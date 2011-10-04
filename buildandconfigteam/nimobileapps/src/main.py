#!/usr/bin/env python
#
# Copyright 2007 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
from google.appengine.ext import webapp
from django.utils import simplejson
from google.appengine.ext.webapp import util
from google.appengine.ext import db
from google.appengine.ext.webapp import template
from google.appengine.api import users
from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers  
from google.appengine.api.images import get_serving_url
from google.appengine.api import urlfetch
from google.appengine.api import users
from time import *

import hashlib
import urllib
import os
import logging
import ConfigParser
config = ConfigParser.ConfigParser()
config.readfp(open('config.cfg'))

BACKEND="http://172.22.10.234/s3fileserver/"
DEV = os.environ['SERVER_SOFTWARE'].startswith('Development')

###################################################################################
###################################################################################
###### DATASTORE DECLARATION
###################################################################################
###################################################################################
class auditTrail(db.Model):
    user = db.UserProperty(auto_current_user=True)
    description = db.StringProperty(multiline=False)
    logDate = db.DateTimeProperty(auto_now_add=True)

class project(db.Model):
    picture = db.LinkProperty(required=False)
    logDate = db.DateTimeProperty(auto_now_add=True)
    user = db.UserProperty(auto_current_user=True)
    active = db.BooleanProperty(default=True)
    label = db.StringProperty(multiline=False)
    label = db.StringProperty(multiline=False)
    
class projectStage(db.Model):
    project = db.ReferenceProperty(project, required=True, collection_name='project')
    name = db.StringProperty(multiline=False)
    label = db.StringProperty(multiline=False)
    logDate = db.DateTimeProperty(auto_now_add=True)
    user = db.UserProperty(auto_current_user=True)
    isDefault = db.BooleanProperty(default=False)

class awsLink(db.Model):
    user = db.UserProperty(auto_current_user=True)
    logDate = db.DateTimeProperty(auto_now_add=True)
    projectStage = db.ReferenceProperty(projectStage, required=True, collection_name='projectStage')
    generatedLink = db.StringProperty(multiline=False)
    
    def get(self,projectStageKey):
        self.response.out.write("great")
        
###################################################################################
###################################################################################
###### END OF DATASTORE DECLARATION
###################################################################################
###################################################################################


class MainHandler(webapp.RequestHandler):
    def get(self):
        if config.get('General','requireLogin')=='yes':
            user = users.get_current_user()
            if not user:
                self.redirect(users.create_login_url("/"))
                return
            else:
                greeting = ("Welcome, %s! (<a href=\"%s\">sign out</a>)" % 
                            (user.nickname(), users.create_logout_url("/")))
        else:
            greeting=''
            
        projectsDb = db.Query(project).filter("active =",True)
        projects = []
        for oneProject in projectsDb:
            projectsStageDb = db.Query(projectStage).filter("project =",oneProject)
            stages=[]
            for oneProjectStage in projectsStageDb:
                
                if oneProjectStage.isDefault:
                    defaultStage=oneProjectStage
                else:
                    stages.append({'name':oneProjectStage.name,'label':oneProjectStage.label})
            newP={
                  'name':oneProject.key().name(),
                  'label':oneProject.label,
                  'picture':oneProject.picture,
                  'defaultStage':defaultStage,
                  'stages':stages,
                  }
            projects.append(newP)
        template_values = {
            'projects': projects,
            'GoogleLibraryKey': config.get('Third Parties','GoogleLibraryKey'),
            'greeting': greeting,
        }
        path = os.path.join(os.path.dirname(__file__), 'template','MainHandler.htm')
        self.response.out.write(template.render(path, template_values))
    
    def post(self):
        if config.get('General','requireLogin')=='yes':
            user = users.get_current_user()
            if not user:
                self.redirect(users.create_login_url("/"))
                return
            else:
                greeting = ("Welcome, %s! (<a href=\"%s\">sign out</a>)" % 
                            (user.nickname(), users.create_logout_url("/")))
        else:
            greeting=''
            
        mobileBrowsers=['iPad','Android','iPhone']
        mobileDevice=False
        agent=self.request.user_agent
        for oneToken in mobileBrowsers:
            if not agent.replace(oneToken,"") == agent:
                mobileDevice=True
                break
        itmsLink="itms-services://?action=download-manifest&url=https://nimobileapps.appspot.com/buildPlist/%s/%s/%s/a.plist" % (self.request.get('project'), self.request.get('projectStage'), '.AAAartifactsAAAMarioDemoApp.ipa')
        if mobileDevice:
            self.redirect(itmsLink)
        else:
            urlRest = 'http://tinyurl.com/api-create.php?url=%s' % itmsLink
            result = urlfetch.fetch(urlRest)
            if result.status_code == 200:
                shortLink=result.content
            else:
                raise Exception("error when trying to shorten the url by calling %s" % urlRest)
            template_values = {
                               'itmsLink': itmsLink,
                               'shortLink': shortLink,
                               'url': 'http://chart.apis.google.com/chart?%s' % urllib.urlencode({'cht': 'qr', 'chs': '300x300', 'chl': itmsLink, 'chld': 'H|0'})
                               }
            path = os.path.join(os.path.dirname(__file__), 'template','downloadFacet.htm')
            self.response.out.write(template.render(path, template_values))
            
    
