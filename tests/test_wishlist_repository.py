"""Wishlist storage: independence from accounts, and the dedup state."""

import tempfile
import unittest
from pathlib import Path

from valstore.repository import SqliteAccountRepository
from valstore.wishlist.repository import SqliteWishlistRepository


class WishlistItemsTest(unittest.TestCase):
    def setUp(self):
        self.repo = SqliteWishlistRepository(":memory:")

    def test_add_then_list(self):
        self.repo.add(1, "skin-a")
        self.repo.add(1, "skin-b")
        uuids = {item.skin_uuid for item in self.repo.list_for(1)}
        self.assertEqual(uuids, {"skin-a", "skin-b"})

    def test_wishlists_are_per_telegram_user(self):
        self.repo.add(1, "skin-a")
        self.assertEqual(self.repo.list_for(2), [])

    def test_adding_the_same_skin_twice_is_a_no_op(self):
        _first, first_new = self.repo.add(1, "skin-a")
        _second, second_new = self.repo.add(1, "skin-a")
        self.assertTrue(first_new)
        self.assertFalse(second_new)
        self.assertEqual(self.repo.count_for(1), 1)

    def test_remove_is_scoped_to_its_owner(self):
        item, _ = self.repo.add(1, "skin-a")
        self.assertFalse(self.repo.remove(item.id, 2))
        self.assertTrue(self.repo.remove(item.id, 1))
        self.assertEqual(self.repo.count_for(1), 0)

    def test_list_telegram_ids_with_items_skips_empty_wishlists(self):
        self.repo.add(1, "skin-a")
        self.assertEqual(self.repo.list_telegram_ids_with_items(), [1])


class ShopSeenTest(unittest.TestCase):
    def setUp(self):
        # shop_seen references accounts(id): both tables must live in the same
        # file for the foreign key to resolve, so this suite uses a temp file
        # instead of two independent :memory: connections.
        self._dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self._dir.name) / "valstore.db")
        self.accounts = SqliteAccountRepository(self.path)
        self.repo = SqliteWishlistRepository(self.path)

    def tearDown(self):
        self._dir.cleanup()

    def _account_id(self):
        account = self.accounts.add(
            telegram_id=1, label="Main", shard="ap", enc_cookie=b"enc",
        )
        return account.id

    def test_previously_seen_is_empty_before_any_poll(self):
        account_id = self._account_id()
        self.assertEqual(self.repo.previously_seen(account_id, "daily"), set())

    def test_mark_seen_replaces_the_prior_set(self):
        account_id = self._account_id()
        self.repo.mark_seen(account_id, "daily", {"skin-a", "skin-b"})
        self.assertEqual(self.repo.previously_seen(account_id, "daily"),
                         {"skin-a", "skin-b"})

        self.repo.mark_seen(account_id, "daily", {"skin-b"})
        self.assertEqual(self.repo.previously_seen(account_id, "daily"),
                         {"skin-b"})

    def test_sources_are_independent(self):
        account_id = self._account_id()
        self.repo.mark_seen(account_id, "daily", {"skin-a"})
        self.repo.mark_seen(account_id, "bundle", {"skin-b"})
        self.assertEqual(self.repo.previously_seen(account_id, "daily"),
                         {"skin-a"})
        self.assertEqual(self.repo.previously_seen(account_id, "bundle"),
                         {"skin-b"})

    def test_shop_seen_cascades_when_the_account_is_removed(self):
        account_id = self._account_id()
        self.repo.mark_seen(account_id, "daily", {"skin-a"})
        self.accounts.remove(account_id, 1)
        self.assertEqual(self.repo.previously_seen(account_id, "daily"), set())

    def test_wishlist_items_survive_removing_every_account(self):
        """No FK to accounts: a wishlist is a preference of the person, not of
        one linked session, so it must outlive removing every account."""
        account_id = self._account_id()
        self.repo.add(1, "skin-a")
        self.accounts.remove(account_id, 1)
        self.assertEqual(self.accounts.count_for(1), 0)
        self.assertEqual(self.repo.skin_uuids_for(1), {"skin-a"})
