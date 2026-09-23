"""Account persistence.

The interface comes first so the service layer depends on the contract rather
than on SQLite, which also lets the tests substitute an in-memory fake.

The account list is runtime state, not configuration: adding and removing an
account are ordinary writes here, so the bot never needs a restart to change who
it serves or which accounts it holds.
"""

import logging
import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path

from valstore.models import Account

log = logging.getLogger("valstore.repository")

_ACCOUNTS_DDL = """
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    label       TEXT    NOT NULL,
    puuid       TEXT,
    riot_name   TEXT,
    riot_tag    TEXT,
    shard       TEXT    NOT NULL,
    enc_cookie  BLOB    NOT NULL,
    is_default  INTEGER NOT NULL DEFAULT 0,
    linked_at   REAL    NOT NULL,
    last_used   REAL,
    UNIQUE(telegram_id, puuid)
)
"""

_COLUMNS = (
    "id, telegram_id, label, puuid, riot_name, riot_tag, shard, enc_cookie, "
    "is_default, linked_at, last_used"
)


class AccountRepository(ABC):
    """Storage contract for linked accounts."""

    @abstractmethod
    def list_for(self, telegram_id: int) -> list[Account]:
        """Every account for this user, default first, then by label."""

    @abstractmethod
    def get(self, account_id: int, telegram_id: int) -> Account | None:
        """One account, scoped to its owner so an id alone grants nothing."""

    @abstractmethod
    def get_default(self, telegram_id: int) -> Account | None:
        """The account to act on when the user did not pick one."""

    @abstractmethod
    def find_by_puuid(self, telegram_id: int, puuid: str) -> Account | None:
        """Used to re-link an existing account instead of duplicating it."""

    @abstractmethod
    def add(self, telegram_id, label, shard, enc_cookie,
            puuid=None, riot_name=None, riot_tag=None) -> Account:
        """Insert an account. The user's first becomes their default."""

    @abstractmethod
    def remove(self, account_id: int, telegram_id: int) -> bool:
        """Delete an account, promoting a new default if this was it."""

    @abstractmethod
    def rename(self, account_id: int, telegram_id: int, label: str) -> bool:
        """Change the friendly label."""

    @abstractmethod
    def set_default(self, account_id: int, telegram_id: int) -> bool:
        """Make this the account acted on when none is picked."""

    @abstractmethod
    def update_cookie(self, account_id: int, enc_cookie: bytes) -> None:
        """Persist a rotated session and stamp last_used."""

    @abstractmethod
    def update_identity(self, account_id, puuid, riot_name, riot_tag) -> None:
        """Backfill Riot identity once a session reveals it."""

    @abstractmethod
    def count_for(self, telegram_id: int) -> int:
        """How many accounts this user holds, for the per-user cap."""


