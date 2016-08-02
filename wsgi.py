from sched_jobs import start_scheduled_jobs, populate_db
from flask import Flask, request, session, render_template, g 
import json
from peewee import *
import requests
from db_tables import *
from gunicorn.instrument.statsd import METRIC_VAR
import ast
from HTMLParser import HTMLParser
import sys, socket

'''    
**********************************************************************************************************
**********************WP REST API (https://developer.wordpress.com/docs/api/)*****************************
**********example: https://public-api.wordpress.com/rest/v1.1/sites/rhelblog.redhat.com/posts/************  
**********************************************************************************************************
************************************NOTES TO PROJECT INHERITOR********************************************
*********1) During OAuth, the redirect URL MUST match the URL of the WordPress application****************
*********(which is bound to a single WordPress (mine, currently) account. For local/OpenShift*************
***testing, you'll need to create your own WordPress application (https://developer.wordpress.com/apps/)**
*********- one with a redirect URL (e.g., 127.0.0.1) and another for OpenShift deployments.***************
**********************************************************************************************************
*********2) When running locally vs. deploying on OpenShift, change WordPressAuth.local accordingly.******
**********************************************************************************************************
**************3) To test locally, cd into root project directory, then run "python wsgi.py"***************
**********************************************************************************************************
'''

application = Flask(__name__)
wp_blogs = ['verticalindustriesblog.redhat.com', 'captainkvm.com', 'rhelblog.redhat.com', 'developerblog.redhat.com', 'redhatstackblog.redhat.com', \
            'redhatstorage.redhat.com', 'servicesblog.redhat.com', 'mobileblog.redhat.com', 'middlewareblog.redhat.com', 'cloudformsblog.redhat.com']
non_wp_blogs = ['https://opensource.com/feed', 'http://stef.thewalter.net/feeds/all.atom.xml', 'http://crunchtools.com/feed', \
                'http://community.redhat.com/blog/feed.xml', 'https://blog.openshift.com/feed/', 'http://www.projectatomic.io/blog/feed.xml', \
                'https://www.redhat.com/en/rss/blog']
redirected_urls = {"redhat.com/blog/verticalindustries":"verticalindustriesblog.redhat.com", "developers.redhat.com":"developerblog.redhat.com", \
                   "redhat.com/blog/mobile":"mobileblog.redhat.com"}

def find_between(s, first, last):
    try:
        start = s.rindex(first) + len(first)
        end = s.rindex(last, start)
        return s[start:end]
    except ValueError:
        return ""

def strip_tags(html):
    code_to_symbol = HTMLParser()
    return code_to_symbol.unescape(html)

class WordPressAuth:
    
    client_secret = None
    client_id = None
    redirect_uri = None
    auth_code = None
    access_token = None
    
    def __init__(self):
        self.local = False #False if deploying on OS
        self.client_id = OAuthInfo.select(OAuthInfo.client_id).where(OAuthInfo.local == self.local).scalar()
        self.redirect_uri = OAuthInfo.select(OAuthInfo.redirect_uri).where(OAuthInfo.local == self.local).scalar()
        self.client_secret = OAuthInfo.select(OAuthInfo.client_secret).where(OAuthInfo.local == self.local).scalar()
    
    def prompt_authentication(self):
        auth_code_response = requests.get('https://public-api.wordpress.com/oauth2/authorize?client_id=' + self.client_id + '&redirect_uri=' + \
                                          self.redirect_uri + '&response_type=code&scope=global') #LOCAL
        WordPressAuth.auth_code = (request.args.get("code")) #retrieve code wp supplies after user authenticates
        if (WordPressAuth.auth_code != None and WordPressAuth.access_token == None):      
            return self.get_token()
        elif (WordPressAuth.auth_code != None and WordPressAuth.access_token != None): #gets called on page refresh
            return auth_top_time_query_options()
        return auth_code_response.content #1st pass to function, begin OAuth workflow
     
    def get_token(self):
        token_response = requests.post('https://public-api.wordpress.com/oauth2/token', \
                                 data={'client_secret':self.client_secret, \
                                 'code':self.auth_code, 'redirect_uri':self.redirect_uri, 'client_id':self.client_id, 'grant_type': 'authorization_code'})
        print(token_response.json()[u'access_token'] +  " TEST")
        WordPressAuth.access_token = token_response.json()[u'access_token']
        return auth_top_time_query_options() 

