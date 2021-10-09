import os, sqlite3
from typing import List
from praw import Reddit, models
from discord.ext import commands, tasks
from threading import Timer
from py_dotenv import read_dotenv
from colorama import init, Fore, Back, Style
from my_cogs import RedditCog

# global constants
DB_NAME = "posts.sqlite"

# global variables
reddit: Reddit
subreddit: models.Subreddit
bot: commands.Bot
database: sqlite3.Connection
timer: Timer


def main():
    startup()
    global reddit, subreddit, bot, timer

    # Create bot instance
    bot = commands.Bot(command_prefix='/')
    bot.add_cog(RedditCog(bot, reddit, subreddit, database))
    bot.run(os.getenv('DISCORD_TOKEN'))


def startup():
    # init colorful console output
    init()

    # Get global's
    global reddit, subreddit, database, timer

    # Load environment file
    print(f'{Fore.BLACK}{Back.GREEN}> Reading environment file {Style.RESET_ALL}')
    dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
    read_dotenv(dotenv_path)

    # setup reddit
    print(f'{Fore.BLACK}{Back.GREEN}> Initializing Reddit API access {Style.RESET_ALL}')
    reddit = Reddit(client_id=os.getenv('REDDIT_CLIENT_ID'),
                    client_secret=os.getenv('REDDIT_SECRET'),
                    user_agent=os.getenv('REDDIT_USER_AGENT'),
                    username=os.getenv('REDDIT_USERNAME'),
                    password=os.getenv('REDDIT_PASSWORD'))

    print(f'{Fore.BLACK}{Back.GREEN}> Fetching target subreddit {Style.RESET_ALL}')
    subreddit = reddit.subreddit("redditrequest")

    # setup sqlite3
    print(f'{Fore.BLACK}{Back.GREEN}> Initializing local database {Style.RESET_ALL}')

    database = sqlite3.connect(DB_NAME)
    cursor = database.cursor()
    create_table_posts = "CREATE TABLE IF NOT EXISTS posts(" \
                         "id INTEGER PRIMARY KEY AUTOINCREMENT," \
                         "post_id TEXT UNIQUE," \
                         "subreddit TEXT," \
                         "last_checked INTEGER, " \
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

    print(f'{Fore.BLACK}{Back.GREEN}> Setting up scraping timer {Style.RESET_ALL}')


if __name__ == '__main__':
    main()