class SqliteAccountRepository(AccountRepository):
    """SQLite implementation.

    Calls are expected from the event-loop thread only; Riot I/O is what gets
    pushed to a worker thread, never these. The connection is therefore left
    with sqlite3's default same-thread guard as a tripwire on that assumption.
    """

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    # ---- schema ----

    def _table_exists(self, name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    def _migrate(self) -> None:
        """Create the accounts table and fold any legacy single-account rows in.

        The old `users` table is renamed rather than dropped, so a migration that
        goes wrong is recoverable from the same database file.
        """
        with self.conn:
            self.conn.execute(_ACCOUNTS_DDL)
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_accounts_owner "
                "ON accounts(telegram_id)"
            )

            if not self._table_exists("users"):
                return

            legacy = self.conn.execute(
                "SELECT telegram_id, enc_cookie, shard, linked_at, last_used "
                "FROM users"
            ).fetchall()

            migrated = 0
            for row in legacy:
                # Skip anyone already migrated, so a half-finished run is safe
                # to repeat.
                existing = self.conn.execute(
                    "SELECT 1 FROM accounts WHERE telegram_id=?",
                    (row["telegram_id"],),
                ).fetchone()
                if existing:
                    continue
                self.conn.execute(
                    "INSERT INTO accounts (telegram_id, label, shard, enc_cookie,"
                    " is_default, linked_at, last_used)"
                    " VALUES (?, ?, ?, ?, 1, ?, ?)",
                    (row["telegram_id"], "Account 1", row["shard"],
                     row["enc_cookie"], row["linked_at"], row["last_used"]),
                )
                migrated += 1

            self.conn.execute("ALTER TABLE users RENAME TO users_legacy")
            log.info("Migrated %d legacy account(s); old table kept as "
                     "users_legacy.", migrated)

    # ---- reads ----

    def _row_to_account(self, row: sqlite3.Row) -> Account:
        return Account(
            id=row["id"],
            telegram_id=row["telegram_id"],
            label=row["label"],
            shard=row["shard"],
            enc_cookie=row["enc_cookie"],
            is_default=bool(row["is_default"]),
            linked_at=row["linked_at"],
            puuid=row["puuid"],
            riot_name=row["riot_name"],
            riot_tag=row["riot_tag"],
            last_used=row["last_used"],
        )

    def list_for(self, telegram_id):
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE telegram_id=?"
            " ORDER BY is_default DESC, LOWER(label)",
            (telegram_id,),
        ).fetchall()
        return [self._row_to_account(r) for r in rows]

    def get(self, account_id, telegram_id):
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE id=? AND telegram_id=?",
            (account_id, telegram_id),
        ).fetchone()
        return self._row_to_account(row) if row else None

    def get_default(self, telegram_id):
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE telegram_id=?"
            " ORDER BY is_default DESC, LOWER(label) LIMIT 1",
            (telegram_id,),
        ).fetchone()
        return self._row_to_account(row) if row else None

    def find_by_puuid(self, telegram_id, puuid):
        if not puuid:
            return None
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM accounts WHERE telegram_id=? AND puuid=?",
            (telegram_id, puuid),
        ).fetchone()
        return self._row_to_account(row) if row else None

    def count_for(self, telegram_id):
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM accounts WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone()
        return row["n"] if row else 0

    # ---- writes ----

    def add(self, telegram_id, label, shard, enc_cookie,
            puuid=None, riot_name=None, riot_tag=None):
        now = time.time()
        with self.conn:
            first = self.count_for(telegram_id) == 0
            cur = self.conn.execute(
                "INSERT INTO accounts (telegram_id, label, puuid, riot_name,"
                " riot_tag, shard, enc_cookie, is_default, linked_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (telegram_id, label, puuid, riot_name, riot_tag, shard,
                 enc_cookie, 1 if first else 0, now),
            )
            account_id = cur.lastrowid
        created = self.get(account_id, telegram_id)
        if created is None:  # pragma: no cover - insert succeeded, row must exist
            raise RuntimeError("Account vanished immediately after insert")
        return created

    def remove(self, account_id, telegram_id):
        with self.conn:
            row = self.conn.execute(
                "SELECT is_default FROM accounts WHERE id=? AND telegram_id=?",
                (account_id, telegram_id),
            ).fetchone()
            if row is None:
                return False
            self.conn.execute(
                "DELETE FROM accounts WHERE id=? AND telegram_id=?",
                (account_id, telegram_id),
            )
            if row["is_default"]:
                self._promote_a_default(telegram_id)
        return True

    def _promote_a_default(self, telegram_id):
        """Never leave a user with accounts but no default."""
        survivor = self.conn.execute(
            "SELECT id FROM accounts WHERE telegram_id=? ORDER BY LOWER(label)"
            " LIMIT 1",
            (telegram_id,),
        ).fetchone()
        if survivor:
            self.conn.execute(
                "UPDATE accounts SET is_default=1 WHERE id=?", (survivor["id"],)
            )

    def rename(self, account_id, telegram_id, label):
        with self.conn:
            cur = self.conn.execute(
                "UPDATE accounts SET label=? WHERE id=? AND telegram_id=?",
                (label, account_id, telegram_id),
            )
        return cur.rowcount > 0

    def set_default(self, account_id, telegram_id):
        with self.conn:
            owned = self.conn.execute(
                "SELECT 1 FROM accounts WHERE id=? AND telegram_id=?",
                (account_id, telegram_id),
            ).fetchone()
            if owned is None:
                return False
            self.conn.execute(
                "UPDATE accounts SET is_default=0 WHERE telegram_id=?",
                (telegram_id,),
            )
            self.conn.execute(
                "UPDATE accounts SET is_default=1 WHERE id=?", (account_id,)
            )
        return True

    def update_cookie(self, account_id, enc_cookie):
        with self.conn:
            self.conn.execute(
                "UPDATE accounts SET enc_cookie=?, last_used=? WHERE id=?",
                (enc_cookie, time.time(), account_id),
            )

    def update_identity(self, account_id, puuid, riot_name, riot_tag):
        with self.conn:
            self.conn.execute(
                "UPDATE accounts SET puuid=?, riot_name=?, riot_tag=? WHERE id=?",
                (puuid, riot_name, riot_tag, account_id),
            )
