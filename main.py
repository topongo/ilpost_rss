import html
import json

from pymongo import MongoClient
from pymongo.synchronous.database import Database
from requests import get, post
from os import getenv
from dotenv import load_dotenv
from datetime import datetime, timedelta
from flask import Flask, request
from feedgen.feed import FeedGenerator 
from flask import make_response

class Episode:
    def __init__(self, data, podcast):
        self.id : int = data["id"]
        self.podcast : str = podcast
        self.author : str = unescape(data["author"])
        self.title : str = unescape(data["title"])
        # self.click : str = data["_click"]
        self.summary : str = unescape(data["summary"])
        self.content_html : str = unescape(data["content_html"])
        self.image : str = data["image"]
        self.image_web : str = data["image_web"]
        self.milliseconds : int = data["milliseconds"]
        self.minutes : int = data["minutes"]
        self.special : int = data["special"]
        self.share_url : str = data["share_url"]
        self.slug : str = data["slug"]
        self.full_slug : str = data["full_slug"]
        self.url : str = data["url"]
        self.episode_raw_url : str = data["episode_raw_url"]
        self.date : datetime = datetime.strptime(data["date"], "%Y-%m-%dT%H:%M:%S%z")
        # self.timestamp : int = data["timestamp"]
        self.access_level : str = data["access_level"]

    def serialize(self):
        return {
            "id": self.id,
            "podcast": self.podcast,
            "author": self.author,
            "title": self.title,
            "summary": self.summary,
            "content_html": self.content_html,
            "image": self.image,
            "image_web": self.image_web,
            "milliseconds": self.milliseconds,
            "minutes": self.minutes,
            "special": self.special,
            "share_url": self.share_url,
            "slug": self.slug,
            "full_slug": self.full_slug,
            "url": self.url,
            "episode_raw_url": self.episode_raw_url,
            "date": self.date.isoformat(),
            "access_level": self.access_level,
        }

    @staticmethod
    def deserialize(data):
        return Episode(data, data["podcast"])

    def __str__(self):
        return f"Episode(id={self.id}, title={self.title})"

    def populate_entry(self, fe):
        fe.title(self.title)
        fe.link(href=self.url)
        fe.description(self.content_html)
        fe.guid(self.url, permalink=True)
        fe.pubDate(self.date)
        fe.enclosure(self.episode_raw_url, 0, "audio/mpeg")
        fe.podcast.itunes_author(self.author)
        # missing field in input data
        # fe.podcast.itunes_subtitle(self.summary)
        fe.podcast.itunes_summary(self.content_html)
        fe.podcast.itunes_duration(int(self.milliseconds / 1000))
        # missing field in input data
        # fe.podcast.itunes_keywords
        fe.podcast.itunes_explicit("clean")
        fe.podcast.itunes_image(self.image)
        fe.podcast.itunes_episode_type("full")



class IlPostApi:
    BASE_URL: str = "https://api-prod.ilpost.it/"
    ROUTE_PODCAST: str = "podcast/v1/podcast/{id}"
    ROUTE_USERS: str = "user/v2"
    ROUTE_PAYMENT: str = "payment/v1"

    def __init__(self, token, subscribed):
        self.token: str = token
        self.subscribed: bool = subscribed

    def __str__(self):
        return f"IlPostApi(token=****, refresh_token=****, subscribed={self.subscribed})"

    @staticmethod
    def login(username, password):
        res = post(
            f"{IlPostApi.BASE_URL}{IlPostApi.ROUTE_USERS}/auth/login",
            json={"username": username, "password": password}
        )

        if res.status_code == 200:
            data = res.json()
            cookies = res.cookies
            subscribed: bool = data["subscription"]
            token: str = data["token"]
            api = IlPostApi(token, subscribed)
            api.update_subscription()
            return api
        else:
            print("error logging in: ", res.status_code)
            print("error logging in: ", res.text)

    def auth_headers(self):
        return {"token": self.token, "apikey": "testapikey"}

    def update_subscription(self):
        res = get(
            f"{IlPostApi.BASE_URL}{IlPostApi.ROUTE_PAYMENT}/subscription",
            headers=self.auth_headers()
        )
        if res.status_code == 200:
            data = res.json()[0]
            start = datetime.strptime(data["data"]["current_period_start"], "%Y-%m-%d")
            end = datetime.strptime(data["data"]["current_period_end"], "%Y-%m-%d")
            self.subscribed = start <= datetime.now() <= end
        else:
            print("error updating subscription: ", res.status_code)
            print("error updating subscription: ", res.text)
            raise
        return self.subscribed

    def recursive_podcast_get(self, podcast, page=1, counter=0, hits=None):
        params = {"hits": hits or 200, "pg": page}
        url = f"{IlPostApi.BASE_URL}{IlPostApi.ROUTE_PODCAST.format(id=podcast)}"
        resp = get(
            url,
            params=params,
            headers=self.auth_headers()
        ) 
        if resp.status_code != 200:
            raise Exception(f"error while requesting podcast: {resp.status_code}: {resp.text}")
        resp = resp.json()
        head = resp["head"]["data"]
        data = resp["data"]
        for i in data:
            yield Episode(i, podcast)
            counter += 1
        if head["total"] > counter:
            for i in self.recursive_podcast_get(podcast, page=page+1, counter=counter):
                yield i

    def get_meta(self, podcast):
        params = {"hits": 1, "pg": 1}
        url = f"{IlPostApi.BASE_URL}{IlPostApi.ROUTE_PODCAST.format(id=podcast)}"
        resp = get(
            url,
            params=params,
            headers=self.auth_headers()
        )
        if resp.status_code != 200:
            raise Exception(f"error while requesting podcast: {resp.status_code}: {resp.text}")

        j = resp.json()

        return j["head"]["data"]["total"], j["data"][0]["parent"]


