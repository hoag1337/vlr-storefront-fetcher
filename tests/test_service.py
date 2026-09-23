"""Account lifecycle and the guards on an openly-reachable bot."""

import unittest

from valstore import crypto
from valstore.errors import (
    AccountLimitReached,
    AccountNotFound,
    RateLimited,
    SessionDecryptError,
)
from valstore.models import LinkResult, RiotIdentity
from valstore.repository import SqliteAccountRepository
from valstore.service import AccountService, LinkGuard


def _result(cookie="ssid=abc", shard="ap", puuid="p1", name="Player", tag="NA1"):
    identity = RiotIdentity(puuid=puuid, game_name=name, tag_line=tag) if puuid else None
    return LinkResult(cookie_header=cookie, shard=shard, identity=identity)


class AccountServiceTest(unittest.TestCase):
    def setUp(self):
        self.key = crypto.generate_fernet_key().encode()
        self.repo = SqliteAccountRepository(":memory:")
        self.service = AccountService(self.repo, self.key, max_per_user=3)

    def test_link_names_the_account_after_the_riot_handle(self):
        account, relinked = self.service.link(1, _result())
        self.assertFalse(relinked)
        self.assertEqual(account.label, "Player#NA1")
        self.assertEqual(account.riot_handle, "Player#NA1")

    def test_cookie_is_encrypted_at_rest(self):
        account, _ = self.service.link(1, _result(cookie="ssid=secret"))
        self.assertNotIn(b"secret", account.enc_cookie)
        self.assertEqual(self.service.decrypt_cookie(account), "ssid=secret")

    def test_relinking_the_same_riot_account_refreshes_in_place(self):
        self.service.link(1, _result(cookie="ssid=old"))
        account, relinked = self.service.link(1, _result(cookie="ssid=new"))

        self.assertTrue(relinked)
        self.assertEqual(self.service.count(1), 1)
        self.assertEqual(self.service.decrypt_cookie(account), "ssid=new")

    def test_different_riot_accounts_coexist(self):
        self.service.link(1, _result(puuid="p1", name="Main"))
        self.service.link(1, _result(puuid="p2", name="Alt"))
        self.assertEqual(self.service.count(1), 2)

    def test_accounts_are_per_telegram_user(self):
        self.service.link(1, _result(puuid="p1"))
        self.assertEqual(self.service.count(2), 0)

    def test_capacity_is_enforced(self):
        for n in range(3):
            self.service.link(1, _result(puuid=f"p{n}"))
        self.assertTrue(self.service.at_capacity(1))
        self.assertFalse(self.service.at_capacity(2))

    def test_a_new_account_past_the_cap_is_refused(self):
        for n in range(3):
            self.service.link(1, _result(puuid=f"p{n}"))
        with self.assertRaises(AccountLimitReached):
            self.service.link(1, _result(puuid="one-too-many"))

    def test_at_the_cap_an_expired_account_can_still_be_refreshed(self):
        """The common failure is an expired session, not a hoarded account —
        being full must not strand someone with no way to re-link."""
        for n in range(3):
            self.service.link(1, _result(puuid=f"p{n}", cookie="ssid=old"))
        self.assertTrue(self.service.at_capacity(1))

        account, relinked = self.service.link(1, _result(puuid="p1",
                                                         cookie="ssid=fresh"))

        self.assertTrue(relinked)
        self.assertEqual(self.service.count(1), 3)
        self.assertEqual(self.service.decrypt_cookie(account), "ssid=fresh")

    def test_sessions_without_identity_still_link(self):
        """A method that cannot name the account must not be blocked by that."""
        account, _ = self.service.link(1, _result(puuid=None))
        self.assertEqual(account.label, "New account")
        self.assertIsNone(account.puuid)

    def test_resolve_target_prefers_the_default(self):
        self.service.link(1, _result(puuid="p1", name="Main"))
        second, _ = self.service.link(1, _result(puuid="p2", name="Alt"))
        self.service.set_default(second.id, 1)
        self.assertEqual(self.service.resolve_target(1).id, second.id)

    def test_resolve_target_without_accounts_is_an_error(self):
        with self.assertRaises(AccountNotFound):
            self.service.resolve_target(1)

    def test_rename_rejects_blank_and_trims(self):
        account, _ = self.service.link(1, _result())
        self.assertFalse(self.service.rename(account.id, 1, "   "))
        self.assertTrue(self.service.rename(account.id, 1, "  Main  "))
        self.assertEqual(self.service.require(account.id, 1).label, "Main")

    def test_a_changed_key_is_reported_not_crashed(self):
        account, _ = self.service.link(1, _result())
        other = AccountService(self.repo, crypto.generate_fernet_key().encode(), 3)
        with self.assertRaises(SessionDecryptError):
            other.decrypt_cookie(account)

    def test_removed_account_is_gone(self):
        account, _ = self.service.link(1, _result())
        self.assertTrue(self.service.remove(account.id, 1))
        with self.assertRaises(AccountNotFound):
            self.service.require(account.id, 1)


class LinkGuardTest(unittest.TestCase):
    def test_per_user_limit(self):
        guard = LinkGuard(per_user_per_hour=2, global_per_hour=100)
        for _ in range(2):
            guard.check(1)
            guard.record(1)
        with self.assertRaises(RateLimited):
            guard.check(1)

    def test_one_user_cannot_exhaust_another(self):
        guard = LinkGuard(per_user_per_hour=1, global_per_hour=100)
        guard.check(1)
        guard.record(1)
        guard.check(2)  # must not raise

    def test_global_limit_applies_across_users(self):
        guard = LinkGuard(per_user_per_hour=50, global_per_hour=3)
        for user in range(3):
            guard.check(user)
            guard.record(user)
        with self.assertRaises(RateLimited):
            guard.check(99)

    def test_rate_limit_reports_a_usable_wait(self):
        guard = LinkGuard(per_user_per_hour=1, global_per_hour=100)
        guard.check(1)
        guard.record(1)
        with self.assertRaises(RateLimited) as caught:
            guard.check(1)
        self.assertGreater(caught.exception.retry_after_seconds, 0)
        self.assertLessEqual(caught.exception.retry_after_seconds, 3601)
