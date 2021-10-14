from typing import List
from datetime import datetime, timedelta
from sqlite3 import Connection

import aiostream.stream

from database import Database
from models import Config, SubredditState, SubmissionState
from utilities import get_subreddit_state, get_submission_state, get_subreddit_moderators, \
    get_subreddit_name, get_embed_color
from time import time, gmtime, strftime

from discord import Embed, Color, Message, TextChannel, Guild, Member
from discord.ext import tasks, commands
from discord.ext.commands import Bot

from asyncpraw import Reddit
from asyncpraw.models import Subreddit
from asyncpraw.reddit import Submission, Redditor

from colorama import Fore, Style


class RedditCog(commands.Cog, name='RedditCog'):
    def __init__(self, bot: Bot, reddit: Reddit, database: Database, config: Config):
        self.bot: Bot = bot
        self.reddit: Reddit = reddit
        self.database: Database = database
        self.config: Config = config

        self.first_run = True

        self.find_posts.start()
        self.update_posts.start()

    def cog_unload(self):
        self.find_posts.cancel()
        self.update_posts.cancel()

    @tasks.loop(minutes=5)
    async def find_posts(self):
        start_time = time()
        channels: List[TextChannel] = self.get_all_channels()

        # Update first run
        post_limit: int = 250 if self.first_run else 50
        self.first_run = False

        redditrequest: Subreddit = await self.reddit.subreddit('redditrequest')
        await redditrequest.load()

        new_submissions: List[Submission] = await aiostream.stream.list(redditrequest.new(limit=post_limit))
        submission: Submission
        for submission in reversed(new_submissions):

            # Check if post is already in database
            if self.database.is_already_submitted(submission.id):
                continue

            await submission.load()
            submission_state = await get_submission_state(submission)

            # Parse the subreddit name from url provided in post, get the submission author and the subreddit object
            subreddit_name: str = get_subreddit_name(submission.url)
            author: Redditor = submission.author
            if author is not None:
                await author.load()
            subreddit: Subreddit = await self.reddit.subreddit(subreddit_name)
            subreddit_state = await get_subreddit_state(subreddit)

            print(f'{Fore.BLUE}    '
                  f'r/{subreddit_name} - u/{"[deleted]" if author is None else author.name} - '
                  f'State: {subreddit_state.name}  '
                  f'{Style.RESET_ALL}')

            # Build embed, send message, store in database
            embed = await self.build_embed(submission, author, subreddit, subreddit_name, subreddit_state)

            for channel in channels:
                message = await channel.send(embed=embed)
                self.database.put_message(message, submission)

                # Remove reaction and add reaction if already granted or denied
                if submission_state == SubmissionState.GRANTED:
                    await message.add_reaction('✔')
                elif submission_state == SubmissionState.DENIED:
                    await message.add_reaction('❌')
                else:
                    await message.add_reaction('🆕')
                # await message.add_reaction('📌')

            await self.database.put_submission(submission, subreddit_name, submission_state)

        stop_time = time()
        print(
            f'{Fore.BLUE}> Finished scraping new posts. Took: {strftime("%H:%M:%S", gmtime(stop_time - start_time))}  {Style.RESET_ALL}')

    @find_posts.before_loop
    async def before_scrape_scoreboard(self) -> None:
        print(f'{Fore.BLUE}> Preparing to scrape new posts  {Style.RESET_ALL}')
        await self.bot.wait_until_ready()

    @tasks.loop(hours=2)
    async def update_posts(self):
        start_time = time()

        # retrieve the reddit instance
        reddit = self.reddit

        # Get posts to check (only choose posts not younger than min_age or update within min_age or older than max_age)
        now = datetime.now()
        min_age: int = int((now - timedelta(hours=self.config.min_post_age)).timestamp())
        max_age: int = int((now - timedelta(days=self.config.max_post_age)).timestamp())

        estimated_posts = self.database.get_update_submission_count(min_age, max_age)
        updated_posts = 0

        print(f'{Fore.GREEN}> '
              f'Revisiting: {Fore.RED}{estimated_posts}{Fore.GREEN} posts with this batch  '
              f'{Style.RESET_ALL}')

        for data in self.database.get_update_submissions(min_age, max_age):
            submission_id: str = data["submission_id"]
            submission = await reddit.submission(id=submission_id)

            # TODO Rewrite to use database and utilities
            # get subreddit name, subreddit, subreddit state, submission, author and build embed
            subreddit_name = get_subreddit_name(submission.url)
            subreddit = await reddit.subreddit(subreddit_name)
            subreddit_state = await get_subreddit_state(subreddit)
            author = submission.author
            if not author is None:
                await author.load()

            # Update embed in Discord message
            embed = await self.build_embed(submission,
                                           submission.author,
                                           subreddit,
                                           subreddit_name,
                                           subreddit_state)

            # Prepare database update
            timestamp: int = int(datetime.now().timestamp())
            submission_state: SubmissionState = await get_submission_state(submission)
            submission_id: str = submission_id

            # Update on CLI
            print(f'    {Fore.RED}{updated_posts}{Fore.GREEN}/'
                  f'{Fore.RED}{estimated_posts}{Fore.GREEN} - '
                  f'{Fore.RED}{int(((updated_posts + 1) / estimated_posts) * 100)}{Fore.GREEN}% '
                  f'{submission_id}: {subreddit_name} state: {submission_state.name} '
                  f'{Style.RESET_ALL}')

            # Update messages in database
            for channel_id, message_id in self.database.get_message_ids(submission_id):
                channel: TextChannel = self.bot.get_channel(channel_id)
                if channel is None:
                    continue
                message: Message = await channel.fetch_message(message_id)
                await message.remove_reaction('🆕', self.bot.user)
                await message.add_reaction('🔄')
                await message.edit(embed=embed)
                await message.remove_reaction('🔄', self.bot.user)

                # Remove reaction and add reaction if already granted or denied
                await message.remove_reaction('🔄', self.bot.user)
            updated_posts += 1
            self.database.update_message(submission_id, timestamp)
            self.database.update_post(submission_id, timestamp, submission_state)

        stop_time = time()
        print(f'{Fore.GREEN}> '
              f'Finished: Revisited {Fore.RED}{updated_posts}{Fore.GREEN} posts with this batch. Took: '
              f'{strftime("%H:%M:%S", gmtime(stop_time - start_time))} '
              f'Average: {strftime("%M:%S", gmtime(int((stop_time - start_time)/max(updated_posts, 1))))}   '
              f'{Style.RESET_ALL}')

    @update_posts.before_loop
    async def before_checkup_scoreboard(self) -> None:
        print(f'{Fore.GREEN}> Getting ready to validate previous posts {Style.RESET_ALL}')
        await self.bot.wait_until_ready()

    @commands.cooldown(1, 60, commands.BucketType.guild)
    @commands.command(name="details")
    async def request_details(self, ctx, arg):
        await ctx.send(f'Argument: {arg}')

    @commands.cooldown(1, 30, commands.BucketType.guild)
    @commands.command(name="statistics")
    async def request_statistics(self, ctx, timeframe: int = 24):
        embed: Embed = Embed(color=Color.from_rgb(0, 187, 255))
        embed.title = "Statistics"

        now = datetime.now()
        max_age: int = int((now - timedelta(days=timeframe)).timestamp())
        post_count = self.database.get_post_count(max_age)
        granted_count = self.database.get_post_count_with_status(max_age, SubmissionState.GRANTED)
        denied_count = self.database.get_post_count_with_status(max_age, SubmissionState.DENIED)
        followup_count = self.database.get_post_count_with_status(max_age, SubmissionState.FOLLOWUP)
        manualreview_count = self.database.get_post_count_with_status(max_age, SubmissionState.MANUAL_REVIEW)
        notassessed_count = self.database.get_post_count_with_status(max_age, SubmissionState.NOT_ASSESSED)

        embed.add_field(name='Timeframe', value=f'{timeframe}h', inline=True)
        embed.add_field(name='Posts', value=f'{post_count}', inline=True)
        embed.add_field(name='\u200b', value='\u200b', inline=False)
        embed.add_field(name='Granted', value=f'{granted_count}', inline=True)
        embed.add_field(name='Denied', value=f'{denied_count}', inline=True)
        embed.add_field(name='\u200b', value='\u200b', inline=False)
        embed.add_field(name='Followup', value=f'{followup_count}', inline=True)
        embed.add_field(name='Manual review', value=f'{manualreview_count}', inline=True)
        embed.add_field(name='Not assessed', value=f'{notassessed_count}', inline=True)
        embed.add_field(name='\u200b', value='\u200b', inline=False)
        embed.add_field(name='Success-rate', value=f'{round(granted_count/post_count*100, 2)}%', inline=True)
        embed.add_field(name='Denial-rate', value=f'{round(denied_count/post_count*100, 2)}%', inline=True)
        embed.add_field(name='Manual-review-rate', value=f'{round(manualreview_count/post_count*100, 2)}%', inline=True)

        embed.timestamp = now
        embed.set_author(name='r/RedditRequest',
                         icon_url='https://styles.redditmedia.com/t5_2rlnw/styles/communityIcon_s4c3lvscu5x11.png?width=256&s=27a7e5edddf7d81f2591f5c0deb78e74cacfadf6')
        embed.set_image(url='https://styles.redditmedia.com/t5_2rlnw/styles/bannerBackgroundImage_m1rtyjm9u5x11.jpg?width=4000&format=pjpg&s=aaa5357108238dd8264de87af6e1ab54914dabaf')

        await ctx.send(embed=embed)

    def get_all_channels(self) -> List[TextChannel]:
        channels: List[TextChannel] = []
        guild: Guild
        for guild in self.bot.guilds:
            channel: TextChannel
            for channel in guild.text_channels:
                if channel.name == self.config.channel_name:
                    channels.append(channel)
        return channels

    async def build_embed(self, submission: Submission,
                          author: Redditor,
                          subreddit: Subreddit,
                          subreddit_name: str,
                          subreddit_state: SubredditState) -> Embed:
        state = subreddit_state
        submission_state = await get_submission_state(submission)

        embed = Embed(title=f'r/{subreddit_name}', color=get_embed_color(submission_state))
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

            moderators = await get_subreddit_moderators(subreddit)

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
