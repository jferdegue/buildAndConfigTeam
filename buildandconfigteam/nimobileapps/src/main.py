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
from google.appengine.ext.webapp import util
from google.appengine.ext import db
from google.appengine.ext.webapp import template

from time import *

import hashlib
import urllib
import os


PRIVATEKEY="48jfgfs"
BACKEND="http://vm-sles11-239/s3fileserver/"

class MainHandler(webapp.RequestHandler):
    def get(self):
        self.response.out.write('Hello world!')

class buildPlist(webapp.RequestHandler):
    def get(self,project,environment,artifact):
		validFrom=str(int(time()))
		artifactUnencoded=artifact.replace("|",'/').replace("%7C",'/')
		strToSign=PRIVATEKEY+"+artifact="+artifactUnencoded+"+environment="+environment+"+project="+project+"+validFrom="+validFrom
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
    	('/buildPlist/([^/]+)/([^/]+)/([^/]+)/a.plist', buildPlist),
    									 ],
                                         debug=True)
    util.run_wsgi_app(application)


if __name__ == '__main__':
    main()
