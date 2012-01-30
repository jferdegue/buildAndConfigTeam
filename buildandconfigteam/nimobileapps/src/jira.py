from google.appengine.api import urlfetch
from django.utils import simplejson
from google.appengine.ext import db
from google.appengine.api import users

import urllib
import logging

url = "http://nidigitalsolutions.jira.com/rest"

class jiraCredentials(db.Model):
    user = db.UserProperty(auto_current_user=True, required=True)
    username = db.StringProperty(multiline=False, required=True)
    password = db.StringProperty(multiline=False, required=True)
    session = db.StringProperty(multiline=False, required=False)

class jira():
    session = 0
    
    def isJiraRegistered(self,user):
        if user == None:
            return False
        if db.Query(jiraCredentials).filter('user =', user).count() == 0:
            return False
        else :
            return True
    
    def registerUser(self,username,password):
        if username == None:
            return False
        if password == None:
            return False
        #try:
        if True:    
            for theCredentials in db.Query(jiraCredentials).filter('user =', users.get_current_user()):
                theCredentials.delete()
            jiraCredentials(username=username, password=password).put()
            return True
        #except:
            logging.error("Could not store credentials for the current user")
            return False
        
    def login(self,user):
        # Return Code : 
        # 11 = Invalid Credentials
        # 12 = login is denied due to a CAPTCHA requirement, throtting, or any other reason. It's possible that the supplied credentials are valid, in this case.
        # 13 = any other error (should never happen)
        # 14 - we don't hold credentials for the user
        
        
        if not self.isJiraRegistered(user):
            return 14
        for theCredentials in db.Query(jiraCredentials).filter('user =', user):
            creds=theCredentials
        login=self.lowLevel_apiCall('/auth/1/session',{'username':creds.username, 'password': creds.password})
        if login['code']==200:
            creds.session=login['content']['session']['value']
            creds.put()
            return 1
        elif login['code']==401:
            return 11
        elif login['code']==403:
            return 12
        else:
            return 13
            
    def lowLevel_apiCall(self,method,params,request=urlfetch.POST):
        for theCredentials in db.Query(jiraCredentials).filter('user =', users.get_current_user()):
                creds=theCredentials
        apiUrl = '%s%s' % (url,method)
        validReturnCode = {
                           '/auth/1/session': {urlfetch.POST: [200,401,403]}
        }
        
        params['username']=creds.username
        params['password']=creds.password
        
        result = urlfetch.fetch(url=apiUrl,method=request,payload=simplejson.dumps(params),headers={'Content-Type': 'application/json'})
        if int(result.status_code) in validReturnCode[method][request] :
            try:
                return {'code': int(result.status_code), 'content': simplejson.loads(result.content)}
            except:
                return {'code': int(result.status_code)}
        else:
            errorMessage = "Received %s with status code %s while trying to access Jira method at %s with params %s" % (result.content, result.status_code, apiUrl, simplejson.dumps(params))
            raise Exception(errorMessage)
            logging.error(errorMessage)
        
        