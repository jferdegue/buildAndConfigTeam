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
from google.appengine.api import mail
from time import *
from google.appengine.api import xmpp
from datetime import datetime,date
from suds.client import Client

import jira
import hashlib
import urllib
import os
import logging
import ConfigParser
config = ConfigParser.ConfigParser()
config.readfp(open('config.cfg'))

jiraUrl = 'http://nidigitalsolutions.jira.com/rpc/soap/jirasoapservice-v2?wsdl'
DEV = os.environ['SERVER_SOFTWARE'].startswith('Development')

###################################################################################
###################################################################################
###### DATASTORE DECLARATION
###################################################################################
###################################################################################

    
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
    facet = db.StringProperty(multiline=False, required=True)
    active = db.BooleanProperty(default=True)
    
    def subscribers(self):
        subscribers = []
        for aSubscription in db.Query(subscription).filter('projectStage =',self).filter('channel =','xmpp'):
            subscribers.append(aSubscription.emailStr)
        return subscribers
    
    def subscribe(self,email,channels=['email','xmpp']):
        for aChannel in channels:
            subscription(key_name='%s_%s_%s' % (self.key().name(),aChannel,email.replace('@newsint.co.uk','')), projectStage = self, channel=aChannel, emailStr = email.lower(), subscribed=True).put()
    
    def isSubscribed(self,user,channels=['email','xmpp']):
        retour = {}
        for aChannel in channels:
            subscribed = None
            for aSubscription in db.Query(subscription).filter('user =',user).filter('projectStage =',self).filter('channel =',aChannel):
                subscribed = aSubscription.subscribed
            retour [aChannel] = subscribed
        return retour
    
    def getLatest(self):
        foundOne=False
        for theFacet in db.Query(Facet).filter('project =', self.project).filter('projectStage =',self).order('-logDate').fetch(1):
            foundOne=True
            facetProp= {
                        'filename': blobstore.BlobInfo.get(theFacet.binary).filename,
                        'details': theFacet,
                        }
            #facetProp['extension']=facetProp['filename'][-3:]
        if foundOne==False:
            raise Exception("There are no builds yet available for %s in stage %s" % (self.project.label,self.label))
        return facetProp

    def downloadLinks(self):
        properties = self.getLatest()
        if properties['filename'][-3:]=='ipa':
            nextLink="itms-services://?action=download-manifest&url=https://nimobileapps.appspot.com/buildPlist/%s/a.plist" % (properties['details'].key().id())
        else:
            nextLink="https://%s/serve/%s/%s" % (os.environ['HTTP_HOST'],properties['details'].binary,properties['filename'])
        logging.info('getting shortened url for %s' % nextLink)
        urlRest = 'http://tinyurl.com/api-create.php?url=%s' % nextLink
        result = urlfetch.fetch(urlRest)
        if result.status_code == 200:
            shortLink=result.content
        else:
            raise Exception("error when trying to shorten the url by calling %s" % urlRest)
        
        downloadLinkLong ="https://%s/serveRelease?%s" % (os.environ['HTTP_HOST'], urllib.urlencode({'project':self.project.key().name(), 'projectStage': self.name}))
        logging.info('getting shortened url for %s' % downloadLinkLong)
        urlRest = 'http://tinyurl.com/api-create.php?url=%s' % downloadLinkLong
        result = urlfetch.fetch(urlRest)
        if result.status_code == 200:
            downloadLink=result.content
        else:
            raise Exception("error when trying to shorten the url by calling %s" % urlRest)
        
        return [nextLink, shortLink, downloadLink]
    
class subscription(db.Model):
    projectStage = db.ReferenceProperty(projectStage, required=True, collection_name='subscription_projectStage')
    emailStr = db.StringProperty(multiline=False, required=True)
    channel = db.StringProperty(multiline=False, choices=['email','xmpp'], required=True)
    subscribed = db.BooleanProperty(required=True)

