"""SQLite persistence. Stores only the encrypted cookie, the shard, and a
timestamp — never a plaintext secret."""

import sqlite3
import time
from pathlib import Path


class Storage:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                   telegram_id INTEGER PRIMARY KEY,
                   enc_cookie  BLOB NOT NULL,
                   shard       TEXT NOT NULL,
                   linked_at   REAL NOT NULL,
                   last_used   REAL
               )"""
        )
        self.conn.commit()

    def upsert(self, telegram_id, enc_cookie, shard):
        self.conn.execute(
            """INSERT INTO users (telegram_id, enc_cookie, shard, linked_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(telegram_id) DO UPDATE SET
                   enc_cookie=excluded.enc_cookie,
                   shard=excluded.shard,
                   linked_at=excluded.linked_at""",
            (telegram_id, enc_cookie, shard, time.time()),
        )
        self.conn.commit()

    def get(self, telegram_id):
        row = self.conn.execute(
            "SELECT enc_cookie, shard FROM users WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone()
        if not row:
            return None
        return {"enc_cookie": row[0], "shard": row[1]}

    def update_cookie(self, telegram_id, enc_cookie):
        self.conn.execute(
            "UPDATE users SET enc_cookie=?, last_used=? WHERE telegram_id=?",
            (enc_cookie, time.time(), telegram_id),
        )
        self.conn.commit()

    def delete(self, telegram_id):
        self.conn.execute("DELETE FROM users WHERE telegram_id=?", (telegram_id,))
        self.conn.commit()
