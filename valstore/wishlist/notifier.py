"""Pushing an unsolicited message to a Telegram chat.

Behind an interface so the watcher's polling loop can be tested with a fake
that just records calls, never touching aiogram or the network.
"""

import logging
from abc import ABC, abstractmethod

log = logging.getLogger("valstore.wishlist.notifier")


class WishlistNotifier(ABC):
    """One outbound message to one Telegram user."""

    @abstractmethod
    async def notify(self, telegram_id: int, text: str) -> None:
        """Deliver text. Must not raise — a blocked bot or deleted chat is
        this user's problem, not the watcher's, and must never stop it from
        checking everyone else."""


class TelegramWishlistNotifier(WishlistNotifier):
    def __init__(self, bot):
        self._bot = bot

    async def notify(self, telegram_id, text):
        try:
            await self._bot.send_message(telegram_id, text)
        except Exception as exc:
            log.warning("could not notify %s: %s", telegram_id, exc)
