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

lock = threading.Lock()

parallel_tags = []

def populate():
    with lock:
        populate_db()
        populate_spreadsheet()
        
def populate_db():
    #OAuthInfo.create(access_token = "TEST")
    from wsgi import strip_tags, all_blogs
    print("populating database...")
    metric_database.connect()
    token = OAuthInfo.select(OAuthInfo.access_token).where(OAuthInfo.local == False)
    for blog in all_blogs:
        post = requests.get('https://public-api.wordpress.com/rest/v1.1/sites/' + blog + '/posts/?number=1')
        num_posts = post.json()['found']
        post_table = []
        print(str(num_posts) + " posts on " + blog)
        while len(post_table) < num_posts: 
            post = requests.get('https://public-api.wordpress.com/rest/v1.1/sites/' + blog + '/posts/?number=100&offset=' + str(len(post_table)))
            for index in range(num_posts): 
                if index == len(post.json()['posts']): #prevent an IndexError
                    break
                
                curr_title = strip_tags(json.dumps(post.json()['posts'][index]['title']).decode('unicode_escape').encode('ascii', 'ignore').strip())[1:-1]
                curr_author= json.dumps(post.json()['posts'][index]['author']['name']).decode('unicode_escape').encode('ascii', 'ignore').strip()[1:-1]
                curr_post_date = json.dumps(post.json()['posts'][index]['date']).decode('unicode_escape').encode('ascii', 'ignore').strip()[1:11]
                unformatted_tags = post.json()['posts'][index]['tags'].keys()
                curr_tags = []
                curr_url = json.dumps(post.json()['posts'][index]['URL']).decode('unicode_escape').encode('ascii', 'ignore').strip()
                for tag in unformatted_tags:
                    curr_tags.append(tag.decode('unicode_escape').encode('ascii', 'ignore').strip())
                curr_wp_id = json.dumps(post.json()['posts'][index]['ID'])
                views_response = requests.get('http://public-api.wordpress.com/rest/v1.1/sites/' + blog + '/stats/post/' + str(curr_wp_id), headers={'Authorization':'Bearer ' + token.scalar()})
                try:
                    curr_views = int(json.dumps(views_response.json()['views']))
                except:
                    curr_views = 0
                post_table.append({'title': curr_title, 'author': curr_author, 'post_date': curr_post_date, 'tags': curr_tags, 'url': curr_url, 'views': curr_views})
            print(len(post_table))
        for post_index in range(len(post_table)):
            query = Post.select().where(Post.url == post_table[post_index]['url'])
            if not query.exists():
                with metric_database.atomic(): #speeds up bulk inserts - see peewee docs
                    Post.create(title=post_table[post_index]['title'], author=post_table[post_index]['author'], post_date=post_table[post_index]['post_date'], tags=post_table[post_index]['tags'], views=post_table[post_index]['views'], url=post_table[post_index]['url'])
    metric_database.close()

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
    sched.add_job(populate, 'interval', seconds=5)