class addProject(blobstore_handlers.BlobstoreUploadHandler):
    def get(self):
        template_values = {
            'uploadLink': blobstore.create_upload_url('/addProject'),
        }
        if DEV:
            template_values['uploadLink']='/addProject'
        if self.request.get('message'):
            template_values['message']=self.request.get('message')
        path = os.path.join(os.path.dirname(__file__), 'template','addProject.htm')
        self.response.out.write(template.render(path, template_values))
        
    def post(self):
        newProject = project.get_or_insert(key_name=self.request.get('name'))
        try:
            upload_files = self.get_uploads('picture')  # 'file' is file upload field in the form
            blob_info = upload_files[0]
            newProject.picture=get_serving_url(blob_info.key())
        except:
            newProject.picture = 'http://s3.amazonaws.com/files.posterous.com/mir/EIop8BBFywxfMGLQX36umw2uOQVdbmUU2KxsdJobFMpHCeBcPaZeYBut3o4q/IMG00054-20100721-1443.jpg.scaled.500.jpg?AWSAccessKeyId=AKIAJFZAE65UYRT34AOQ&Expires=1317651343&Signature=zT6UvAnHs%2FcIlfiZhsvLOWHvvwE%3D'
        newProject.label=self.request.get('label')
        newProject.save()
        self.redirect("/addProject?%s" % urllib.urlencode({"message": str(newProject.key().name())+" successfully added"}))

class addProjectStage(webapp.RequestHandler):
    def get(self):
        projectsDb = db.Query(project).filter("active =",True)
        projects = []
        for oneProject in projectsDb:
            oneProject.name = oneProject.key().name()
            projects.append(oneProject)
        template_values = {
            'projects': projects,
        }
        if self.request.get('message'):
            template_values['message']=self.request.get('message')
        path = os.path.join(os.path.dirname(__file__), 'template','addProjectStage.htm')
        self.response.out.write(template.render(path, template_values))
        
    def post(self):
        containingProject = project.get_by_key_name(self.request.get('project'))
        newProjectStage = projectStage.get_or_insert(key_name=self.request.get('project')+"_"+self.request.get('name'),project=containingProject, name=self.request.get('name'), label=self.request.get('label')) 
        if self.request.get('defaultStage')=="yes":
            newProjectStage.isDefault = True
            newProjectStage.save()
        self.redirect("/addProjectStage?%s" % urllib.urlencode({"message": str(newProjectStage.name)+" successfully added to project " + str(newProjectStage.project.key().name())}))


class buildPlist(webapp.RequestHandler):
    def get(self,project,environment,artifact):
        validFrom=str(int(time()))
        artifactUnencoded=artifact.replace("AAA",'/').replace("%7C",'/')
        strToSign=config.get('Third Parties','AmazonServingKey')+"+artifact="+artifactUnencoded+"+environment="+environment+"+project="+project+"+validFrom="+validFrom
        sig = hashlib.md5(strToSign).hexdigest()
        params = {
        	'project': project,
        	'environment' : environment,
        	'artifact': artifactUnencoded,
        	'sig': sig,
        	'validFrom': validFrom,
        }
        link=BACKEND+"?"+urllib.urlencode(params)
        
        template_values = {
        	'params': params,
        	'link': link,
        	'version': environment+" as of "+ctime(float(validFrom))
        }
        self.response.headers["Content-Type"] = "text/xml"
        path = os.path.join(os.path.dirname(__file__), 'template','buildPlist.xml')
        self.response.out.write(template.render(path, template_values))

def main():
    application = webapp.WSGIApplication([
    	('/', MainHandler),
        ('/addProject', addProject),
        ('/addProjectStage', addProjectStage),
    	('/buildPlist/([^/]+)/([^/]+)/([^/]+)/a.plist', buildPlist),
    									 ],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
