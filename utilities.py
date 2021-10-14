from typing import List

from asyncpraw.reddit import Subreddit, Submission
from asyncprawcore import Forbidden, NotFound, BadRequest
from discord import Color

from models import SubredditState, SubmissionState


def get_subreddit_name(url: str) -> str:
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


async def get_subreddit_state(subreddit: Subreddit) -> SubredditState:
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


async def get_submission_state(submission: Submission) -> SubmissionState:
    comments = await submission.comments()
    async for tlc in comments:
        await tlc.load()
        if tlc.author_flair_text is not None and "admin" in tlc.author_flair_text:
            tlc_body: str = tlc.body
            comment = tlc_body.lower()
            if "directly messaging the mod team" in comment:
                return SubmissionState.FOLLOWUP
            elif 'manual review' in comment:
                return SubmissionState.MANUAL_REVIEW
            elif "has been granted" in comment or "approved" in comment:
                return SubmissionState.GRANTED
            elif "cannot be transferred" in comment or \
                 "aren't eligible for request" in comment or \
                 "not to approve" in comment or \
                 "mods are still active" in comment:
                return SubmissionState.DENIED

    return SubmissionState.NOT_ASSESSED


def get_embed_color(submission_state: SubmissionState) -> Color:
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


async def get_subreddit_moderators(subreddit: Subreddit) -> List[str]:
    moderators: List[str] = []
    async for mod in subreddit.moderator:
        moderators.append(f'u/{mod.name}')
    return moderators
