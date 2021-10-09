import os
from os import path
from enum import Enum
from py_dotenv import read_dotenv


class Config:
    def __init__(self):
        dotenv_path = path.join(path.dirname(__file__), '.env')
        read_dotenv(dotenv_path)

        self.discord_token = os.getenv("DISCORD_TOKEN")
        self.reddit_client_id = os.getenv("REDDIT_CLIENT_ID")
        self.reddit_secret = os.getenv("REDDIT_SECRET")
        self.reddit_user_agent = os.getenv("REDDIT_USER_AGENT")
        self.reddit_subreddit = os.getenv("REDDIT_SUBREDDIT")
        self.reddit_username = os.getenv("REDDIT_USERNAME")
        self.reddit_password = os.getenv("REDDIT_PASSWORD")
        self.update_rate = os.getenv("UPDATE_RATE")
        self.min_post_age = os.getenv("MIN_POST_AGE")
        self.max_post_age = os.getenv("MAX_POST_AGE")
        self.channel_id = int(os.getenv("CHANNEL_ID"))


class SubmissionState(Enum):
    MANUAL_REVIEW = 0
    GRANTED = 1
    DENIED = 2
    FOLLOWUP = 3
    NOT_ASSESSED = 4


class SubredditState(Enum):
    PUBLIC = 0
    RESTRICTED = 1
    PRIVATE = 2
    BANNED = 3
    BAD_URL = 4
    NOT_REACHABLE = 5