class auditTrail(db.Model):
    user = db.UserProperty(auto_current_user=True)
    description = db.StringProperty(multiline=False, required=True)
    logDate = db.DateTimeProperty(auto_now_add=True)
    project = db.ReferenceProperty(project, required=True, collection_name='project_auditTrail')
    projectStage = db.ReferenceProperty(projectStage, required=True, collection_name='projectStage_auditTrail')
    
class Feedback(db.Model):
    user = db.UserProperty(auto_current_user=True)
    logDate = db.DateTimeProperty(auto_now_add=True)
    auditTrail = db.ReferenceProperty(auditTrail, required=True, collection_name='feedback_auditTrail')
    comment = db.TextProperty()
    type=db.StringProperty(multiline=False)
    score = db.IntegerProperty()
    
class Facet(db.Model):
    project = db.ReferenceProperty(project, required=False, collection_name='facet_project')
    projectStage = db.ReferenceProperty(projectStage, required=False, collection_name='facet_projectstage')
    binary = db.StringProperty(multiline=False)
    logDate = db.DateTimeProperty(auto_now_add=True)
    version = db.StringProperty(multiline=False, required=True)
    
class oneUser(db.Model):
    logDate = db.DateTimeProperty(auto_now_add=True)
    lastSeen = db.DateTimeProperty(auto_now_add=False)
    user = db.UserProperty(auto_current_user=True, required=False)
    emailString = db.StringProperty(multiline=False)
    xmppEnabled = db.BooleanProperty(default=False)
        
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
                
            theUser=oneUser(key_name=user.user_id(), emailString=user.email().lower())
            theUser.put()
            if not theUser.xmppEnabled:
                logging.debug("Sending an invite to %s" % theUser.user.email())
                xmpp.send_invite(theUser.user.email(),'%s@%s.appspotchat.com' % (config.get('xmpp','fromAddress'), config.get('General','appName')))
            
        else:
            greeting=''
        
        if self.request.get('project'):
            projectsDb = [project.get_by_key_name(self.request.get('project'))]
        else:
            projectsDb = db.Query(project).filter("active =",True)
        projects = []
        for oneProject in projectsDb:
            projectsStageDb = db.Query(projectStage).filter("project =",oneProject).filter("active =",True)
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
        try:
        #if True:
            theprojectStage=projectStage.get_by_key_name('%s_%s' % (self.request.get('project'), self.request.get('projectStage')))
        except:
            raise Exception('cannot seem to find the stage %s in project %s' % (self.request.get('projectStage'), self.request.get('project')))
        
        properties=theprojectStage.getLatest()
        theprojectStage.subscribe(user.email())
        (nextLink, shortLink, accessLink) = theprojectStage.downloadLinks()
        if properties['filename'][-3:]=='ipa':
            nextLink="itms-services://?action=download-manifest&url=https://nimobileapps.appspot.com/buildPlist/%s/a.plist" % (properties['details'].key().id())
        else:
            nextLink="https://%s/serve/%s/%s" % (os.environ['HTTP_HOST'],properties['details'].binary,properties['filename'])
        request=auditTrail(description='Request', project=theprojectStage.project, projectStage=theprojectStage, user=user)
        request.put()
        if not mobileDevice:
            urlRest = 'http://tinyurl.com/api-create.php?url=%s' % nextLink
            result = urlfetch.fetch(urlRest)
            if result.status_code == 200:
                shortLink=result.content
            else:
                raise Exception("error when trying to shorten the url by calling %s" % urlRest)
        if config.get('General','requireLogin')=='yes':
            if mobileDevice:
                subject='We would love your feedback'
                body='Do you want to tell us about your experience ? Just click the link below or paste it in your browser. %s' % 'https://'+os.environ['HTTP_HOST']+'/feedback/'+str(request.key().id())
            else:
                subject='Your download is ready'
                body='You can download the product you requested by clicking the following link %s Once you have looked at it, we would love that you provide us feedback. Just click the following link %s for that' % (shortLink, 'https://'+os.environ['HTTP_HOST']+'/feedback/'+str(request.key().id()))
            mail.send_mail(sender=config.get('General','emailSender'),
              to=user.email(),
              subject=subject,
              body="""
Dear %s:

%s

Please let us know if you have any questions.

The Build and Config Team
""" % (user.nickname(), body))
        if mobileDevice:
            auditTrail(description='Download', project=theprojectStage.project, projectStage=theprojectStage, user=user).save()
            self.response.out.write('<a href=%s>Download the app</a>' % nextLink)
        else:
            
            template_values = {
                               'greeting': greeting,
                               'itmsLink': nextLink,
                               'shortLink': shortLink,
                               'url': 'http://chart.apis.google.com/chart?%s' % urllib.urlencode({'cht': 'qr', 'chs': '300x300', 'chl': 'http://nimobileapps.appspot.com/showClick/%s'% theprojectStage.key().name(), 'chld': 'H|0'}),
                               #'url': 'http://chart.apis.google.com/chart?%s' % urllib.urlencode({'cht': 'qr', 'chs': '300x300', 'chl': nextLink, 'chld': 'H|0'})
                               }
            path = os.path.join(os.path.dirname(__file__), 'template','downloadFacet.htm')
            self.response.out.write(template.render(path, template_values))
            
