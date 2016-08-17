from peewee import *
import os
import peewee
import pymysql
from pymysql.constants.FIELD_TYPE import CHAR

#OpenShift connection parameters
metric_database = MySQLDatabase(os.getenv('MYSQL_DATABASE'), host = os.getenv('MYSQL_SERVICE_HOST'),  \
                                user = os.getenv('MYSQL_USER'), password = os.getenv('MYSQL_PASSWORD'))

class BaseModel(peewee.Model):
    class Meta:
        database = metric_database
    
class Post(BaseModel):
    title = CharField()
    author = CharField()
    post_date = CharField()
    tags = CharField(max_length=5000) #this represents the topic
    views = IntegerField(null=True) #null for blogs w/o admin rights
    url = CharField(primary_key = True) 
    content = TextField(null=True) 

class OAuthInfo(BaseModel):
    access_token = CharField(null=True)
    client_secret = CharField(null=True)
    client_id = CharField(null=True)
    redirect_uri = CharField(null=True)
    local = BooleanField(null=True)
    auth_file = BlobField(null=True)
    api = CharField()