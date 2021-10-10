import os
import sqlite3
from threading import Timer

from colorama import init, Fore, Back, Style
from discord.ext import commands
from praw import Reddit, models
from py_dotenv import read_dotenv

from models import Config
from my_cogs import RedditCog

# global constants
DB_NAME = "redditrequest.sqlite"

# global variables
config: Config
reddit: Reddit
bot: commands.Bot
database: sqlite3.Connection


def main():
    startup()
    global reddit, bot, config

    # Create bot instance
    bot = commands.Bot(command_prefix='/')
    bot.add_cog(RedditCog(bot, reddit, database, config))
    bot.run(os.getenv('DISCORD_TOKEN'))


def startup():
    # init colorful console output
    init()

    # Get global's
    global reddit, database, config
    config = Config()

    # setup reddit
    print(f'{Fore.BLACK}{Back.GREEN}> Initializing Reddit API access {Style.RESET_ALL}')
    reddit = Reddit(client_id=config.reddit_client_id,
                    client_secret=config.reddit_secret,
                    user_agent=config.reddit_user_agent,
                    username=config.reddit_username,
                    password=config.reddit_password,
                    check_for_async=False)

    # setup sqlite3
    print(f'{Fore.BLACK}{Back.GREEN}> Initializing local database {Style.RESET_ALL}')

    database = sqlite3.connect(DB_NAME)
    cursor = database.cursor()
    create_table_posts = "CREATE TABLE IF NOT EXISTS posts(" \
                         "id INTEGER PRIMARY KEY AUTOINCREMENT," \
                         "post_id TEXT UNIQUE," \
                         "subreddit TEXT," \
                         "created_at INTEGER, " \
                         "updated_at INTEGER, " \
                         "status INTEGER DEFAULT 0" \
                         ")"
    cursor.execute(create_table_posts)
    create_table_users = "CREATE TABLE IF NOT EXISTS users(" \
                         "id INTEGER PRIMARY KEY AUTOINCREMENT," \
                         "user_name TEXT UNIQUE," \
                         "request_count INTEGER DEFAULT  1" \
                         ")"
    cursor.execute(create_table_users)
    create_table_messages = "CREATE TABLE IF NOT EXISTS messages(" \
                            "id INTEGER PRIMARY KEY AUTOINCREMENT," \
                            "message_id INTEGER UNIQUE," \
                            "submission TEXT UNIQUE, " \
                            "created_at INTEGER, " \
                            "updated_at INTEGER" \
                            ")"
    cursor.execute(create_table_messages)
    database.commit()

    print(f'{Fore.BLACK}{Back.GREEN}> Setting up completed - Starting bot {Style.RESET_ALL}')


if __name__ == '__main__':
    main()