class serveRelease(webapp.RequestHandler):
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
            
        mobileBrowsers=['iPad','Android','iPhone']
        mobileDevice=False
        agent=self.request.user_agent
        for oneToken in mobileBrowsers:
            if not agent.replace(oneToken,"") == agent:
                mobileDevice=True
                break
        try:
        #if True:
            theprojectStage=projectStage.get_by_key_name('%s_%s' % (self.request.get('project'), self.request.get('projectStage')))
        except:
            raise Exception('cannot seem to find the stage %s in project %s' % (self.request.get('projectStage'), self.request.get('project')))
        
        properties=theprojectStage.getLatest()
        theprojectStage.subscribe(user.email())
        (nextLink, shortLink, longlink) = theprojectStage.downloadLinks()
        if properties['filename'][-3:]=='ipa':
            nextLink="itms-services://?action=download-manifest&url=https://nimobileapps.appspot.com/buildPlist/%s/a.plist" % (properties['details'].key().id())
        else:
            nextLink="https://%s/serve/%s/%s" % (os.environ['HTTP_HOST'],properties['details'].binary,properties['filename'])
        
        request=auditTrail(description='Request', project=theprojectStage.project, projectStage=theprojectStage, user=user)
        request.put()
        if not mobileDevice:
            urlRest = 'http://tinyurl.com/api-create.php?url=%s' % nextLink
            result = urlfetch.fetch(urlRest)
            if result.status_code == 200:
                shortLink=result.content
            else:
                raise Exception("error when trying to shorten the url by calling %s" % urlRest)
        if config.get('General','requireLogin')=='yes':
            if mobileDevice:
                subject='We would love your feedback'
                body='Do you want to tell us about your experience ? Just click the link below or paste it in your browser. %s' % 'https://'+os.environ['HTTP_HOST']+'/feedback/'+str(request.key().id())
            else:
                subject='Your download is ready'
                body='You can download the product you requested by clicking the following link %s Once you have looked at it, we would love that you provide us feedback. Just click the following link %s for that' % (shortLink, 'http://'+os.environ['HTTP_HOST']+'/feedback/'+str(request.key().id()))
            mail.send_mail(sender=config.get('General','emailSender'),
              to=user.email(),
              subject=subject,
              body="""
Dear %s:

%s

Please let us know if you have any questions.

The Build and Config Team
""" % (user.nickname(), body))
        if mobileDevice:
            auditTrail(description='Download', project=theprojectStage.project, projectStage=theprojectStage, user=user).save()
            #self.response.out.write('<a href=%s>Click to install the app</a>' % nextLink)
            self.redirect(nextLink)
        else:
            template_values = {
                               'greeting': greeting,
                               'itmsLink': nextLink,
                               'shortLink': shortLink,
                               #'url': 'http://chart.apis.google.com/chart?%s' % urllib.urlencode({'cht': 'qr', 'chs': '300x300', 'chl': nextLink, 'chld': 'H|0'}),
                               'message': 'The link is %s' % nextLink,
                               'url': 'http://chart.apis.google.com/chart?%s' % urllib.urlencode({'cht': 'qr', 'chs': '300x300', 'chl': 'http://nimobileapps.appspot.com/showClick/%s'% theprojectStage.key().name(), 'chld': 'H|0'}),
                               }
            path = os.path.join(os.path.dirname(__file__), 'template','downloadFacet.htm')
            self.response.out.write(template.render(path, template_values))
    
    post=get
    
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
        newProjectStage = projectStage.get_or_insert(key_name=self.request.get('project')+"_"+self.request.get('name'),facet=self.request.get('facet'),project=containingProject, name=self.request.get('name'), label=self.request.get('label')) 
        if self.request.get('defaultStage')=="yes":
            for oneStage in db.Query(projectStage).filter('project =',self.request.get('project')).filter('isDefault =',True):
                oneStage.isDefault=False
                oneStage.save()
            newProjectStage.isDefault = True
            newProjectStage.save()
        self.redirect("/addProjectStage?%s" % urllib.urlencode({"message": str(newProjectStage.name)+" successfully added to project " + str(newProjectStage.project.key().name())}))


