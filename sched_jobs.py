from apscheduler.schedulers.background import BackgroundScheduler
import logging
from peewee import *
from db_tables import *
import requests
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import threading
import ast
from bs4 import BeautifulSoup
import feedparser
from DateTime import DateTime

lock = threading.Lock()

tag_source_html = {"http://stef.thewalter.net/" : "http://stef.thewalter.net/tag/", "community.redhat.com/blog" : "/blog/tag", "blog.openshift.com" : "https://blog.openshift.com/tag", "http://crunchtools.com/" : "http://crunchtools.com/tag/"} 

def populate():
    with lock:
        populate_db()
        populate_spreadsheet()
        
def populate_db():
    print("populating database...")
    from wsgi import wp_blogs, non_wp_blogs
    metric_database.connect()
    for blog in non_wp_blogs:
        curr_blogs_posts = parse_non_wp_blogs(blog)
        insert_row(curr_blogs_posts)
    for blog in wp_blogs:
        curr_blogs_posts = parse_wp_blogs(blog)
        insert_row(curr_blogs_posts)
    metric_database.close()

def parse_wp_blogs(blog):
    from wsgi import strip_tags, wp_blogs
    token = OAuthInfo.select(OAuthInfo.access_token).where(OAuthInfo.local == False)
    post = requests.get('https://public-api.wordpress.com/rest/v1.1/sites/' + blog + '/posts/?number=1')
    num_posts = post.json()['found']
    post_table = []
    print(str(num_posts) + " posts on " + blog)
    while len(post_table) < num_posts: 
        post = requests.get('https://public-api.wordpress.com/rest/v1.1/sites/' + blog + '/posts/?number=100&offset=' + str(len(post_table)))
        for index in range(num_posts): 
            try:
                if index == len(post.json()['posts']): #prevent an IndexError
                    break
            except:
                print(post)
                print(blog)
            
            curr_title = strip_tags(json.dumps(post.json()['posts'][index]['title']).decode('unicode_escape').encode('ascii', 'ignore').strip())[1:-1]
            curr_author= json.dumps(post.json()['posts'][index]['author']['name']).decode('unicode_escape').encode('ascii', 'ignore').strip()[1:-1]
            curr_post_date = json.dumps(post.json()['posts'][index]['date']).decode('unicode_escape').encode('ascii', 'ignore').strip()[1:11]
            unformatted_tags = post.json()['posts'][index]['tags'].keys()
            curr_tags = []
            curr_url = json.dumps(post.json()['posts'][index]['URL']).decode('unicode_escape').encode('ascii', 'ignore').strip()
            for tag in unformatted_tags:
                curr_tags.append(tag.decode('unicode_escape').encode('ascii', 'ignore').strip())
            curr_wp_id = json.dumps(post.json()['posts'][index]['ID'])
            views_response = requests.get('http://public-api.wordpress.com/rest/v1.1/sites/' + blog + '/stats/post/' + str(curr_wp_id), headers={'Authorization':'Bearer ' \
                                                                                                                                                 + token.scalar()})
            curr_content = get_content(blog = blog, wp_blog_id = curr_wp_id)
            try:
                curr_views = int(json.dumps(views_response.json()['views']))
            except:
                curr_views = 0
            post_table.append({'title': curr_title, 'author': curr_author, 'post_date': curr_post_date, 'tags': curr_tags, 'url': curr_url, \
                               'views': curr_views, 'content': curr_content})
        print(len(post_table))
    return post_table
        
def parse_non_wp_blogs(blog):
    from wsgi import non_wp_blogs
    feed = feedparser.parse(blog)
    post_table = []
    
    for item in feed.entries:
        title = item.title
        url = item.link
        post_date = DateTime(item.published).ISO()[:-9]
        try:
            author = item.author
        except:
            author = "N/A"
        tags = get_tags(url)
        curr_content = ""#get_content(non_wp_url = url)
        post_table.append({'title': title, 'author': author, 'post_date': post_date, 'tags': tags, 'url': url, 'views': 0, 'content': curr_content})     
    return post_table