def auth_top_time_query_options(answer = None, results = 0):
    """The main view in it's pre or post-queried state, as per the value of @param - 'answer'.
    I.e., populates all the dropdowns. If provided an answer, renders that as well."""
    authors = []
    titles = []
    post_date = []
    tags = set()
    hosts = set()
    for row in Post.select(Post.author).distinct().group_by(Post.author):
        authors.append(row.author)
    for row in Post.select(Post.title).distinct().group_by(Post.title):
        titles.append(row.title)
    for row in Post.select(Post.tags).distinct().group_by(Post.tags):
        row.tags = ast.literal_eval("[" + str(row.tags) + "]") #convert string representation in database to a list
        for tag_list in row.tags:
            for tag in tag_list:
                tags.add(tag)
    for row in Post.select(Post.url).distinct().group_by(Post.url):
        for blog in wp_blogs, non_wp_blogs: #returns a tuple of the two blog types
            for blog in blog:
                if blog in row.url: #wordpress
                    hosts.add(blog)
                    break
                elif find_between(blog, "http://www.", "/blog/feed.xml") in row.url and find_between(blog, "http://www.", "/blog/feed.xml") != "": #project atomic
                    hosts.add(find_between(blog, "http://www.", "/blog/feed.xml"))
                    break
                elif find_between(blog, "https://", "/feed") in row.url and find_between(blog, "https://", "/feed") != "": #opensource.com, blog.openshift.com
                    hosts.add(find_between(blog, "https://", "/feed"))
                    break
                elif find_between(blog, "http://", "/feed") in row.url and find_between(blog, "http://", "/feed") != "": #crunchtools, stef.thewalter.net
                    hosts.add(find_between(blog, "http://", "/feed"))
                    break
                elif find_between(blog, "http://", "/blog/feed.xml") in row.url and find_between(blog, "http://", "/blog/feed.xml") != "": #community.redhat.com
                    hosts.add(find_between(blog, "http://", "/blog/feed.xml"))
                    break
                elif find_between(blog, "https://www.", "/en/rss/blog") in row.url and find_between(blog, "https://www.", "/en/rss/blog") == "redhat.com": #redhat.com
                    hosts.add(find_between(blog, "https://www.", "/en/rss/blog"))
                    break
                else:
                    for redirect_url in redirected_urls.keys():
                        if redirect_url in row.url:
                            hosts.add(redirected_urls[redirect_url])
                            break 
    return render_template("index.html", authors = authors, titles = titles, tags = sorted(tags), hosts=sorted(hosts), answer = answer, results = results)

@application.route("/auth_top_time_query", methods=["GET", "POST"])
def auth_top_time_query():
    """Called from index.html as the action for the submit button. Creates an answer to the user's
    query to be rendered."""
    if request.method == "POST":      
        answer = []
        
        authors = set(author.decode('unicode_escape').encode('ascii', 'ignore').strip() for author in request.form.getlist('author'))
        topics = set(topic.decode('unicode_escape').encode('ascii', 'ignore').strip() for topic in request.form.getlist('topic'))
        start_date = str(request.form.getlist('start_date')).decode('unicode_escape').encode('ascii', 'ignore').strip()[1:-1]
        end_date = str(request.form.getlist('end_date')).decode('unicode_escape').encode('ascii', 'ignore').strip()[1:-1]
        blogs = set(blog.decode('unicode_escape').encode('ascii', 'ignore').strip() for blog in request.form.getlist('filter'))
        
        blogs_selected = True if (len(blogs) > 0) else False
        authors_selected = True if (len(authors) > 0) else False
        topics_selected = True if (len(topics) > 0) else False
        start_date_selected = True if (len(start_date) > 0) else False
        end_date_selected = True if (len(end_date) > 0) else False
        
        sort_arg = Post.post_date if (len(request.form.getlist('sort')) == 0 or str(request.form.getlist('sort')[0]) == "Date") else Post.views

        if not topics_selected: #check database against all topics
            for row in Post.select():
                row.tags = ast.literal_eval("[" + str(row.tags) + "]") #convert string representation in database to a list
                for tag_list in row.tags:
                    for tag in tag_list:
                        topics.add(tag)
                        
        if not authors_selected: #check database against all authors
            for row in Post.select():
                authors.add(row.author)
                       
        if not start_date_selected:
            start_date = "xx0000-00-00x" #must account for unicode, see below [2:-1]
            
        if not end_date_selected:
            end_date = "xx9999-99-99x"  
                                 
        results = 0
        for row in Post.select().order_by(-sort_arg):
            #for all matching authors, create a list of all written topics
            if row.author in authors: #this will filter out a lot of unnecessary processing when user selects an author
                matching_topics = get_matching_topics(row, topics)
                if ((((len(matching_topics) > 0) or ((len(matching_topics) == 0) and (row.tags == "") and not topics_selected)) \
                    and start_date[2:-1] <= row.post_date.decode('unicode_escape').encode('ascii', 'ignore').strip() <= end_date[2:-1]) \
                    and (not blogs_selected) or (blogs_selected and blog_in_filter(row, blogs))): #verify current row meets all filter requirements
                    host = blog_in_filter(row, wp_blogs + non_wp_blogs, False)
                    results += 1
                    answer.append({'author': row.author, 'title': row.title, 'post_date': row.post_date, 'views': str(row.views), \
                                   'topic_matches': str(matching_topics)[5:-2], 'url': str(row.url), 'host': host})     
        return auth_top_time_query_options(answer, results)
    return ""