class buildPlist(webapp.RequestHandler):
    def get(self,facetId):
        theFacet=Facet.get_by_id(int(facetId))
        if theFacet==None:
            self.response.out.write('This release is not available anymore. Please <a href=/>click here</a> to get a new one')
            return
        
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
            
            
        template_values = {
        	                      'facet': theFacet,
                                  'facetDetails': theFacet.projectStage.getLatest(),
                                  'url': os.environ['HTTP_HOST'],
        }
        self.response.headers["Content-Type"] = "text/xml"
        path = os.path.join(os.path.dirname(__file__), 'template','buildPlist.xml')
        
        self.response.out.write(template.render(path, template_values))

class receiveFacet(webapp.RequestHandler):
    def get(self):
        upload_url = blobstore.create_upload_url('/upload')
        self.response.out.write(upload_url)

class UploadHandler(blobstore_handlers.BlobstoreUploadHandler):
    def post(self):
        upload_files = self.get_uploads('facet')  # 'file' is file upload field in the form
        blob_info = upload_files[0]
        theproject = project.get_by_key_name(self.request.get('project'))
        if theproject==None:
            raise Exception("Cannot find project %s" % self.request.get('project'))
        theprojectStage = projectStage.get_by_key_name('%s_%s' % (self.request.get('project'),self.request.get('stage')))
        if theprojectStage==None:
            raise Exception('Cannot find projectStage %s_%s' % (self.request.get('project'),self.request.get('stage')))
        Facet(project=theproject, projectStage=theprojectStage, binary=str(blob_info.key()), version=str(self.request.get('version'))).put()
        for anEmail in theprojectStage.subscribers():
            xmpp.send_message(anEmail, """A new release is available for project %s in stage %s. You can get it from %s""" % (theprojectStage.project.label, theprojectStage.label, theprojectStage.downloadLinks()[2]), from_jid='%s@%s.appspotchat.com' % (config.get('xmpp','fromAddress'), config.get('General','appName')))

class ServeHandler(blobstore_handlers.BlobstoreDownloadHandler):
    def get(self, resource):
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
        resource = str(urllib.unquote(resource))
        blob_info = blobstore.BlobInfo.get(resource)
        self.send_blob(blob_info)