def get_content(blog = None, wp_blog_id = None, non_wp_url = None):
    """Return all text from a blog post's content. If wp_blog_id == None, it's a non-wp blog."""
    if wp_blog_id:
        content_response = requests.get('http://public-api.wordpress.com/rest/v1.1/sites/' + blog + '/posts/' + wp_blog_id)
        return BeautifulSoup(json.dumps(content_response.json()['content']).decode('unicode_escape').encode('ascii', 'ignore').strip(), "html.parser").text[1:-1]
    
    """elif non_wp_url:
        from wsgi import non_wp_selectors
        
        for blog in non_wp_selectors:
            content = ""
            if blog in non_wp_url:
                soup = BeautifulSoup(requests.get(non_wp_url).content, "html.parser")
                parent_struct = non_wp_selectors[blog].keys()[0]
                parent_attr = non_wp_selectors[blog][parent_struct].keys()[0]
                parent_attr_val = non_wp_selectors[blog][parent_struct][parent_attr]
                parent = soup.find(parent_struct, {parent_attr : parent_attr_val})
                for tag in parent.children:
                    try:
                        if tag.name == 'p' or tag.name == 'ul' or tag.name == "ol":
                            content += tag.text.decode('unicode_escape').encode('ascii', 'ignore').strip()
                        elif tag.name == 'iframe':
                            pass
                        else:
                            content += tag.string.decode('unicode_escape').encode('ascii', 'ignore').strip()
                    except:
                        pass
        print(non_wp_url)
        return content"""            

def get_tags(url):
    """Tags are pulled from source HTML, which varies per blog. Hence the conditional situation."""
    tags = []
    src=requests.get(url)
    soup=BeautifulSoup(src.content, "html.parser")
    for blog in tag_source_html.keys():
        if blog in url:
            for a in soup.find_all('a'):
                try:
                    if tag_source_html[blog] in a['href']:
                        tags.append(a.contents[0].decode('unicode_escape').encode('ascii', 'ignore').strip())
                except:
                    pass
    if "redhat.com" in url: #find an alternative -- all tags get returned at once, makes the dropdown no bueno
        for meta in soup.find_all('meta'):
            if meta.get("name") == "taxonomy-blog_post_category":
                tags.append(meta.get("content"))
    elif "opensource.com" in url:
        for a in soup.find_all('a'):
            try:
                if "/tags/" in a['href'] and not a['href'].startswith("https://opensource.com/tags/") and not "cid=" in a['href']: #avoid non-tag info in source href
                    tags.append(a.contents[0].decode('unicode_escape').encode('ascii', 'ignore').strip())
            except:
                continue
    return tags
    
def insert_row(post_table):
    """Updates the database with the new post. If the post already exists, update it's view count."""
    for post_index in range(len(post_table)):
        query = Post.select().where(Post.url == post_table[post_index]['url'])
        if not query.exists():
            with metric_database.atomic(): #speeds up bulk inserts - see peewee docs
                Post.create(title=post_table[post_index]['title'], author=post_table[post_index]['author'], post_date=post_table[post_index]['post_date'],\
                             tags=post_table[post_index]['tags'], views=post_table[post_index]['views'], url=post_table[post_index]['url'])
        else:
            with metric_database.atomic():
                query = Post.update(views = post_table[post_index]['views']).where(Post.url == post_table[post_index]['url'])
                query.execute()
                
                query = Post.update(content = post_table[post_index]['content']).where(Post.content != None and Post.url == post_table[post_index]['url'])
                query.execute()
                
def populate_spreadsheet():
    """Prerequisite: database is filled"""
    scope = ['https://spreadsheets.google.com/feeds']
    credentials = ServiceAccountCredentials.from_json_keyfile_name('metrictool-f16ab8f08d89.json', scope)
    conn = gspread.authorize(credentials)
    worksheet = conn.open("Metrics").sheet1
    
    worksheet.update_acell('A1', 'AUTHORS')
    worksheet.update_acell('B1', 'TITLES')
    worksheet.update_acell('C1', 'POST DATES')
    worksheet.update_acell('D1', 'VIEWS')
    worksheet.update_acell('E1', 'TAGS')
    worksheet.update_acell('F1', 'URL')
    
    row_index = 3 #1: header, 2: white space 
    for row in Post.select().order_by(-Post.post_date):
        cell_list = worksheet.range('A%s:F%s' % (row_index, row_index)) 
        cell_values = [row.author, row.title, row.post_date, row.views, row.tags, row.url]
        for i in range(len(cell_values)):
            cell_list[i].value = cell_values[i]
        row_index += 1
        worksheet.update_cells(cell_list)
    
def start_scheduled_jobs():
    logging.basicConfig()
    sched = BackgroundScheduler()
    sched.start()
    sched.add_job(populate, 'interval', seconds=300)