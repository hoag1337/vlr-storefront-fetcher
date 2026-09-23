"""WishlistWatcher: the core promise — notify once on a new match, not on
every poll while it's still there, and again once it comes back."""

import unittest
from unittest.mock import patch

from valstore.models import Account
from valstore.riot.session import RiotSession
from valstore.wishlist.watcher import WishlistWatcher


class _Map:
    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, uuid, default=None):
        if not uuid:
            return default
        return self._mapping.get(uuid, default)


class _FakeWishlistRepo:
    def __init__(self, wishlists=None):
        self._wishlists = wishlists or {}
        self._seen = {}

    def list_telegram_ids_with_items(self):
        return [tid for tid, uuids in self._wishlists.items() if uuids]

    def skin_uuids_for(self, telegram_id):
        return set(self._wishlists.get(telegram_id, set()))

    def previously_seen(self, account_id, source):
        return set(self._seen.get((account_id, source), set()))

    def mark_seen(self, account_id, source, skin_uuids):
        self._seen[(account_id, source)] = set(skin_uuids)


class _FakeAccountRepo:
    def __init__(self, accounts):
        self._accounts = accounts
        self.updated_cookies = []

    def list_for(self, telegram_id):
        return [a for a in self._accounts if a.telegram_id == telegram_id]

    def update_cookie(self, account_id, enc_cookie):
        self.updated_cookies.append((account_id, enc_cookie))


class _FakeAccountsService:
    def decrypt_cookie(self, account):
        return f"cookie-for-{account.id}"

    def encrypt_cookie(self, cookie_header):
        return f"enc({cookie_header})".encode()


class _FakeCatalogs:
    def __init__(self):
        self.skin_levels = _Map({"lvl-a": {"skin": "Reaver Vandal",
                                           "skin_uuid": "skin-a"}})

    def skin_uuid_to_name(self):
        return {"skin-a": "Reaver Vandal"}


class _FakeNotifier:
    def __init__(self):
        self.sent = []

    async def notify(self, telegram_id, text):
        self.sent.append((telegram_id, text))


def _account(account_id, telegram_id, shard="ap"):
    return Account(id=account_id, telegram_id=telegram_id, label=f"Acct{account_id}",
                   shard=shard, enc_cookie=b"enc", is_default=True, linked_at=0.0)


def _store_with(skin_level_id):
    return {"SkinsPanelLayout": {"SingleItemStoreOffers": [
        {"Rewards": [{"ItemID": skin_level_id}]}
    ]}}


_EMPTY_STORE = {"SkinsPanelLayout": {"SingleItemStoreOffers": []}}


class WishlistWatcherTest(unittest.IsolatedAsyncioTestCase):
    def _watcher(self, wishlists, accounts):
        self.wishlist_repo = _FakeWishlistRepo(wishlists)
        self.account_repo = _FakeAccountRepo(accounts)
        self.notifier = _FakeNotifier()
        return WishlistWatcher(
            self.wishlist_repo, self.account_repo, _FakeAccountsService(),
            _FakeCatalogs(), self.notifier, poll_interval_seconds=86400,
        )

    async def test_a_user_with_no_wishlist_is_never_fetched(self):
        watcher = self._watcher({1: set()}, [_account(1, 1)])
        with patch("valstore.wishlist.watcher.open_session") as fake_open:
            await watcher.check_all()
        fake_open.assert_not_called()

    async def test_new_match_notifies_once(self):
        watcher = self._watcher({1: {"skin-a"}}, [_account(1, 1)])
        session = RiotSession(access_token="t", puuid="p",
                              entitlements_token="e", client_version="v")
        with patch("valstore.wishlist.watcher.open_session", return_value=session), \
             patch("valstore.wishlist.watcher.riot_store.get_storefront",
                   return_value=_store_with("lvl-a")):
            await watcher.check_user(1)

        self.assertEqual(len(self.notifier.sent), 1)
        telegram_id, text = self.notifier.sent[0]
        self.assertEqual(telegram_id, 1)
        self.assertIn("Reaver Vandal", text)

    async def test_the_same_match_does_not_notify_twice(self):
        watcher = self._watcher({1: {"skin-a"}}, [_account(1, 1)])
        session = RiotSession(access_token="t", puuid="p",
                              entitlements_token="e", client_version="v")
        with patch("valstore.wishlist.watcher.open_session", return_value=session), \
             patch("valstore.wishlist.watcher.riot_store.get_storefront",
                   return_value=_store_with("lvl-a")):
            await watcher.check_user(1)
            await watcher.check_user(1)

        self.assertEqual(len(self.notifier.sent), 1)

    async def test_a_match_that_disappears_then_returns_notifies_again(self):
        watcher = self._watcher({1: {"skin-a"}}, [_account(1, 1)])
        session = RiotSession(access_token="t", puuid="p",
                              entitlements_token="e", client_version="v")
        with patch("valstore.wishlist.watcher.open_session", return_value=session):
            with patch("valstore.wishlist.watcher.riot_store.get_storefront",
                      return_value=_store_with("lvl-a")):
                await watcher.check_user(1)
            with patch("valstore.wishlist.watcher.riot_store.get_storefront",
                      return_value=_EMPTY_STORE):
                await watcher.check_user(1)
            with patch("valstore.wishlist.watcher.riot_store.get_storefront",
                      return_value=_store_with("lvl-a")):
                await watcher.check_user(1)

        self.assertEqual(len(self.notifier.sent), 2)

    async def test_a_user_with_two_accounts_is_checked_against_both(self):
        watcher = self._watcher({1: {"skin-a"}},
                                [_account(1, 1), _account(2, 1)])
        session = RiotSession(access_token="t", puuid="p",
                              entitlements_token="e", client_version="v")
        with patch("valstore.wishlist.watcher.open_session", return_value=session), \
             patch("valstore.wishlist.watcher.riot_store.get_storefront",
                   return_value=_store_with("lvl-a")):
            await watcher.check_user(1)

        self.assertEqual(len(self.notifier.sent), 2)
        # Two accounts on one wishlist: the notification should say which is which.
        self.assertTrue(any("Acct1" in text for _tid, text in self.notifier.sent))
        self.assertTrue(any("Acct2" in text for _tid, text in self.notifier.sent))

    async def test_a_broken_account_does_not_stop_the_cycle(self):
        watcher = self._watcher(
            {1: {"skin-a"}, 2: {"skin-a"}},
            [_account(1, 1), _account(2, 2, shard="broken")],
        )
        session = RiotSession(access_token="t", puuid="p",
                              entitlements_token="e", client_version="v")

        def fake_get_storefront(shard, *args, **kwargs):
            if shard == "broken":
                raise RuntimeError("Riot is down")
            return _store_with("lvl-a")

        with patch("valstore.wishlist.watcher.open_session", return_value=session), \
             patch("valstore.wishlist.watcher.riot_store.get_storefront",
                   side_effect=fake_get_storefront):
            await watcher.check_all()

        self.assertEqual(len(self.notifier.sent), 1)
        self.assertEqual(self.notifier.sent[0][0], 1)
