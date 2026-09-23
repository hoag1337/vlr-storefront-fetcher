# Valorant Store Telegram Bot

Send `/store`, get your current shop — no launching the game. Accounts are added
and removed from the chat while the bot runs; nothing needs a restart.

## What it does

- `/store` — today's shop, with Night Market and bundles when they're live
- `/inventory` — every skin you own at **Premium Edition or above**
  (Premium / Exclusive / Ultra), grouped by tier
- `/accounts` — add, rename, remove, or pick a default account
- `/help` — the same list, in the chat

Everything is buttons. Several Riot accounts can be linked to one Telegram user,
and `/store` only asks which one when more than one is linked.

## Security model

- The session is **sealed to the bot's public key** before it leaves your
  machine, so the plaintext cookie never transits Telegram.
- At rest it is **Fernet-encrypted** with a key held only in the bot's
  environment. A stolen database is useless without it.
- **Your Riot password is never sent to the bot** and never stored. The bot only
  ever holds a session cookie, and `/accounts → Remove` deletes it immediately.
- Removing an account wipes its stored session in the same action.

The bot is **open to anyone who can link an account**. There is no allowlist. Two
guards exist because of that: link attempts are rate-limited per user and
globally, and the `OWNER_ID` can `/lockdown` linking (and `/unlock` it) if the
bot is ever found and abused. Keep it private; a public version is what Riot
bans.

## Setup

1. `pip install -r requirements.txt`
2. Make a bot with @BotFather and copy the token.
3. `python gen_keys.py` — prints `BOT_PRIVATE_KEY`, `AT_REST_KEY` and
   `BOT_PUBLIC_KEY`.
4. `cp .env.example .env` and fill it in. Never commit `.env`.
5. Share `BOT_PUBLIC_KEY` with whoever links — it is the only key that is safe
   to hand out.
6. `python bot.py`

## Linking an account

Send `/start` and tap **Link an account**; the bot walks you through whichever
method is enabled.

Today that is the sealed-paste method, which needs a computer once:

```
python tools/seal_ssid.py --pubkey <BOT_PUBLIC_KEY>
```

Paste your Riot cookie when prompted, then send the bot the line it prints. It
is already encrypted to the bot, so nobody in between can read it. Delete the
message afterwards anyway.

> **Why it still asks for a cookie.** Riot now requires an hCaptcha token on its
> password endpoint and recommends against direct username/password auth, and the
> session cookie is `HttpOnly` — so no web page or Mini App can read it. A
> friendlier method plugs in as another `LinkMethod` without touching anything
> else; see `valstore/linking/`.

## Running 24/7 (Windows home PC)

- Set the PC to never sleep; disable NIC power management and Fast Startup.
- Wrap `python bot.py` as a service with NSSM under a dedicated non-admin user.
- Long polling → no open ports, no port forwarding.

## Layout

```
bot.py                    entry point
valstore/
  config.py               env loading
  crypto.py               sealed box (in transit) + Fernet (at rest)
  errors.py               every expected failure, in one hierarchy
  models.py               Account, RiotIdentity, LinkResult
  assets.py               cached valorant-api catalogs
  repository.py           AccountRepository + SQLite implementation
  service.py              account lifecycle, command execution, rate limiting
  commands.py             AccountCommand + Store / Inventory
  rendering.py            payload -> Telegram messages
  riot/                   auth chain, identity, storefront, entitlements
  linking/                LinkMethod + implementations
  bot/                    handlers, keyboards, copy, composition root
tools/seal_ssid.py        one-time linking helper
tests/                    python -m unittest discover -s tests
```

## Tests

```
python -m unittest discover -s tests
```

No network and no database file required.

## Upgrading from the single-account version

Starting the bot migrates the old `users` table into `accounts` automatically.
The old table is renamed to `users_legacy` rather than dropped, so the migration
is reversible from the same file. Back up `data/valstore.db` first anyway.
`ALLOWED_IDS` is no longer read — delete it from your `.env`.
