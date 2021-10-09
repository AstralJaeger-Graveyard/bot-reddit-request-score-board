import sqlite3
from enum import Enum
from typing import List
from datetime import datetime, timedelta

import discord
from discord import Embed, Color, Message, TextChannel, Emoji
from discord.ext import tasks, commands
from discord.ext.commands import Bot

from praw import Reddit
from praw.models import Subreddit
from praw.reddit import Submission, Redditor
from prawcore import Forbidden, NotFound, BadRequest

from colorama import Fore, Back, Style


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


class RedditCog(commands.Cog, name='ScoreBoardCog'):
    def __init__(self, bot, reddit, subreddit, database):
        self.bot: Bot = bot
        self.reddit: Reddit = reddit
        self.subreddit: Subreddit = subreddit
        self.database: sqlite3.Connection = database
        self.revisits: List[str] = []
        self.channel_id:int = 896344246330748948
        self.scrape_scoreboard.start()
        self.checkup_scoreboard.start()

    def cog_unload(self):
        self.scrape_scoreboard.cancel()
        self.checkup_scoreboard.cancel()

    @tasks.loop(minutes=5)
    async def scrape_scoreboard(self):
        channel = self.bot.get_channel(self.channel_id)
        i: int
        submission: Submission
        skipped: int = 0

        for i, submission in enumerate(self.subreddit.new(limit=50)):

            # Check if post is already in database
            if self.is_already_posted(submission.id):
                print(f'Submission already posted, skipping | Skipped: {skipped}')
                skipped += 1
                if skipped >= 10:
                    break
                continue

            skipped = 0

            # Parse the subreddit name from url provided in post, get the submission author and the subreddit object
            subreddit_name: str = self.get_subreddit_name_from_url(submission.url)
            author: Redditor = submission.author
            subreddit: Subreddit = self.reddit.subreddit(subreddit_name)

            print(f'{Fore.BLUE}{Back.BLACK}  {i}: r/{subreddit_name} - '
                  f'u/{"[deleted]" if author is None else author.name} '
                  f'{Style.RESET_ALL}')

            # Build embed, send message, store in database
            embed = self.build_embed(submission, author, subreddit, subreddit_name)
            message = await channel.send(embed=embed)
            self.put_message_into_database(submission, message)
            self.put_post_into_database(submission, subreddit_name, self.get_submission_state(submission))

    @scrape_scoreboard.before_loop
    async def before_scrape_scoreboard(self) -> None:
        print(f'{Fore.BLUE}{Back.BLACK}Preparing to scrape new posts {Style.RESET_ALL}')
        await self.bot.wait_until_ready()

    @tasks.loop(hours=8)
    async def checkup_scoreboard(self):
        channel: TextChannel = self.bot.get_channel(self.channel_id)
        for post_id in self.revisits:
            # Get message id from database
            cursor = self.database.cursor()
            select_stmt = "SELECT * FROM messages WHERE submission == ?"
            cursor.execute(select_stmt, (post_id, ))

            message_id = 0
            for data in cursor:
                message_id = data[1]

            # get message and submission
            message: Message = await channel.fetch_message(message_id)
            submission: Submission = self.reddit.submission(id=post_id)
            subreddit_name = self.get_subreddit_name_from_url(submission.url)
            subreddit = self.reddit.subreddit(subreddit_name)

            print(f'{Fore.GREEN}{Back.BLACK}  {post_id}: {subreddit_name} {Style.RESET_ALL}')

            await message.add_reaction('🔄')
            embed = self.build_embed(submission, submission.author, subreddit, subreddit_name)
            await message.edit(embed=embed)
            await message.remove_reaction('🔄', self.bot.user)

            cursor = self.database.cursor()
            update_stmt = "UPDATE messages SET updated_at = datetime('%s', 'now') WHERE message_id == ?"
            cursor.execute(update_stmt, (message.id, ))

    @checkup_scoreboard.before_loop
    async def before_checkup_scoreboard(self) -> None:
        print(f'{Fore.GREEN}{Back.BLACK}  Getting ready to validate previous posts {Style.RESET_ALL}')

        # Clearing already existing data
        self.revisits = []

        # Get posts to check
        cursor = self.database.cursor()
        timestamp: int = int((datetime.now() - timedelta(hours=1)).timestamp())
        select_stmt = 'SELECT post_id, last_checked FROM posts WHERE status != ? AND last_checked <= ? ORDER BY id'
        cursor.execute(select_stmt, (SubmissionState.GRANTED.value, timestamp))

        for data in cursor:
            post_id: str = data[0]
            last_checked: datetime = datetime.utcfromtimestamp(data[1])
            self.revisits.append(post_id)

        print(f'{Fore.GREEN}{Back.BLACK}Revisiting: {Fore.RED}{len(self.revisits)}{Fore.GREEN} posts with this batch {Style.RESET_ALL}')
        await self.bot.wait_until_ready()

    def get_subreddit_name_from_url(self, url: str) -> str:
        url = url[[i for i, n in enumerate(url) if n == '/'][2] + 1:]
        if "?" in url:
            url = url[:[i for i, n in enumerate(url) if n == '?'][0]]
        if "/" == url[-1:]:
            url = url.rstrip(url[-1:])
        if url.count("/") > 2:
            url = url[:[i for i, n in enumerate(url) if n == '/'][1]]
        if "r/" in url:
            url = url.replace("r/", "")
        return url

    def is_already_posted(self, submission_id) -> bool:
        """"This method checks if the submission id is already in the database and thus already posted"""
        cursor = self.database.cursor()
        select_stmt = "SELECT (post_id) FROM posts WHERE post_id = ?"
        cursor.execute(select_stmt, (submission_id,))
        already_posted = False
        for entry in cursor:
            return True
        return False

    def put_post_into_database(self, submission: Submission, subreddit_name: str, submission_state: SubmissionState) \
            -> None:
        """This method puts a submission (and author) into the database"""
        cursor = self.database.cursor()
        insert_stmt = 'INSERT INTO posts(post_id, subreddit, last_checked, status) ' \
                      'VALUES (?, ?, strftime(\'%s\', \'now\'), ?)'
        cursor.execute(insert_stmt, (submission.id,
                                     subreddit_name,
                                     submission_state.value))

        author = submission.author
        if author is None:
            self.database.commit()
            return

        select_stmt = 'SELECT * FROM users WHERE user_name = ?'
        cursor.execute(select_stmt, (author.name,))

        row_id = -1
        request_count = 0
        for usr in cursor:
            row_id = usr[0]
            request_count = usr[2]

        if row_id == -1:
            insert_stmt = 'INSERT INTO users(user_name, request_count) VALUES (?, ?)'
            cursor.execute(insert_stmt, (author.name, 1))
        else:
            update_stmt = 'UPDATE users SET request_count = ? WHERE user_name = ?'
            cursor.execute(update_stmt, (request_count, row_id))

        self.database.commit()

    def put_message_into_database(self, submission: Submission, message: Message) -> None:
        cursor = self.database.cursor()
        insert_stmt = 'INSERT INTO messages(message_id, submission, created_at, updated_at) ' \
                      'VALUES (?, ?, strftime(\'%s\', \'now\'), strftime(\'%s\', \'now\'))'
        cursor.execute(insert_stmt, (message.id, submission.id))
        pass

    def get_subreddit_state(self, subreddit: Subreddit) -> SubredditState:
        try:
            if subreddit.subreddit_type == "public":
                return SubredditState.PUBLIC
            elif subreddit.subreddit_type == "restricted":
                return SubredditState.RESTRICTED
        except Forbidden:
            return SubredditState.PRIVATE
        except NotFound:
            return SubredditState.BANNED
        except BadRequest:
            return SubredditState.BAD_URL
        return SubredditState.NOT_REACHABLE

    def get_submission_state(self, submission: Submission) -> SubmissionState:
        for tlc in submission.comments:
            author = tlc.author
            if author.name == 'request_bot':
                tlc_body = tlc.body
                if "directly messaging the mod team" in tlc_body:
                    return SubmissionState.FOLLOWUP
                elif 'manual review' in tlc_body:
                    return SubmissionState.MANUAL_REVIEW
                elif "has been granted" in tlc_body or "Approved" in tlc_body:
                    return SubmissionState.GRANTED
                elif "cannot be transferred" in tlc_body:
                    return SubmissionState.DENIED

        return SubmissionState.NOT_ASSESSED

    def get_embed_color(self, submission_state: SubmissionState) -> Color:
        if submission_state is SubmissionState.DENIED:
            return Color.red()
        elif submission_state is SubmissionState.GRANTED:
            return Color.green()
        elif submission_state is SubmissionState.MANUAL_REVIEW:
            return Color.blue()
        elif submission_state is SubmissionState.FOLLOWUP:
            return Color.gold()
        elif submission_state is SubmissionState.NOT_ASSESSED:
            return Color.dark_gray()
        return Color.purple()

    def get_subreddit_moderators(self, subreddit: Subreddit) -> List[str]:
        moderators: List[str] = []
        for mod in subreddit.moderator():
            moderators.append(f'u/{mod.name}')
        return moderators

    def build_embed(self, submission: Submission, author: Redditor, subreddit: Subreddit, subreddit_name: str) -> Embed:
        state = self.get_subreddit_state(subreddit)
        submission_state = self.get_submission_state(submission)

        embed = Embed(title=f'r/{subreddit_name}', color=self.get_embed_color(submission_state))
        if author is None:
            embed.set_author(name='u/[deleted]',
                             url='https://www.reddit.com/user/[deleted]/',
                             icon_url='https://www.redditstatic.com/desktop2x/img/snoomoji/snoo_thoughtful.png')
        elif hasattr(author, 'is_suspended'):
            embed.set_author(name=f'u/{author.name}',
                             url=f'https://www.reddit.com/user/{author.name}/',
                             icon_url='https://www.redditstatic.com/desktop2x/img/snoomoji/snoo_thoughtful.png')
        else:
            embed.set_author(name=f'u/{author.name}',
                             url=f'https://www.reddit.com/user/{author.name}/',
                             icon_url=author.icon_img)

        # embed.url = submission.url
        embed.url = f'https://www.reddit.com{submission.permalink}'
        embed.timestamp = datetime.utcfromtimestamp(submission.created_utc)
        embed.description = submission.title
        embed.add_field(name='Subreddit state', value=state.name, inline=True)
        embed.add_field(name='Request state', value=submission_state.name, inline=True)

        if state == SubredditState.PUBLIC:
            embed.set_thumbnail(url=subreddit.community_icon)
            embed.add_field(name='NSFW', value=subreddit.over18, inline=True)
            embed.add_field(name='Members', value=subreddit.subscribers, inline=True)

            moderators = self.get_subreddit_moderators(subreddit)

            embed.add_field(name='Moderators', value=str(len(moderators)), inline=True)
            if not len(moderators) == 0:
                embed.add_field(name='Moderators', value=str(', '.join(moderators)), inline=False)
            embed.add_field(name='Subreddit created', value=str(datetime.utcfromtimestamp(subreddit.created_utc)),
                            inline=True)

            if author is not None:
                embed.add_field(name='Account created', value=f'{datetime.utcfromtimestamp(author.created_utc)}',
                                inline=True)
        return embed

