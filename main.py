import wsgiref.handlers
import datetime, time, hashlib, urllib, urllib2, re, os
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.api import urlfetch, mail, memcache, users
from google.appengine.ext.webapp import template
from django.utils import simplejson
from pprint import pprint
from datetime import datetime, date, time
from collections import defaultdict
import logging
import base64
import sys

APP_NAME = 'grep-hacker'
EMAIL_FROM = "Dojo Hackers <no-reply@%s.appspotmail.com>" % APP_NAME
DAYS_FOR_KEY = 30

try:
    is_dev = os.environ['SERVER_SOFTWARE'].startswith('Dev')
except:
    is_dev = False

is_prod = not is_dev

def fetch_usernames(use_cache=True):
    usernames = memcache.get('usernames')
    if usernames and use_cache:
        return usernames
    else:
        resp = urlfetch.fetch('http://domain.hackerdojo.com/users', deadline=20)
        if resp.status_code == 200:
            usernames = [m.lower() for m in simplejson.loads(resp.content)]
            skills_dict = {}
            for username in usernames:
                skills_dict[username] = []
            if not memcache.set('usernames', skills_dict, 3600*24):
                logging.error("Memcache set failed.")
            return usernames

def weighted_tags():
    ret = None
    usernames_dict = memcache.get('usernames')
    
    if (not usernames_dict):
        fetch_usernames()
        usernames_dict = memcache.get('usernames')
    
    if (usernames_dict):
        tags = []
        for username in usernames_dict:
            tags += usernames_dict[username]
        d = defaultdict(int)
        for tag in tags:
            d[tag] += 1
        ret = d.items()
        
    return ret

class HackerSkills(db.Expando):
    first_name = db.StringProperty()
    last_name = db.StringProperty()
    email = db.StringProperty()
    status  = db.StringProperty() # None, active, suspended
    skills = db.StringListProperty()
    username = db.StringProperty(required=True)
    
    def full_name(self):
        return '%s %s' % (self.first_name, self.last_name)
    
class MainHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if user:
            logout_url = users.create_logout_url('/')
            w_tags = weighted_tags()
            skill_tags_list = ""
            if (w_tags):
                for k,v in w_tags:
                    skill_tags_list += "{text: \"" + k + "\", weight: " + str(v) + "},\n"
            skill_tags_list = skill_tags_list.rstrip(",\n")
            self.response.out.write(template.render('templates/main.html', locals()))
        else:
            self.redirect(users.create_login_url(self.request.uri), locals())

    def post(self):
        user = users.get_current_user()
        logout_url = users.create_logout_url('/')
        #id = str(m.key().id())
        if user:
            search_tag = self.request.get('search_for')
            search_req = None
            if (search_tag):
                search_req = 1
            self.response.out.write(template.render('templates/main.html', locals()))
        else:
            self.redirect(users.create_login_url(self.request.uri))

class MailHandler(webapp.RequestHandler):
    def get(self, hash):
        member = HackerSkills.all().filter('hash =', hash).get()
        if member:
            if self.request.query_string == 'email':
                spreedly_url = member.spreedly_url()
                mail.send_mail(sender=EMAIL_FROM,
                    to="%s <%s>" % (member.full_name(), member.email),
                    subject="Welcome to Hacker Dojo, %s!" % member.first_name,
                    body=template.render('templates/welcome.txt', locals()))
                self.redirect(self.request.path)
            else:
                success_html = urlfetch.fetch("http://hackerdojo.pbworks.com/api_v2/op/GetPage/page/SubscriptionSuccess/_type/html").content
                success_html = success_html.replace('joining!', 'joining, %s!' % member.first_name)
                is_prod = not is_dev
                self.response.out.write(template.render('templates/success.html', locals()))

class HackerListHandler(webapp.RequestHandler):
    def get(self):
      user = users.get_current_user()
      if not user:
        self.redirect(users.create_login_url(self.request.uri))
      logout_url = users.create_logout_url('/')
      hackers_list = fetch_usernames();
      self.response.out.write(template.render('templates/hackerlist.html', locals()))

class ProfileHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if not user:
          self.redirect(users.create_login_url(self.request.uri))
        else:
          logout_url = users.create_logout_url('/')
          hacker = user.nickname()
          account = HackerSkills.all().filter('username =', hacker).get()
          if (not account):
              # If we already don't have a record of the user, create it
              hs = HackerSkills(username=hacker)
              hs.put()
              account = HackerSkills.all().filter('username =', hacker).get()
              account.skills = []
              account.put()
          email = hacker + "@hackerdojo.com"
          gravatar_url = "http://www.gravatar.com/avatar/" + hashlib.md5(email.lower()).hexdigest()
          if (account.skills):
            skill_set = ', '.join(account.skills)
          else:
            skill_set = []
          my_skill_tags = self._genSkillTags(account.skills)
          self.response.out.write(template.render('templates/profile.html', locals()))
          
    def post(self):
        skill_tags = self.request.get('tags_csv').split(',')
        user = users.get_current_user()
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
        else:
            hacker = user.nickname()
            logout_url = users.create_logout_url('/')
            email = hacker + "@hackerdojo.com"
            gravatar_url = "http://www.gravatar.com/avatar/" + hashlib.md5(email.lower()).hexdigest()
            account = HackerSkills.all().filter('username =', hacker).get()
            if (skill_tags):
                account.skills = skill_tags
            else:
                account.skills = []
            account.put()
            if (account.skills):
                skill_set = ', '.join(account.skills)
            else:
                skill_set = []
            my_skill_tags = self._genSkillTags(account.skills)
            self.response.out.write(template.render('templates/profile.html', locals()))
    
    def _genSkillTags(self, skill_set):
        markup = "["
        if (skill_set):
            for skill in skill_set:
                markup += "\"" + skill + "\","
            markup = markup.rstrip(",")
        markup += "]"
        return markup

class PageNotFound(webapp.RequestHandler):
    def get(self):
      self.response.out.write(template.render('templates/404.html', locals()))
          
def main():
    application = webapp.WSGIApplication([
        ('/', MainHandler),
        ('/hackerlist', HackerListHandler),
        ('/profile', ProfileHandler),
        ('/.*', PageNotFound),
        ], debug=True)
    wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
    main()
