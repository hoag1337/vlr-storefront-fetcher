"""Application services: the only place handlers mutate anything.

AccountService owns the account lifecycle, CommandExecutor owns running a
command against one account, and LinkGuard is the safety net that keeps an
openly-reachable bot from being useful as a credential-testing oracle.
"""

import asyncio
import logging
import time
from collections import deque

from valstore import crypto
from valstore.errors import (
    AccountLimitReached,
    AccountNotFound,
    RateLimited,
    SessionDecryptError,
)
from valstore.models import Account, LinkResult

log = logging.getLogger("valstore.service")

_ONE_HOUR = 3600


class LinkGuard:
    """Rate limits link attempts, and carries the owner's kill switch.

    The bot is reachable by anyone, and a link attempt is the one operation that
    consumes Riot's auth endpoint on a stranger's behalf. Capping it per user and
    globally keeps the bot from being turned into a credential checker, and the
    kill switch is the lever if it is ever found and abused.
    """

    def __init__(self, per_user_per_hour: int, global_per_hour: int):
        self._per_user = per_user_per_hour
        self._global = global_per_hour
        self._by_user: dict[int, deque[float]] = {}
        self._all: deque[float] = deque()
        self.enabled = True

    @staticmethod
    def _prune(stamps: deque, now: float) -> None:
        while stamps and now - stamps[0] >= _ONE_HOUR:
            stamps.popleft()

    def check(self, telegram_id: int) -> None:
        """Raise RateLimited if this attempt should not proceed."""
        now = time.time()

        self._prune(self._all, now)
        if len(self._all) >= self._global:
            raise RateLimited(int(_ONE_HOUR - (now - self._all[0])) + 1)

        stamps = self._by_user.setdefault(telegram_id, deque())
        self._prune(stamps, now)
        if len(stamps) >= self._per_user:
            raise RateLimited(int(_ONE_HOUR - (now - stamps[0])) + 1)

    def record(self, telegram_id: int) -> None:
        """Count an attempt. Called for failures too — that is the point."""
        now = time.time()
        self._all.append(now)
        self._by_user.setdefault(telegram_id, deque()).append(now)


class AccountService:
    """Add, remove, rename and re-link accounts while the bot runs."""

    def __init__(self, repository, at_rest_key: bytes, max_per_user: int):
        self._repo = repository
        self._key = at_rest_key
        self._max_per_user = max_per_user

    # ---- reads ----

    def list_accounts(self, telegram_id) -> list[Account]:
        return self._repo.list_for(telegram_id)

    def count(self, telegram_id) -> int:
        return self._repo.count_for(telegram_id)

    def require(self, account_id, telegram_id) -> Account:
        account = self._repo.get(account_id, telegram_id)
        if account is None:
            raise AccountNotFound("That account is no longer linked.")
        return account

    def resolve_target(self, telegram_id, account_id=None) -> Account:
        """The account a command should act on."""
        if account_id is not None:
            return self.require(account_id, telegram_id)
        account = self._repo.get_default(telegram_id)
        if account is None:
            raise AccountNotFound("You have no linked accounts yet.")
        return account

    def at_capacity(self, telegram_id) -> bool:
        return self._repo.count_for(telegram_id) >= self._max_per_user

    @property
    def max_per_user(self) -> int:
        return self._max_per_user

    # ---- writes ----

    def link(self, telegram_id: int, result: LinkResult,
             label: str | None = None) -> tuple[Account, bool]:
        """Store a validated session.

        Returns (account, was_relink). Re-linking an account the user already
        holds refreshes it in place instead of creating a duplicate — which is
        what someone whose session expired actually means to do.

        Raises AccountLimitReached only when this would be an additional
        account, so someone at the cap can still refresh what they have.
        """
        enc = self.encrypt_cookie(result.cookie_header)
        identity = result.identity
        puuid = identity.puuid if identity else None

        existing = self._repo.find_by_puuid(telegram_id, puuid) if puuid else None
        if existing is not None:
            self._repo.update_cookie(existing.id, enc)
            if identity:
                self._repo.update_identity(existing.id, identity.puuid,
                                           identity.game_name, identity.tag_line)
            refreshed = self._repo.get(existing.id, telegram_id) or existing
            return refreshed, True

        if self.at_capacity(telegram_id):
            raise AccountLimitReached(
                f"You've reached the limit of {self._max_per_user} linked "
                "accounts. Remove one first and you can link another."
            )

        account = self._repo.add(
            telegram_id=telegram_id,
            label=(label or result.suggested_label).strip()[:64],
            shard=result.shard,
            enc_cookie=enc,
            puuid=puuid,
            riot_name=identity.game_name if identity else None,
            riot_tag=identity.tag_line if identity else None,
        )
        return account, False

    def remove(self, account_id, telegram_id) -> bool:
        return self._repo.remove(account_id, telegram_id)

    def rename(self, account_id, telegram_id, label) -> bool:
        cleaned = label.strip()[:64]
        if not cleaned:
            return False
        return self._repo.rename(account_id, telegram_id, cleaned)

    def set_default(self, account_id, telegram_id) -> bool:
        return self._repo.set_default(account_id, telegram_id)

    # ---- session material ----

    def encrypt_cookie(self, cookie_header: str) -> bytes:
        return crypto.encrypt_at_rest(self._key, cookie_header)

    def decrypt_cookie(self, account: Account) -> str:
        try:
            return crypto.decrypt_at_rest(self._key, account.enc_cookie)
        except Exception as exc:
            # Almost always a changed AT_REST_KEY; the stored blob is unusable.
            log.warning("at-rest decryption failed for account %s", account.id)
            raise SessionDecryptError(
                "That account's stored session could not be decrypted."
            ) from exc


class CommandExecutor:
    """Runs an AccountCommand off the event loop and persists what it learned."""

    def __init__(self, accounts: AccountService, repository):
        self._accounts = accounts
        self._repo = repository

    async def execute(self, account: Account, command) -> list[str]:
        """Messages for the user. Riot errors propagate for handlers to phrase."""
        cookie_header = self._accounts.decrypt_cookie(account)

        outcome = await asyncio.to_thread(command.run, cookie_header, account.shard)

        if outcome.rotated_cookie:
            self._repo.update_cookie(
                account.id,
                self._accounts.encrypt_cookie(outcome.rotated_cookie),
            )
        if outcome.puuid and not account.puuid:
            # Backfill so legacy migrated rows gain an identity on first use.
            self._repo.update_identity(account.id, outcome.puuid,
                                       account.riot_name, account.riot_tag)
        return outcome.messages