def get_matching_topics(row, topics):
    """Utility function for auth_top_time_query. Retrieves the set of tags for the current post"""
    matching_topics = set()
    if len(row.tags) > 0: #w/o this check, ast.literal_eval will error out on any rows with no tags
        curr_row = ast.literal_eval(row.tags)
        for topic in topics:
            if (topic in curr_row): 
                matching_topics.add(topic.decode('unicode_escape').encode('ascii', 'ignore').strip())
    return matching_topics
                
def blog_in_filter(row, blogs = wp_blogs + non_wp_blogs, filter = True):
    """Accepts or rejects the current database record based on the user's blog filter setting."""
    for blog in blogs:
        if blog in row.url and blog != "redhat.com": #this will get all WordPress blogs
            return True if filter else blog
        elif find_between(blog, "https://", "/feed") in row.url and find_between(blog, "https://", "/feed") != "": #opensource.com, blog.openshift.com
            return True if filter else find_between(blog, "https://", "/feed")
        elif find_between(blog, "http://", "/feed") in row.url and find_between(blog, "http://", "/feed") != "": #crunchtools, stef.thewalter.net
            return True if filter else find_between(blog, "http://", "/feed")
        elif find_between(blog, "http://www.", "/blog/feed.xml") in row.url and find_between(blog, "http://www.", "/blog/feed.xml") != "": #project atomic
            return True if filter else find_between(blog, "http://www.", "/blog/feed.xml")
        elif find_between(blog, "http://", "/blog/feed.xml") in row.url and find_between(blog, "http://", "/blog/feed.xml") != "": #community.redhat.com
            return True if filter else find_between(blog, "http://", "/blog/feed.xml")
        elif (find_between(blog, "https://www.", "/rss/blog") in row.url) and "redhat.com/en" in row.url and ((blog == "redhat.com") or \
                                                                (blog == "https://www.redhat.com/en/rss/blog")): #handles redhat.com blogs
            return True if filter else "redhat.com"#find_between(blog, "https://www.", "/en/rss/blog")
        else: #redirect WordPress blogs
            for redirect_url in redirected_urls.keys():
                if redirected_urls[redirect_url] == blog and redirect_url in row.url:
                    return True if filter else redirected_urls[redirect_url]
    return False if filter else "N/A" 

@application.route("/")
def show_metrics():    
    #token = OAuthInfo.select(OAuthInfo.access_token)

    return auth_top_time_query_options()
    #auth = WordPressAuth()
    #return auth.prompt_authentication()    

def wipe_db():
    print("wipe db")
    metric_database.connect()
    metric_database.drop_tables([Post], True)
    metric_database.create_tables([Post], True)

#prevents OS database issue
@application.before_request
def before_request():
    g.db = metric_database
    g.db.connect()

@application.after_request
def after_request(response):
    g.db.close()
    return response

#Ensures that not every gunicorn worker runs an apscheduler job
try:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 47200))
except socket.error:
    pass
else:
    start_scheduled_jobs()
    
if __name__ == "__main__":
    application.run()