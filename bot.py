"""
Valorant store bot (aiogram 3). On-demand, private, allowlisted.

Commands:
  /start   — intro + your Telegram ID
  /whoami  — your Telegram ID (for building the allowlist)
  /link    — /link <sealed-blob>  (blob comes from seal_ssid.py)
  /store   — fetch and show your current store
  /unlink  — delete your stored session

The Riot chain is synchronous (requests); each call is pushed to a thread so
the event loop is never blocked.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

import config
import crypto_util as cu
import riot_auth as ra
import store_format
from storage import Storage

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("valstore")

dp = Dispatcher()


def _authorized(message: Message, cfg) -> bool:
    return message.from_user is not None and message.from_user.id in cfg.allowed_ids


# ---- synchronous Riot work, run in a thread from async handlers ----

def _validate_and_shard(cookie_header):
    """Prove a cookie works and discover its shard. Returns shard."""
    access_token, id_token, _ = ra.reauth(cookie_header=cookie_header)
    return ra.get_live_shard(access_token, id_token)


def _fetch_store(cookie_header, shard):
    """Run the full chain. Returns (store_dict, rotated_cookie_or_None)."""
    version = ra.get_client_version()
    access_token, _id, rotated_ssid = ra.reauth(cookie_header=cookie_header)
    puuid = ra.puuid_from_token(access_token)
    ent = ra.get_entitlement(access_token)
    store = ra.get_storefront(shard, puuid, access_token, ent, version)
    new_cookie = None
    if rotated_ssid:
        candidate = ra.replace_ssid(cookie_header, rotated_ssid)
        if candidate != cookie_header:
            new_cookie = candidate
    return store, new_cookie


# ---- handlers ----

@dp.message(Command("start"))
async def cmd_start(message: Message, cfg):
    uid = message.from_user.id
    if not _authorized(message, cfg):
        await message.answer(
            f"This is a private bot. Your Telegram ID is `{uid}` — ask the owner "
            "to add it to the allowlist.", parse_mode="Markdown")
        return
    await message.answer(
        "Linked accounts can use /store to see today's shop.\n"
        "Not linked yet? Run seal_ssid.py locally and send /link <blob>.")


@dp.message(Command("whoami"))
async def cmd_whoami(message: Message):
    await message.answer(f"Your Telegram ID: `{message.from_user.id}`",
                         parse_mode="Markdown")


@dp.message(Command("link"))
async def cmd_link(message: Message, command: CommandObject, cfg, store: Storage):
    if not _authorized(message, cfg):
        await message.answer("Not authorized.")
        return
    blob = (command.args or "").strip()
    if not blob:
        await message.answer("Usage: /link <sealed-blob from seal_ssid.py>")
        return
    try:
        cookie_header = cu.unseal(cfg.bot_private_key_b64, blob)
    except Exception:
        await message.answer("Couldn't open that blob. Re-run seal_ssid.py with "
                             "the current bot public key.")
        return

    await message.answer("Validating session with Riot…")
    try:
        shard = await asyncio.to_thread(_validate_and_shard, cookie_header)
    except ra.CloudflareBlock:
        await message.answer("Riot's WAF blocked validation. Try again shortly.")
        return
    except ra.ReauthError:
        await message.answer("That session didn't authenticate. Copy a fresh "
                             "cookie and reseal.")
        return

    enc = cu.encrypt_at_rest(cfg.at_rest_key, cookie_header)
    store.upsert(message.from_user.id, enc, shard)
    await message.answer(
        f"✅ Linked (shard `{shard}`). Now delete your /link message — it held "
        "your sealed session. Use /store anytime.", parse_mode="Markdown")


@dp.message(Command("store"))
async def cmd_store(message: Message, cfg, store: Storage):
    if not _authorized(message, cfg):
        await message.answer("Not authorized.")
        return
    row = store.get(message.from_user.id)
    if not row:
        await message.answer("You're not linked. Send /link <blob> first.")
        return

    cookie_header = cu.decrypt_at_rest(cfg.at_rest_key, row["enc_cookie"])
    await message.answer("Fetching your store…")
    try:
        result, new_cookie = await asyncio.to_thread(
            _fetch_store, cookie_header, row["shard"])
    except ra.CloudflareBlock:
        await message.answer("Riot's WAF blocked the request. Try again shortly.")
        return
    except ra.ReauthError:
        await message.answer("Your session expired. Reseal a fresh cookie and "
                             "/link again.")
        return
    except Exception as e:
        log.exception("store fetch failed")
        await message.answer(f"Something went wrong: {e}")
        return

    if new_cookie:
        enc = cu.encrypt_at_rest(cfg.at_rest_key, new_cookie)
        store.update_cookie(message.from_user.id, enc)

    # plain text on purpose: skin names are arbitrary and would break Markdown
    await message.answer(store_format.format_store(result))


@dp.message(Command("unlink"))
async def cmd_unlink(message: Message, cfg, store: Storage):
    if not _authorized(message, cfg):
        await message.answer("Not authorized.")
        return
    store.delete(message.from_user.id)
    await message.answer("Unlinked. Your stored session was deleted.")


async def main():
    cfg = config.load()
    store = Storage(cfg.db_path)
    bot = Bot(cfg.telegram_token,
              default=DefaultBotProperties(parse_mode=None))
    # inject shared objects into every handler by parameter name
    dp["cfg"] = cfg
    dp["store"] = store
    log.info("Bot starting (allowlist: %s)", sorted(cfg.allowed_ids))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
