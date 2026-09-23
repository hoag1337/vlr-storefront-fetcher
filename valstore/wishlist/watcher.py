"""The background loop: poll every account with a wishlist, notify on new hits.

Nothing here is Telegram-specific except the final send (behind
WishlistNotifier) and nothing here is aiogram-specific at all, so the polling
logic is testable with fakes for every collaborator.
"""

import asyncio
import logging

from valstore.riot import store as riot_store
from valstore.riot.session import open_session
from valstore.wishlist.matching import BUNDLE, DAILY, NIGHT_MARKET, StorefrontSkins

log = logging.getLogger("valstore.wishlist.watcher")

_SOURCE_LABEL = {
    DAILY: "today's daily shop",
    NIGHT_MARKET: "the Night Market",
    BUNDLE: "a featured bundle",
}


class WishlistWatcher:
    """A daily background sweep, plus check_user() for an immediate, one-off
    check right after someone changes their wishlist.

    The shop, Night Market and bundles all rotate at most once a day, so
    polling faster than that only spends Riot API calls for no benefit — the
    sweep exists to catch a rotation the user wasn't around to trigger
    check_user() for, not to shrink notification latency.
    """

    def __init__(self, wishlist_repo, account_repo, accounts_service, catalogs,
                notifier, poll_interval_seconds):
        self._wishlist_repo = wishlist_repo
        self._account_repo = account_repo
        self._accounts = accounts_service
        self._catalogs = catalogs
        self._extractor = StorefrontSkins(catalogs.skin_levels)
        self._notifier = notifier
        self._interval = poll_interval_seconds

    async def run_forever(self) -> None:
        while True:
            try:
                await self.check_all()
            except Exception:
                # A bug in the cycle itself must not end background checking
                # for good — the next iteration gets another chance.
                log.exception("wishlist poll cycle failed")
            await asyncio.sleep(self._interval)

    async def check_all(self) -> None:
        """Every user with a wishlist item, against every account they've linked."""
        for telegram_id in self._wishlist_repo.list_telegram_ids_with_items():
            try:
                await self.check_user(telegram_id)
            except Exception:
                log.exception("wishlist check failed for user %s", telegram_id)

    async def check_user(self, telegram_id: int) -> None:
        """One user's wishlist against every account they've linked.

        Called by the daily sweep, and directly by the handler right after
        an add — so a skin that's already live gets flagged immediately
        instead of waiting for the next scheduled sweep.
        """
        wishlist_uuids = self._wishlist_repo.skin_uuids_for(telegram_id)
        if not wishlist_uuids:
            return
        accounts = self._account_repo.list_for(telegram_id)
        announce_account = len(accounts) > 1
        for account in accounts:
            try:
                await self._check_account(account, wishlist_uuids,
                                          announce_account)
            except Exception:
                log.exception("wishlist check failed for account %s", account.id)

    async def _check_account(self, account, wishlist_uuids, announce_account):
        try:
            cookie_header = self._accounts.decrypt_cookie(account)
            session, store = await asyncio.to_thread(
                self._fetch, cookie_header, account.shard
            )
        except Exception as exc:
            # Riot/network failures (expired session, Cloudflare, an outage)
            # are expected here — this is a silent background poll, not a
            # user action, so it logs and waits for the next cycle rather
            # than paging anyone.
            log.info("wishlist fetch skipped for account %s: %s", account.id, exc)
            return

        if session.rotated_cookie:
            self._account_repo.update_cookie(
                account.id, self._accounts.encrypt_cookie(session.rotated_cookie)
            )

        for source, current in self._extractor.all_sources(store).items():
            matches = current & wishlist_uuids
            previous = self._wishlist_repo.previously_seen(account.id, source)
            new_hits = matches - previous
            if new_hits:
                await self._notify(account, source, new_hits, announce_account)
            self._wishlist_repo.mark_seen(account.id, source, matches)

    @staticmethod
    def _fetch(cookie_header, shard):
        session = open_session(cookie_header)
        store = riot_store.get_storefront(
            shard, session.puuid, session.access_token,
            session.entitlements_token, session.client_version,
        )
        return session, store

    async def _notify(self, account, source, skin_uuids, announce_account):
        names_by_uuid = self._catalogs.skin_uuid_to_name()
        names = sorted(names_by_uuid.get(u, "Unknown skin") for u in skin_uuids)

        header = f"🎯 Wishlist match — {_SOURCE_LABEL[source]}!"
        if announce_account:
            header += f" ({account.title})"
        lines = [header] + [f"• {name}" for name in names] + [
            "\nCheck /store for prices."
        ]
        await self._notifier.notify(account.telegram_id, "\n".join(lines))
