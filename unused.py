from praw import Reddit
from pprint import pprint
from datetime import datetime

debug_mode = False
REDDIT_SECRET = "zOzRFXaMoHYRAXAkO3XhTJsJKra4yg"
CLIENT_ID = "ul-1SIpjUWtyBtMHJSxdRQ"
USER_AGENT = "RRSB"
SUBREDDIT = "redditrequest"


def main():
    reddit = Reddit(client_id=CLIENT_ID,
                    client_secret=REDDIT_SECRET,
                    user_agent=USER_AGENT,
                    username="AstralJaegerBot",
                    password="2l2VjcKR5$5cDe#mq&PMPsgVaKVbNIOm")

    print(f'Authenticated: {reddit.user.me()}')
    print(f'READ-ONLY: {reddit.read_only}')

    subreddit = reddit.subreddit("redditrequest")
    print(f'Display name: {subreddit.display_name}')
    print(f'Title:        {subreddit.title}')

    if debug_mode:
        print(" SUBMISSION ".center(64, "="))
        submission = reddit.submission(id="39zje0")
        print(submission.title)
        pprint(vars(submission))

        print(" COMMENT ".center(64, "="))
        comment = reddit.comment(id="t1_cs7vwlm")
        print(comment.author)
        pprint(vars(comment))

    print(" SUBMISSIONS ".center(64, "="))
    for submission in subreddit.new(limit=100):
        title = submission.title

        # Clean up subreddit url to get a proper name
        target_subreddit = submission.url
        target_subreddit = target_subreddit[[i for i, n in enumerate(target_subreddit) if n == '/'][2] + 1:]
        if "?" in target_subreddit:
            target_subreddit = target_subreddit[:[i for i, n in enumerate(target_subreddit) if n == '?'][0]]
        if "/" == target_subreddit[-1:]:
            target_subreddit = target_subreddit.rstrip(target_subreddit[-1:])
        if target_subreddit.count('/') > 1:
            # Invalid request, just skip
            continue

        # Get the state of the request
        state = ""
        for tlc in submission.comments:
            author = tlc.author
            if author.name == "request_bot":
                tlc_body = tlc.body
                if "manual review" in tlc_body:
                    state = "MANUAL REVIEW"
                if "has been granted" in tlc_body or "Approved" in tlc_body:
                    state = "GRANTED"
                if "cannot be transferred" in tlc_body:
                    state = "DENIED"
                if "directly messaging the mod team" in tlc_body:
                    state = "ASK FOR FOLLOWUP"
                break

        posted = datetime.utcfromtimestamp(submission.created_utc)
        print(f"> {submission.id}: {target_subreddit}")
        print(f"  Approved: {state} - Posted: {posted}")


if __name__ == '__main__':
    main()

