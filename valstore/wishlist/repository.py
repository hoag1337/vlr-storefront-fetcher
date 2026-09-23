"""Wishlist persistence.

Two tables, two different lifetimes. wishlist_items is what the person asked
for: it has no foreign key to accounts, because a wishlist is a standing
preference of the Telegram user, not of one linked session — it must survive
removing and re-linking an account. shop_seen is the opposite: purely dedup
state for one account's last poll, meaningless once that account is gone, so
it cascades with it.
"""

import logging
import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path

from valstore.wishlist.models import WishlistItem

log = logging.getLogger("valstore.wishlist.repository")

_DDL = """
CREATE TABLE IF NOT EXISTS wishlist_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER NOT NULL,
    skin_uuid   TEXT    NOT NULL,
    added_at    REAL    NOT NULL,
    UNIQUE(telegram_id, skin_uuid)
);

CREATE INDEX IF NOT EXISTS idx_wishlist_owner ON wishlist_items(telegram_id);

CREATE TABLE IF NOT EXISTS shop_seen (
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    source     TEXT    NOT NULL,
    skin_uuid  TEXT    NOT NULL,
    PRIMARY KEY (account_id, source, skin_uuid)
);
"""

_COLUMNS = "id, telegram_id, skin_uuid, added_at"


class WishlistRepository(ABC):
    """Storage contract for wishlists and the watcher's dedup state."""

    @abstractmethod
    def list_for(self, telegram_id: int) -> list[WishlistItem]:
        """Every skin this user has wishlisted, most recently added first."""

    @abstractmethod
    def skin_uuids_for(self, telegram_id: int) -> set[str]:
        """Convenience for the watcher: just the uuids, as a set to intersect."""

    @abstractmethod
    def add(self, telegram_id: int, skin_uuid: str) -> tuple[WishlistItem, bool]:
        """Insert, or return the existing row if it's already wishlisted.

        Returns (item, was_new) so callers can tell a fresh add from a no-op.
        """

    @abstractmethod
    def remove(self, item_id: int, telegram_id: int) -> bool:
        """Delete one item, scoped to its owner so an id alone grants nothing."""

    @abstractmethod
    def count_for(self, telegram_id: int) -> int:
        """How many skins this user holds, for the per-user cap."""

    @abstractmethod
    def list_telegram_ids_with_items(self) -> list[int]:
        """Everyone the watcher needs to check — skips anyone with an empty list."""

    @abstractmethod
    def previously_seen(self, account_id: int, source: str) -> set[str]:
        """Wishlist uuids that matched this account+source on the last poll."""

    @abstractmethod
    def mark_seen(self, account_id: int, source: str, skin_uuids: set[str]) -> None:
        """Replace the dedup state for this account+source with this poll's matches."""


class SqliteWishlistRepository(WishlistRepository):
    """SQLite implementation. Event-loop thread only, same as SqliteAccountRepository."""

    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        with self.conn:
            self.conn.executescript(_DDL)

    # ---- wishlist_items ----

    def _row_to_item(self, row: sqlite3.Row) -> WishlistItem:
        return WishlistItem(
            id=row["id"],
            telegram_id=row["telegram_id"],
            skin_uuid=row["skin_uuid"],
            added_at=row["added_at"],
        )

    def list_for(self, telegram_id):
        rows = self.conn.execute(
            f"SELECT {_COLUMNS} FROM wishlist_items WHERE telegram_id=?"
            " ORDER BY added_at DESC",
            (telegram_id,),
        ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def skin_uuids_for(self, telegram_id):
        rows = self.conn.execute(
            "SELECT skin_uuid FROM wishlist_items WHERE telegram_id=?",
            (telegram_id,),
        ).fetchall()
        return {r["skin_uuid"] for r in rows}

    def add(self, telegram_id, skin_uuid):
        now = time.time()
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO wishlist_items (telegram_id, skin_uuid, added_at)"
                " VALUES (?, ?, ?) ON CONFLICT(telegram_id, skin_uuid) DO NOTHING",
                (telegram_id, skin_uuid, now),
            )
            was_new = cur.rowcount > 0
        row = self.conn.execute(
            f"SELECT {_COLUMNS} FROM wishlist_items"
            " WHERE telegram_id=? AND skin_uuid=?",
            (telegram_id, skin_uuid),
        ).fetchone()
        if row is None:  # pragma: no cover - insert or the row already existed
            raise RuntimeError("Wishlist item vanished immediately after insert")
        return self._row_to_item(row), was_new

    def remove(self, item_id, telegram_id):
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM wishlist_items WHERE id=? AND telegram_id=?",
                (item_id, telegram_id),
            )
        return cur.rowcount > 0

    def count_for(self, telegram_id):
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM wishlist_items WHERE telegram_id=?",
            (telegram_id,),
        ).fetchone()
        return row["n"] if row else 0

    def list_telegram_ids_with_items(self):
        rows = self.conn.execute(
            "SELECT DISTINCT telegram_id FROM wishlist_items"
        ).fetchall()
        return [r["telegram_id"] for r in rows]

    # ---- shop_seen ----

    def previously_seen(self, account_id, source):
        rows = self.conn.execute(
            "SELECT skin_uuid FROM shop_seen WHERE account_id=? AND source=?",
            (account_id, source),
        ).fetchall()
        return {r["skin_uuid"] for r in rows}

    def mark_seen(self, account_id, source, skin_uuids):
        with self.conn:
            self.conn.execute(
                "DELETE FROM shop_seen WHERE account_id=? AND source=?",
                (account_id, source),
            )
            self.conn.executemany(
                "INSERT INTO shop_seen (account_id, source, skin_uuid)"
                " VALUES (?, ?, ?)",
                [(account_id, source, uuid) for uuid in skin_uuids],
            )