def api_db_cache_mix(api, db, podcast, modified_since=None):
    start = datetime.now()
    tot_db = db[podcast].count_documents({})
    print(f"+{datetime.now() - start} to count episodes in db")
    parent = db["podcasts"].find_one({"_slug": podcast})
    print(f"+{datetime.now() - start} to find podcast in db")
    if parent is None:
        # this ensures that if the podcast was never fetched, we fetch it (because tot > tot_db)
        tot, parent = api.get_meta(podcast)
        assert tot_db == 0
        parent["_slug"] = podcast
        updated = datetime.fromtimestamp(0)
        parent["_updated"] = updated.isoformat()
        modified = datetime.now()
        parent["_modified"] = modified.isoformat()
        db["podcasts"].insert_one(parent)
    else:
        updated = datetime.fromisoformat(parent["_updated"])
        modified = datetime.fromisoformat(parent["_modified"])
        tot = None

    if updated + timedelta(minutes=10) < datetime.now():
        print("updating podcast meta")
        if tot is None:
            tot, _ = api.get_meta(podcast)
        if tot > tot_db:
            print("getting already fetched episode ids")
            episodes = {e["id"] for e in db[podcast].find({}, {"id": 1})}
            print("fetching missing episodes from api")
            to_insert = []
            for i in api.recursive_podcast_get(podcast, hits=tot - tot_db):
                if i.id not in episodes:
                    to_insert.append(i)
                    print("adding episode", i)
            assert len(to_insert) + tot_db == tot
            if len(to_insert) > 0:
                db[podcast].insert_many((i.serialize() for i in to_insert))
                print(f"inserted {len(to_insert)} episodes in db")
                modified = datetime.now()
                db["podcasts"].update_one({"_slug": podcast}, {"$set": {"_modified": modified.isoformat()}})

        updated = datetime.now()
        db["podcasts"].update_one({"_slug": podcast}, {"$set": {"_updated": updated.isoformat()}})

    if modified_since is not None and modified <= modified_since:
        print("podcast not updated since last request")
        return None, None, modified
        
    sorted = [Episode.deserialize(e) for e in db[podcast].aggregate([{"$sort": {"date": -1}}])]
    return parent, sorted, modified


def unescape(text):
    if text is None:
        return None
    return html.unescape(text)

def feed_gen(api, db, podcast, modified_since=None):
    parent, episodes, modified = api_db_cache_mix(api, db, podcast, modified_since)
    if parent is None and episodes is None:
        # contend didn't change since last request
        return None, modified

    fg = FeedGenerator()
    fg.load_extension('podcast')
    fg.title(parent["title"])
    fg.link({"href": f"https://ilpost.it/podcasts/{podcast}"})
    fg.description(parent["description"])
    fg.category({"term": "News & Politics"})
    fg.image(parent["image"])
    fg.author({'name': parent["author"]})
    fg.copyright(parent["author"])
    fg.podcast.itunes_author(itunes_author=parent["author"])
    # missing email from input data
    # fg.podcast.itunes_owner(parent["author"])
    fg.podcast.itunes_image(parent["image"])
    fg.podcast.itunes_summary(parent["description"])
    fg.podcast.itunes_explicit("clean")
    fg.podcast.itunes_category("News & Politics")
    fg.podcast.itunes_type("episodic")
    for e in episodes:
        fe = fg.add_entry()
        e.populate_entry(fe)

    return fg.rss_str(), modified

ILPOST_USERNAME = getenv("ILPOST_USERNAME")
ILPOST_PASSWORD = getenv("ILPOST_PASSWORD", "")
MONGO_HOST = getenv("MONGO_HOST", "")
MONGO_PORT = getenv("MONGO_PORT", 27017)
MONGO_USERNAME = getenv("MONGO_USERNAME", "")
MONGO_PASSWORD = getenv("MONGO_PASSWORD", "")

MONGO_URI = f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}"

if __name__ == "main":
    client = MongoClient(MONGO_URI)
    print(f"connecting to db (mongodb://{MONGO_USERNAME}:****@{MONGO_HOST}:{MONGO_PORT})")
    db = client["ilpost"]
    auth = db["auth"]
    users = list(auth.find())
    print("connected to db!")
    assert len(users) <= 1
    if len(users) == 0:
        print("no uses in db, logging in for the first time...")
        api = IlPostApi.login(ILPOST_USERNAME, ILPOST_PASSWORD)
        if api is not None:
            print("login successful")
            auth.insert_one({"token": api.token, "subscribed": api.subscribed})
        else:
            print("error logging in")
            exit(1)
    else:
        api = IlPostApi(users[0]["token"], users[0]["subscribed"])

    if api.update_subscription():
        print("user is logged in and subscribed")
    else:
        print("user is logged in but not subscribed")
        exit(1)

    app = Flask(__name__)


@app.route("/<podcast>")
def rss(podcast):
    for c in podcast:
        if not c.isalnum() and c != "-":
            return "invalid podcast name", 404
    try:
        modified_since = datetime.fromisoformat(request.headers.get("if-modified-since"))
    except Exception as _:
        modified_since = None
    feed, modified = feed_gen(api, db, podcast, modified_since)
    if feed is None:
        return "", 304
    response = make_response(feed)
    response.headers.set('Content-Type', 'text/xml')
    response.headers.set('Last-Modified', modified.isoformat())
    return response


