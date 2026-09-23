"""Storage: legacy migration, and the invariants the account list depends on."""

import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from valstore.repository import SqliteAccountRepository


def _legacy_db(path, rows):
    """A database shaped like the pre-refactor one."""
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE users (
               telegram_id INTEGER PRIMARY KEY,
               enc_cookie  BLOB NOT NULL,
               shard       TEXT NOT NULL,
               linked_at   REAL NOT NULL,
               last_used   REAL
           )"""
    )
    conn.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?)", rows)
    conn.commit()
    conn.close()


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self._dir.name) / "valstore.db")

    def tearDown(self):
        self._dir.cleanup()

    def test_legacy_rows_become_default_accounts(self):
        _legacy_db(self.path, [(111, b"enc-a", "ap", time.time(), None),
                               (222, b"enc-b", "eu", time.time(), None)])

        repo = SqliteAccountRepository(self.path)

        first = repo.get_default(111)
        self.assertIsNotNone(first)
        self.assertEqual(first.shard, "ap")
        self.assertEqual(first.enc_cookie, b"enc-a")
        self.assertTrue(first.is_default)
        self.assertEqual(repo.get_default(222).shard, "eu")

    def test_old_table_is_kept_not_dropped(self):
        _legacy_db(self.path, [(111, b"enc", "ap", time.time(), None)])
        repo = SqliteAccountRepository(self.path)
        self.assertTrue(repo._table_exists("users_legacy"))
        self.assertFalse(repo._table_exists("users"))

    def test_migration_is_idempotent(self):
        _legacy_db(self.path, [(111, b"enc", "ap", time.time(), None)])
        SqliteAccountRepository(self.path)
        repo = SqliteAccountRepository(self.path)  # reopen, must not duplicate
        self.assertEqual(repo.count_for(111), 1)

    def test_fresh_database_needs_no_legacy_table(self):
        repo = SqliteAccountRepository(self.path)
        self.assertEqual(repo.count_for(111), 0)


class AccountInvariantsTest(unittest.TestCase):
    def setUp(self):
        self.repo = SqliteAccountRepository(":memory:")

    def _add(self, label, telegram_id=1, puuid=None):
        return self.repo.add(telegram_id, label, "ap", b"enc", puuid=puuid)

    def test_first_account_becomes_default(self):
        account = self._add("Main")
        self.assertTrue(account.is_default)

    def test_second_account_does_not_steal_default(self):
        self._add("Main", puuid="p1")
        second = self._add("Smurf", puuid="p2")
        self.assertFalse(second.is_default)

    def test_removing_the_default_promotes_a_survivor(self):
        first = self._add("Main", puuid="p1")
        self._add("Smurf", puuid="p2")

        self.repo.remove(first.id, 1)

        remaining = self.repo.get_default(1)
        self.assertEqual(remaining.label, "Smurf")
        self.assertTrue(remaining.is_default)

    def test_set_default_is_exclusive(self):
        first = self._add("Main", puuid="p1")
        second = self._add("Smurf", puuid="p2")

        self.repo.set_default(second.id, 1)

        defaults = [a.label for a in self.repo.list_for(1) if a.is_default]
        self.assertEqual(defaults, ["Smurf"])
        self.assertFalse(self.repo.get(first.id, 1).is_default)

    def test_an_account_id_alone_grants_nothing(self):
        """Ownership is checked on every read and write, not just on listing."""
        account = self._add("Main", telegram_id=1)
        stranger = 999

        self.assertIsNone(self.repo.get(account.id, stranger))
        self.assertFalse(self.repo.remove(account.id, stranger))
        self.assertFalse(self.repo.rename(account.id, stranger, "Pwned"))
        self.assertFalse(self.repo.set_default(account.id, stranger))
        self.assertEqual(self.repo.get(account.id, 1).label, "Main")

    def test_default_listed_first(self):
        self._add("Zeta", puuid="p1")
        second = self._add("Alpha", puuid="p2")
        self.repo.set_default(second.id, 1)
        self.assertEqual([a.label for a in self.repo.list_for(1)],
                         ["Alpha", "Zeta"])

    def test_find_by_puuid_scoped_to_owner(self):
        self._add("Main", telegram_id=1, puuid="shared")
        self.assertIsNotNone(self.repo.find_by_puuid(1, "shared"))
        self.assertIsNone(self.repo.find_by_puuid(2, "shared"))
