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
from sets import Set
import logging
import base64
import sys

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
                account = HackerSkills.all().filter('username =', username).get()
                if (not account):
                    skills_dict[username] = []
                else:
                    skills_dict[username] = account.skills
            if not memcache.set('usernames', skills_dict, 3600*24):
                logging.error("Memcache set failed.")
        return usernames

def fetch_usernames_dict():
    usernames_dict = memcache.get('usernames')
    if (not usernames_dict):
        fetch_usernames()
        usernames_dict = memcache.get('usernames')
    
    return usernames_dict

def weighted_tags():
    ret = None
    usernames_dict = fetch_usernames_dict()
    
    if (usernames_dict):
        tags = []
        for username in usernames_dict:
            tags += usernames_dict[username]
        d = defaultdict(int)
        for tag in tags:
            d[tag] += 1
        ret = d.items()
        
    return ret

def available_tags():
    avail_tags = memcache.get('available_tags')
    if avail_tags:
        return avail_tags
    else:
        usernames_dict = fetch_usernames_dict()
        if (usernames_dict):
            tags = []
            for username in usernames_dict:
                tags += usernames_dict[username]
            set = Set(tags)
            if not memcache.set('available_tags', list(set), 3600*24):
                logging.error("Memcache set failed.")
            return list(set)

def available_tags_str():
    avail_tags = available_tags()
    tags_list = ""
    if (len(avail_tags) > 1):
        tags_list = "["
        for tag in avail_tags:
          tags_list += "\""+tag+"\","
        tags_list = tags_list.rstrip(",")
        tags_list += "]"
    else:
        tags_list = "[\"c++\", \"java\", \"php\", \"coldfusion\", \"javascript\", \"asp\", \"ruby\", \"python\", \"c\", \"scala\", \"groovy\", \"haskell\", \"perl\"]"
    return tags_list

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
            tags_list = available_tags_str()
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
            tags_list = available_tags_str()
            self.response.out.write(template.render('templates/main.html', locals()))
        else:
            self.redirect(users.create_login_url(self.request.uri))

class MailHandler(webapp.RequestHandler):
    def get(self):
        username_to = self.request.get('to')
        user = users.get_current_user().nickname()
        mail.send_mail(sender=user+"@hackerdojo.com",
            to="<%s>" % (username_to+"@hackerdojo.com"),
            subject="%s is requesting your help" % (user+"@hackerdojo.com"),
            body= "%s thinks that you might be to able to help him/her. Wanna help?" % (user))
        self.redirect("/")

class HackerListHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if not user:
            self.redirect(users.create_login_url(self.request.uri))
        logout_url = users.create_logout_url('/')
        usernames_dict = fetch_usernames_dict()
        rows = []
        for k in usernames_dict:
            v = "N/A"
            if (usernames_dict[k]):
                v = ",".join(usernames_dict[k])
            rows.append("<tr><td>" + k + "</td><td>" + v + "</td><td><a href='/contact?to=" + k + "'>ping</a></td></tr>")
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
            tags_list = available_tags_str()
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
            tags_list = available_tags_str()
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
        ('/contact', MailHandler),
        ('/.*', PageNotFound),
        ], debug=True)
    wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
    main()