class feedback(webapp.RequestHandler):
    def get(self,requestId):
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
        initialRequest=auditTrail.get_by_id(int(requestId))
        if not initialRequest.user==user:
            self.response.out.write('We except %s to give us feedback on this release, however you are connected as %s. Could you please logout and reconnect as %s ?' % (initialRequest.user.nickname, user.nickname, initialRequest.user.nickname))
            return
        template_values = {
                           'greeting': greeting,
                           'initialRequest':initialRequest,
                           'GoogleLibraryKey': config.get('Third Parties','GoogleLibraryKey'),
                           }
        path = os.path.join(os.path.dirname(__file__), 'template','feedback.htm')
        self.response.out.write(template.render(path, template_values))
    
    def post(self,requestId):
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
        
        theAuditTrail=auditTrail.get_by_id(int(requestId))
        thefeedback=Feedback(auditTrail=theAuditTrail,comment=self.request.get('comment'),type=self.request.get('type'),score=int(10*float(self.request.get('score'))))
        thefeedback.put()
        auditTrail(description='Feedback', project=theAuditTrail.project, projectStage=theAuditTrail.projectStage, user=user).save()
        template_values = {
                           'greeting': greeting,
                           'GoogleLibraryKey': config.get('Third Parties','GoogleLibraryKey'),
                           }
        path = os.path.join(os.path.dirname(__file__), 'template','feedbackPost.htm')
        self.response.out.write(template.render(path, template_values))
    
class backend(webapp.RequestHandler):
    def get(self):
        client = Client(jiraUrl)
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
            
        message=''
        if self.request.get('key'):
            theStage=projectStage.get_by_key_name(self.request.get('key'))
            theStage.label=self.request.get('label')
            theStage.facet=self.request.get('facet')
            if self.request.get('active')=='yes':
                theStage.active=True
            else:
                theStage.active=False
            theStage.save()
            message='The stage %s from project %s has been changed as requested' % (theStage.label, theStage.project.label)
        if self.request.get('currentDefault'):
            theStage=projectStage.get_by_key_name(self.request.get('currentDefault'))
            theStage.isDefault=False
            message=theStage.label
            theStage.save()
            theStage=projectStage.get_by_key_name(self.request.get('newDefault'))
            theStage.isDefault=True
            theStage.active=True
            theStage.save()
        allProjects=project.all()
        p=[]
        for oneProject in allProjects:
            oneP={'details':oneProject, 'name':oneProject.key().name(), 'stages':[] }
            for oneStage in db.Query(projectStage).filter('project =',oneProject):
                #Facet(project=oneStage.project,projectStage=oneStage,binary='toto',version='4.2.1').put()
                oneStage.subscribe(user.email())
                oneP['stages'].append(oneStage)
            p.append(oneP)
        template_values = {
            'projects': p,
            'message': message,
        }
        path = os.path.join(os.path.dirname(__file__), 'template','backend.htm')
        self.response.out.write(template.render(path, template_values))
    
    post=get

class maintenance(webapp.RequestHandler):
    def get(self):
        # First we build a list of the latest facets, these should never be deleted
        toKeep = []
        for oneprojectStage in db.Query(projectStage):
            for latest in db.Query(Facet).filter('projectStage =',oneprojectStage).order('-logDate').fetch(1):
                logging.info('%s should be kept' % latest.key().id())
                toKeep.append(latest.key().id())
        for oneFacet in db.Query(Facet):
            if not oneFacet.key().id() in toKeep:
                logging.info('%s is going to be deleted' % oneFacet.key().id())
                blobstore.delete(oneFacet.binary)
                oneFacet.delete()
   
class xmppAvailable(webapp.RequestHandler):
    def post(self):
        fromEmail = self.request.get('from').split('/')[0].lower()
        logging.info("""%s is available""" % fromEmail)
        theUser = None
        for aUser in db.Query(oneUser).filter('emailString =',str(fromEmail)):
            logging.debug('The user has id %s' % aUser.key().name())
            theUser = aUser
        if theUser == None:
            logging.error("Received available signal from user %s. However no user with this email could be found" % fromEmail)
            return
        previousLastSeen = theUser.lastSeen
        theUser.lastSeen = datetime.today()
        #theUser.lastSeen = datetime.strptime("21/11/06 16:30", "%d/%m/%y %H:%M")
        theUser.xmppEnabled = True
        theUser.put()
        
        availableReleases = []
        for aSubscription in db.Query(subscription).filter('emailStr =',str(fromEmail)).filter('channel =', 'xmpp').filter('subscribed =',True):
            logging.info('Subscribed to %s' % aSubscription.projectStage.key().name())
            for aFacet in db.Query(Facet).filter('projectStage =',aSubscription.projectStage).filter('logDate >', previousLastSeen).order('-logDate').fetch(1):
                logging.info('%s is available' % aFacet.key().id())
                availableReleases.append(aFacet)
        
        
        for oneRelease in availableReleases:
            messageText = """new Release available for %s at stage %s. Download it from %s""" % (oneRelease.project.label, oneRelease.projectStage.label, oneRelease.projectStage.downloadLinks()[2])
            #xmpp.send_invite(myConfig.emailFrom,'%s___%s@%s.appspotchat.com' % (myConfig.namespace,self.key().name(),config.get('Architecture','appengineId')))
            xmpp.send_message(theUser.emailString, messageText, from_jid='%s@%s.appspotchat.com' % (config.get('xmpp','fromAddress'), config.get('General','appName')))
        
