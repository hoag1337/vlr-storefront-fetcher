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

Send `/start` and tap **Link an account**. The bot sends a link to the sealing
page (`docs/`, hosted on GitHub Pages). On a computer the friend:

1. signs in to Riot,
2. copies one cookie value (`ssid`) — the page shows how, per browser,
3. pastes it into the page, which **seals it in the browser** and prints a
   `/link …` line,
4. sends that line back to the bot.

The page never uploads anything: the cookie is encrypted to the bot's public key
entirely client-side (proven byte-compatible with `valstore.crypto.unseal`), so
the plaintext session never leaves the friend's machine. `tools/seal_ssid.py`
does the same thing from a terminal for anyone who prefers it.

> **Why a computer is needed once.** Riot now requires an hCaptcha token on its
> password endpoint, Riot Mobile (the QR flow) isn't available in every region,
> and the session cookie is `HttpOnly` — so no phone page, Mini App, or bookmark
> can read it. Extracting it needs a desktop browser's dev tools once; after
> that, daily use is entirely on the phone. The QR flow is spiked in
> `tools/spike_qr_login.py` for regions where Riot Mobile exists.

### Hosting the sealing page

The `docs/` folder is a self-contained static site. Enable GitHub Pages
(Settings → Pages → deploy from `main`/`docs`) and point `LINK_PAGE_URL` at the
result. It has no build step and no runtime network calls; the two vendored
crypto libraries (`tweetnacl`, `blakejs`) are served from `docs/vendor/`. The
bot's public key is baked into `docs/index.html` — update it there if you ever
run `gen_keys.py` again.

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
