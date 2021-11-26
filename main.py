import os

from colorama import init, Fore, Back, Style
from discord_components import DiscordComponents, ComponentsBot
from asyncpraw import Reddit

from database import Database
from models import Config
from my_cogs import RedditCog

# global constants
DB_NAME = "redditrequest.sqlite"

# global variables
config: Config
reddit: Reddit
components_bot: ComponentsBot
database: Database


def main():
    startup()
    global reddit, components_bot, config

    # Create bot instance
    components_bot = ComponentsBot(command_prefix='/')
    components_bot.add_cog(RedditCog(components_bot, reddit, database, config))
    components_bot.run(os.getenv('DISCORD_TOKEN'))


def startup():
    # init colorful console output
    init()

    # Get global's
    global reddit, database, config
    config = Config()

    # setup reddit
    print(f'{Fore.WHITE}{Back.BLACK}> Initializing Reddit API access  {Style.RESET_ALL}')
    reddit = Reddit(client_id=config.reddit_client_id,
                    client_secret=config.reddit_secret,
                    user_agent=config.reddit_user_agent,
                    username=config.reddit_username,
                    password=config.reddit_password)

    print(f'{Fore.WHITE}{Back.BLACK}> Accessing reddit as: {"read-only" if reddit.read_only else "read-write"}  {Style.RESET_ALL}')

    # setup sqlite3
    print(f'{Fore.WHITE}{Back.BLACK}> Initializing local database  {Style.RESET_ALL}')
    database = Database(config.sqlite_path)
    print(f'{Fore.WHITE}{Back.BLACK}> Setting up completed - Starting bot  {Style.RESET_ALL}')


if __name__ == '__main__':
    main()
