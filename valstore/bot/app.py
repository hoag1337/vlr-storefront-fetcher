"""Composition root.

Every dependency is built once here and injected by name into handlers, so the
handler layer never constructs a repository, a catalog or a link method — which
is what makes each of them substitutable in a test.
"""

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

log = logging.getLogger("valstore")

MENU = [
    BotCommand(command="store", description="Today's shop"),
    BotCommand(command="inventory", description="Your Premium+ skins"),
    BotCommand(command="accounts", description="Add, rename or remove accounts"),
    BotCommand(command="help", description="What I can do"),
]


def build_dispatcher(cfg) -> Dispatcher:
    """Wire everything together. Separated from main() so tests can inspect it."""
    repository = SqliteAccountRepository(cfg.db_path)
    catalogs = Catalogs()
    accounts = AccountService(repository, cfg.at_rest_key,
                              cfg.max_accounts_per_user)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    dispatcher["cfg"] = cfg
    dispatcher["accounts"] = accounts
    dispatcher["executor"] = CommandExecutor(accounts, repository)
    dispatcher["store_command"] = StoreCommand(catalogs)
    dispatcher["inventory_command"] = InventoryCommand(catalogs)
    dispatcher["registry"] = LinkMethodRegistry([
        SealedPasteLinkMethod(cfg.bot_private_key_b64),
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
    dispatcher = build_dispatcher(cfg)

    # parse_mode=None: skin names and Riot handles are arbitrary text and would
    # break Markdown parsing.
    bot = Bot(cfg.telegram_token, default=DefaultBotProperties(parse_mode=None))

    try:
        await bot.set_my_commands(MENU)
    except Exception as exc:
        # A menu that failed to register is cosmetic; do not refuse to start.
        log.warning("Could not set the command menu: %s", exc)

    log.info("Bot starting (open to all; owner=%s, max %d accounts/user)",
             cfg.owner_id, cfg.max_accounts_per_user)
    await dispatcher.start_polling(bot)
