# RedditRequestOverview
## How to use:
The script requires the following packages:
- discord.py
- praw
- colorama
- py_dotenv

The script requres a ``.env`` file in the same directory with the following content:
```dotenv
#.env
DISCORD_TOKEN=<Discord API Token>
REDDIT_SECRET=<Reddit client secret>
REDDIT_CLIENT_ID=<Reddit client id>
REDDIT_USER_AGENT=<Reddit user agent>
REDDIT_SUBREDDIT=redditrequest
REDDIT_USERNAME=<Reddit username>
REDDIT_PASSWORD=<Reddit password>
# How old should a post be before it gets updated [hours]
MIN_POST_AGE=1
# How old should a post be before it stops getting updated [days]
MAX_POST_AGE=21
# What channel to post in (channelid)
CHANNEL_ID=<Your channel ID>
```

the script can then be run with the command
``python main.py``
python version 3.9 is required.