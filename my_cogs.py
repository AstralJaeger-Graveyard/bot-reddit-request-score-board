from typing import List
from datetime import datetime, timedelta
from sqlite3 import Connection

import aiostream.stream

from models import Config, SubredditState, SubmissionState
from time import time, gmtime, strftime

from discord import Embed, Color, Message, TextChannel
from discord.ext import tasks, commands
from discord.ext.commands import Bot

from asyncpraw import Reddit
from asyncpraw.models import Subreddit
from asyncpraw.reddit import Submission, Redditor
from asyncprawcore import Forbidden, NotFound, BadRequest

from colorama import Fore, Style


class RedditCog(commands.Cog, name='RedditCog'):
    def __init__(self, bot: Bot, reddit: Reddit, database: Connection, config: Config):
        self.bot: Bot = bot
        self.reddit: Reddit = reddit
        self.database: Connection = database
        self.config: Config = config
        self.find_posts.start()
        self.update_posts.start()
        self.first_run = True

    def cog_unload(self):
        self.find_posts.cancel()
        self.update_posts.cancel()

    @tasks.loop(minutes=15)
    async def find_posts(self):
        start_time = time()
        channel = self.bot.get_channel(self.config.channel_id)

        # Update first run
        post_limit: int = 250 if self.first_run else 50
        self.first_run = False

        redditrequest: Subreddit = await self.reddit.subreddit('redditrequest')
        await redditrequest.load()

        new_submissions: List[Submission] = await aiostream.stream.list(redditrequest.new(limit=post_limit))
        submission: Submission
        for submission in reversed(new_submissions):

            # Check if post is already in database
            if self.is_already_posted(submission.id):
                print(f'{Fore.BLUE}    '
                      f'Submission already posted  '
                      f'{Style.RESET_ALL}')
                continue

            await submission.load()
            submission_state = await self.get_submission_state(submission)

            # Parse the subreddit name from url provided in post, get the submission author and the subreddit object
            subreddit_name: str = self.get_subreddit_name_from_url(submission.url)
            author: Redditor = submission.author
            await author.load()
            subreddit: Subreddit = await self.reddit.subreddit(subreddit_name)
            subreddit_state = await self.get_subreddit_state(subreddit)

            print(f'{Fore.BLUE}    '
                  f'r/{subreddit_name} - u/{"[deleted]" if author is None else author.name} - '
                  f'State: {subreddit_state.name}  '
                  f'{Style.RESET_ALL}')

            # Build embed, send message, store in database
            embed = await self.build_embed(submission, author, subreddit, subreddit_name, subreddit_state)
            message = await channel.send(embed=embed)

            self.put_message_into_database(submission, message)
            self.put_post_into_database(submission, subreddit_name, submission_state)

            # Remove reaction and add reaction if already granted or denied
            if submission_state == SubmissionState.GRANTED:
                await message.add_reaction('✔')
            elif submission_state == SubmissionState.DENIED:
                await message.add_reaction('❌')
            else:
                await message.add_reaction('🆕')
        stop_time = time()
        print(f'{Fore.BLUE}> Finished scraping new posts. Took: {strftime("%H:%M:%S", gmtime(stop_time - start_time))}  {Style.RESET_ALL}')

    @find_posts.before_loop
    async def before_scrape_scoreboard(self) -> None:
        print(f'{Fore.BLUE}> Preparing to scrape new posts  {Style.RESET_ALL}')
        await self.bot.wait_until_ready()

    @tasks.loop(hours=2)
    async def update_posts(self):
        start_time = time()

        # Get channel, instantiate the cache list, retrieve the reddit instance
        channel: TextChannel = self.bot.get_channel(self.config.channel_id)
        reddit = self.reddit

        # Get posts to check (only choose posts not younger than min_age or update within min_age or older than max_age)
        cursor = self.database.cursor()
        now = datetime.now()
        min_age: int = int((now - timedelta(hours=self.config.min_post_age)).timestamp())
        max_age: int = int((now - timedelta(days=self.config.max_post_age)).timestamp())

        count_stmt = 'SELECT COUNT(*) FROM posts ' \
                     'WHERE status != ? AND created_at <= ? AND created_at >= ? AND updated_at <= ? ' \
                     'ORDER BY id'
        cursor.execute(count_stmt, (SubmissionState.GRANTED.value, min_age, max_age, min_age))
        estimated_posts = cursor.fetchone()[0]
        updated_posts = 0

        cursor = self.database.cursor()
        select_stmt = 'SELECT post_id FROM posts ' \
                      'WHERE status != ? AND created_at <= ? AND created_at >= ? AND updated_at <= ? ' \
                      'ORDER BY id'
        cursor.execute(select_stmt, (SubmissionState.GRANTED.value, min_age, max_age, min_age))

        print(f'{Fore.GREEN}> '
              f'Revisiting: {Fore.RED}{estimated_posts}{Fore.GREEN} posts with this batch  '
              f'{Style.RESET_ALL}')

        for data in cursor:
            submission_id: str = data[0]

            print(f'{Fore.GREEN}    '
                  f'Fetching {Fore.RED}{updated_posts}{Fore.GREEN}/'
                  f'{Fore.RED}{estimated_posts}{Fore.GREEN} - '
                  f'{Fore.RED}{int(((updated_posts + 1) / estimated_posts) * 100)}%  '
                  f'{Style.RESET_ALL}')

            submission = await reddit.submission(id=submission_id)
            message_id: int = self.get_message_id_from_database(submission_id)

            # Get message from discord
            message: Message = await channel.fetch_message(message_id)
            await message.remove_reaction('🆕', self.bot.user)

            # Add loading reaction-emoji to message
            await message.add_reaction('🔄')

            # get message and submission
            subreddit_name = self.get_subreddit_name_from_url(submission.url)
            subreddit = await reddit.subreddit(subreddit_name)
            subreddit_state = await self.get_subreddit_state(subreddit)

            submission = submission
            author = submission.author
            await author.load()

            # Update embed in Discord message
            embed = await self.build_embed(submission,
                                           submission.author,
                                           subreddit,
                                           subreddit_name,
                                           subreddit_state)
            await message.edit(embed=embed)

            # Prepare database update
            timestamp: int = int(datetime.now().timestamp())
            submission_state: SubmissionState = await self.get_submission_state(submission)
            submission_id: str = submission_id
            message_id: int = message_id

            # Update on CLI
            print(f'    {Fore.RED}{updated_posts}{Fore.GREEN}/'
                  f'{Fore.RED}{estimated_posts}{Fore.GREEN} - '
                  f'{Fore.RED}{int(((updated_posts + 1) / estimated_posts) * 100)}{Fore.GREEN}% '
                  f'{submission_id}: {subreddit_name} state: {submission_state.name} '
                  f'{Style.RESET_ALL}')

            # Update database
            posts_update_stmt = 'UPDATE posts SET updated_at = ?, status = ? WHERE post_id == ?'
            messages_update_stmt = 'UPDATE messages SET updated_at = ? WHERE message_id == ?'

            # Update timestamps in database
            cursor.execute(posts_update_stmt, (timestamp, submission_state.value, submission_id))
            cursor.execute(messages_update_stmt, (timestamp, message_id))
            self.database.commit()

            # Remove reaction and add reaction if already granted or denied
            await message.remove_reaction('🔄', self.bot.user)
            if submission_state == SubmissionState.GRANTED:
                await message.add_reaction('✔')
            elif submission_state == SubmissionState.DENIED:
                await message.add_reaction('❌')
            updated_posts += 1

        stop_time = time()
        print(f'{Fore.GREEN}> '
              f'Finished: Revisited {Fore.RED}{updated_posts}{Fore.GREEN} posts with this batch '
              f'{strftime("%H:%M:%S", gmtime(stop_time - start_time))}s  '
              f'{Style.RESET_ALL}')

    @update_posts.before_loop
    async def before_checkup_scoreboard(self) -> None:
        print(f'{Fore.GREEN}> Getting ready to validate previous posts {Style.RESET_ALL}')
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
        data = cursor.fetchall()
        if len(data) == 0:
            return False
        return True

    def get_message_id_from_database(self, submission_id: str):
        cursor = self.database.cursor()
        select_stmt = 'SELECT * FROM messages WHERE submission == ?'
        cursor.execute(select_stmt, (submission_id, ))
        return cursor.fetchone()[1]

    def put_post_into_database(self, submission: Submission, subreddit_name: str, submission_state: SubmissionState) \
            -> None:
        """This method puts a submission (and author) into the database"""
        cursor = self.database.cursor()
        insert_stmt = 'INSERT INTO posts(post_id, subreddit, updated_at, created_at, status) ' \
                      'VALUES (?, ?, ?, ?, ?)'
        cursor.execute(insert_stmt, (submission.id,
                                     subreddit_name,
                                     int(datetime.now().timestamp()),
                                     int(datetime.now().timestamp()),
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

    async def get_subreddit_state(self, subreddit: Subreddit) -> SubredditState:
        try:
            await subreddit.load()
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

    async def get_submission_state(self, submission: Submission) -> SubmissionState:
        comments = await submission.comments()
        async for tlc in comments:
            await tlc.load()
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

    async def get_subreddit_moderators(self, subreddit: Subreddit) -> List[str]:
        moderators: List[str] = []
        async for mod in subreddit.moderator:
            moderators.append(f'u/{mod.name}')
        return moderators

    async def build_embed(self, submission: Submission,
                          author: Redditor,
                          subreddit: Subreddit,
                          subreddit_name: str,
                          subreddit_state: SubredditState) -> Embed:
        state = subreddit_state
        submission_state = await self.get_submission_state(submission)

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

            moderators = await self.get_subreddit_moderators(subreddit)

            embed.add_field(name='Moderators', value=str(len(moderators)), inline=True)
            if not len(moderators) == 0:
                embed.add_field(name='Moderators', value=str(', '.join(moderators)), inline=False)
            embed.add_field(name='Subreddit created',
                            value=datetime.utcfromtimestamp(subreddit.created_utc).strftime('%Y-%m-%d'),
                            inline=True)

        if author is not None and not hasattr(author, 'is_suspended'):
            embed.add_field(name='Account created',
                            value=datetime.utcfromtimestamp(author.created_utc).strftime('%Y-%m-%d'),
                            inline=True)
        return embed