class createJira(webapp.RequestHandler):
    def get(self,feedbackId):
        if config.get('General','requireLogin')=='yes':
            user = users.get_current_user()
            if not user:
                self.redirect(users.create_login_url("/"))
                return
            else:
                greeting = ("Welcome, %s! (<a href=\"%s\">sign out</a>)" % 
                            (user.nickname(), users.create_logout_url("/")))
        else:
            self.response.out.write('This function is only available to logged in users')
            return
        message = None
        oneJira = jira.jira()
        
        login = oneJira.login(user=users.get_current_user())
        if login == 14:
            template_values = {
            }
            path = os.path.join(os.path.dirname(__file__), 'template','createJira_1.htm')
            self.response.out.write(template.render(path, template_values))
        elif login==11:
            template_values = {
                'message': 'Could not connect you to Jira. Can you please reenter your credentials ?'
            }
            path = os.path.join(os.path.dirname(__file__), 'template','createJira_1.htm')
            self.response.out.write(template.render(path, template_values))
        elif login>10:
            self.response.out.write("It seems that we can't log you in into Jira. Sorry about that")
        
        self.response.out.write("You made it to the end")
        
    def post(self,feedbackId):
       if config.get('General','requireLogin')=='yes':
            user = users.get_current_user()
            if not user:
                self.redirect(users.create_login_url("/"))
                return
            else:
                greeting = ("Welcome, %s! (<a href=\"%s\">sign out</a>)" % 
                            (user.nickname(), users.create_logout_url("/")))
       else:
            self.response.out.write('This function is only available to logged in users')
            return
       if jira.jira().registerUser(self.request.get('username'), self.request.get('password')):
           self.get(feedbackId)       

class showClick(webapp.RequestHandler):
    def get(self,keyName):
        theprojectStage = projectStage.get_by_key_name('%s' % keyName)
        (nextLink, shortLink, accessLink) = theprojectStage.downloadLinks()
        if config.get('General','requireLogin')=='yes':
            user = users.get_current_user()
            if not user:
                self.response.out.write('<h1 style="padding:50px">Please open your browser and login with your News Int account to Gmail. Once this is done, come back and click <a href=%s>here</a>.'% nextLink)
                return
            else:
                self.response.out.write("<h1 style='padding:50px'><a href=%s>Download & Install the app</a></h1>" % nextLink)
        else:
            self.response.out.write("<h1 style='padding:50px'><a href=%s>Download & Install the app</a></h1>" % nextLink)
        
    post=get

def main():
    application = webapp.WSGIApplication([
    	('/', MainHandler),
        ('/addProject', addProject),
        ('/addProjectStage', addProjectStage),
    	('/buildPlist/([0-9]+)/a.plist', buildPlist),
        ('/feedback/([0-9]+)', feedback),
        ('/backend', backend),
        ('/upload', UploadHandler),
        ('/serve/([^/]+).*?', ServeHandler),
        ('/receiveFacet', receiveFacet),
        ('/maintenance', maintenance),
        ('/createJira/([0-9]+)', createJira),
        #('/_ah/xmpp/presence/available/', xmppAvailable),
        ('/serveRelease', serveRelease),
        ('/showClick/([^/]+)', showClick),
    									 ],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
