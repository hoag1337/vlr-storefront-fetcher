"""Composition root.

Every dependency is built once here and injected by name into handlers, so the
handler layer never constructs a repository, a catalog or a link method — which
is what makes each of them substitutable in a test.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand

from valstore import config
from valstore.assets import Catalogs
from valstore.bot.handlers import router
from valstore.commands import InventoryCommand, StoreCommand
from valstore.linking.method import LinkMethodRegistry
from valstore.linking.sealed_paste import SealedPasteLinkMethod
from valstore.repository import SqliteAccountRepository
from valstore.service import AccountService, CommandExecutor, LinkGuard
from valstore.wishlist.notifier import TelegramWishlistNotifier
from valstore.wishlist.repository import SqliteWishlistRepository
from valstore.wishlist.service import WishlistService
from valstore.wishlist.watcher import WishlistWatcher

log = logging.getLogger("valstore")

MENU = [
    BotCommand(command="store", description="Today's shop"),
    BotCommand(command="inventory", description="Your Premium+ skins"),
    BotCommand(command="wishlist", description="Skins to watch for"),
    BotCommand(command="accounts", description="Add, rename or remove accounts"),
    BotCommand(command="help", description="What I can do"),
]


def build_dispatcher(cfg, bot) -> Dispatcher:
    """Wire everything together. Separated from main() so tests can inspect it.

    Takes bot rather than building its own, because the wishlist watcher's
    notifier needs it too — one Bot for the whole process, not two.
    """
    repository = SqliteAccountRepository(cfg.db_path)
    catalogs = Catalogs()
    accounts = AccountService(repository, cfg.at_rest_key,
                              cfg.max_accounts_per_user)

    wishlist_repo = SqliteWishlistRepository(cfg.db_path)
    wishlist = WishlistService(wishlist_repo, catalogs,
                               cfg.max_wishlist_items_per_user)
    watcher = WishlistWatcher(
        wishlist_repo, repository, accounts, catalogs,
        TelegramWishlistNotifier(bot), cfg.wishlist_poll_interval_seconds,
    )

    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    dispatcher["cfg"] = cfg
    dispatcher["accounts"] = accounts
    dispatcher["executor"] = CommandExecutor(accounts, repository)
    dispatcher["store_command"] = StoreCommand(catalogs)
    dispatcher["inventory_command"] = InventoryCommand(catalogs)
    dispatcher["wishlist"] = wishlist
    dispatcher["watcher"] = watcher
    dispatcher["registry"] = LinkMethodRegistry([
        SealedPasteLinkMethod(cfg.bot_private_key_b64, cfg.link_page_url),
    ])
    dispatcher["guard"] = LinkGuard(
        per_user_per_hour=cfg.link_attempts_per_hour,
        global_per_hour=cfg.global_link_attempts_per_hour,
    )
    return dispatcher


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = config.load()

    # parse_mode=None: skin names and Riot handles are arbitrary text and would
    # break Markdown parsing.
    bot = Bot(cfg.telegram_token, default=DefaultBotProperties(parse_mode=None))
    dispatcher = build_dispatcher(cfg, bot)

    try:
        await bot.set_my_commands(MENU)
    except Exception as exc:
        # A menu that failed to register is cosmetic; do not refuse to start.
        log.warning("Could not set the command menu: %s", exc)

    # Held for the process lifetime by start_polling() below never returning;
    # an unreferenced task can otherwise be garbage-collected mid-flight.
    watch_task = asyncio.create_task(dispatcher["watcher"].run_forever())

    log.info("Bot starting (open to all; owner=%s, max %d accounts/user)",
             cfg.owner_id, cfg.max_accounts_per_user)
    try:
        await dispatcher.start_polling(bot)
    finally:
        watch_task.cancel()
