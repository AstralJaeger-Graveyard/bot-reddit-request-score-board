from typing import List, Generator, Dict
import sqlite3
from sqlite3 import Connection
from datetime import datetime
from os import path

from asyncpraw.reddit import Submission, Redditor
from discord import Message, TextChannel
from discord.ext.commands import Bot

from models import SubmissionState


class Database:
    def __init__(self, database_name: str):
        self.database_name: str = database_name
        self.__check_database_name()
        db_path = path.join(path.dirname(__file__), self.database_name)

        self.connection: Connection = sqlite3.connect(db_path)

        self.__setup_database()

    def __check_database_name(self) -> None:
        """This method makes sure the database name is somewhat adequate"""
        if not self.database_name.endswith('.sqlite'):
            self.database_name = self.database_name + '.sqlite'
        self.database_name.replace(" ", "_")

    def __setup_database(self) -> None:
        """This method initializes the database, adding all necessary tabes"""

        cursor = self.connection.cursor()
        create_table_posts = "CREATE TABLE IF NOT EXISTS submissions(" \
                             "id INTEGER PRIMARY KEY AUTOINCREMENT," \
                             "submission_id TEXT UNIQUE," \
                             "subreddit TEXT," \
                             "created_at INTEGER, " \
                             "updated_at INTEGER, " \
                             "status INTEGER DEFAULT 0" \
                             ")"
        cursor.execute(create_table_posts)
        create_table_users = "CREATE TABLE IF NOT EXISTS redditors(" \
                             "id INTEGER PRIMARY KEY AUTOINCREMENT," \
                             "user_name TEXT UNIQUE," \
                             "user_id TEXT UNIQUE," \
                             "request_count INTEGER DEFAULT  1" \
                             ")"
        cursor.execute(create_table_users)
        create_table_messages = "CREATE TABLE IF NOT EXISTS messages(" \
                                "id INTEGER PRIMARY KEY AUTOINCREMENT," \
                                "message_id INTEGER UNIQUE," \
                                "channel_id INTEGER, " \
                                "submission_id TEXT, " \
                                "created_at INTEGER, " \
                                "updated_at INTEGER" \
                                ")"
        cursor.execute(create_table_messages)
        self.connection.commit()

    async def put_submission(self, submission: Submission, subreddit_name: str, submission_state: SubmissionState)\
            -> None:
        """This method inserts a submission into the database"""
        cursor = self.connection.cursor()
        insert_stmt: str = 'INSERT INTO submissions(submission_id, subreddit, updated_at, created_at, status) ' \
                           'VALUES (?, ?, ?, ?, ?)'
        cursor.execute(insert_stmt, (submission.id,
                                     subreddit_name,
                                     int(datetime.now().timestamp()),
                                     int(datetime.now().timestamp()),
                                     submission_state.value))

        # Handle author aswell
        author = submission.author
        if author is None:
            self.connection.commit()
            return
        await self.put_redditor(author)

    async def put_redditor(self, redditor: Redditor) -> None:
        """This method inserts a redditor into the database and increments the count of request if there has already
        been a previous submission """
        await redditor.load()
        if hasattr(redditor, 'is_suspended'):
            return

        cursor = self.connection.cursor()
        select_stmt = 'SELECT user_id, request_count FROM redditors WHERE user_id = ?'
        cursor.execute(select_stmt, (redditor.id, ))

        row_id = -1
        request_count = 0
        for usr in cursor:
            row_id = usr[0]
            request_count = usr[2]

        if row_id == -1:
            insert_stmt = 'INSERT INTO redditors(user_name, user_id, request_count) VALUES (?, ?, ?)'
            cursor.execute(insert_stmt, (redditor.name, redditor.id, 1))
        else:
            update_stmt = 'UPDATE redditors SET request_count = ? WHERE user_id = ?'
            cursor.execute(update_stmt, (request_count, redditor.id))

        self.connection.commit()

    def put_message(self, message: Message, submission: Submission) -> None:
        """This methods inserts a message into the database"""
        timestamp = int(datetime.now().timestamp())
        cursor = self.connection.cursor()
        insert_stmt = 'INSERT INTO messages(message_id, channel_id, submission_id, created_at, updated_at) ' \
                      'VALUES (?, ?, ?, ?, ?)'
        cursor.execute(insert_stmt, (message.id, message.channel.id, submission.id, timestamp, timestamp))
        self.connection.commit()

    def is_already_submitted(self, submission_id: str) -> bool:
        """Checks if a submission is already in the database"""
        cursor = self.connection.cursor()
        select_stmt = "SELECT (submission_id) FROM submissions WHERE submission_id = ?"
        cursor.execute(select_stmt, (submission_id,))
        data = cursor.fetchall()
        if len(data) == 0:
            return False
        return True

    async def get_messages(self, bot: Bot, submission_id: str) -> List[Message]:
        cursor = self.connection.cursor()
        select_stmt = 'SELECT * FROM messages WHERE submission == ?'
        cursor.execute(select_stmt, (submission_id,))
        messages: List[Message] = []
        for entry in cursor:
            channel: TextChannel = bot.get_channel(entry[2])
            if channel is None:
                continue

            message = await channel.fetch_message(entry[1])
            messages.append(message)
        return messages

    def get_update_submission_count(self, min_age: int, max_age: int) -> int:
        cursor = self.connection.cursor()
        count_stmt = 'SELECT COUNT(*) FROM submissions ' \
                     'WHERE status != ? AND created_at <= ? AND created_at >= ? AND updated_at <= ? ' \
                     'ORDER BY id'
        cursor.execute(count_stmt, (SubmissionState.GRANTED.value, min_age, max_age, min_age))
        return cursor.fetchone()[0]

    def get_update_submissions(self, min_age: int, max_age: int):
        cursor = self.connection.cursor()
        select_stmt = 'SELECT submission_id, subreddit FROM submissions ' \
                      'WHERE status != ? AND created_at <= ? AND created_at >= ? AND updated_at <= ? ' \
                      'ORDER BY id'
        cursor.execute(select_stmt, (SubmissionState.GRANTED.value, min_age, max_age, min_age))
        for row in cursor:
            data = {
                'submission_id': row[0],
                'subreddit': row[1]
            }
            yield data

    def get_message_ids(self, submission_id: str):
        """
        Returns a generator for all message id's for a submission.

        :returns

        channel_id: int The id of the channel of a message

        message_id: int The id of the message within a channel
        """
        cursor = self.connection.cursor()
        select_stmt = 'SELECT * from messages WHERE submission_id == ?'
        cursor.execute(select_stmt, (submission_id,))
        for row in cursor:
            yield row[2], row[1]

    def update_message(self, submission_id: str, timestamp: int) -> None:
        cursor = self.connection.cursor()
        messages_update_stmt = 'UPDATE messages SET updated_at = ? WHERE submission_id == ?'
        cursor.execute(messages_update_stmt, (timestamp, submission_id))
        self.connection.commit()

    def update_post(self, submission_id: str, timestamp: int, status: SubmissionState) -> None:
        cursor = self.connection.cursor()
        posts_update_stmt = 'UPDATE submissions SET updated_at = ?, status = ? WHERE submission_id == ?'
        cursor.execute(posts_update_stmt, (submission_id, timestamp, status.value))
        self.connection.commit()

    def get_post_count(self, max_age: int) -> int:
        cursor = self.connection.cursor()
        count_stmt = 'SELECT COUNT(*) FROM submissions ' \
                     'WHERE created_at >= ? '
        cursor.execute(count_stmt, (max_age, ))
        return cursor.fetchone()[0]

    def get_post_count_with_status(self, max_age: int, status: SubmissionState) -> int:
        cursor = self.connection.cursor()
        count_stmt = 'SELECT COUNT(*) FROM submissions ' \
                     'WHERE status == ? and created_at >= ? '
        cursor.execute(count_stmt, (status.value, max_age))
        return cursor.fetchone()[0]