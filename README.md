# Valorant Store Telegram Bot

On-demand, private, allowlisted. Send `/store`, get your current shop — no
launching the game. Built on the auth→store chain proven in Phase 0.

## Security model
- Your cookie is **sealed to the bot's public key** on your machine before it
  ever touches Telegram, so the plaintext `ssid` never transits Telegram.
- At rest it's **Fernet-encrypted** with a key that lives only in the bot's
  environment. A stolen DB is useless without it.
- The bot answers **only** Telegram IDs on the allowlist.
- Keep it private to you two. A public version is what Riot bans.

## One-time setup
1. `pip install -r requirements.txt`
2. Make a bot with @BotFather, copy the token.
3. Generate keys: `python gen_keys.py` — it prints `BOT_PRIVATE_KEY`,
   `AT_REST_KEY`, and `BOT_PUBLIC_KEY`.
4. `cp .env.example .env` and fill in `TELEGRAM_TOKEN`, `ALLOWED_IDS`
   (get IDs by messaging the running bot `/whoami`), `BOT_PRIVATE_KEY`,
   `AT_REST_KEY`. Never commit `.env`.
5. Give the `BOT_PUBLIC_KEY` to whoever links (it's used by `seal_ssid.py`).

## Linking an account
On your own machine:
```
python seal_ssid.py --pubkey <BOT_PUBLIC_KEY>
```
Paste your cookie (`ssid=...; clid=...`) when prompted, copy the printed
`/link <blob>`, send it to the bot, then delete that message.

## Daily use
`/store` — today's shop. `/unlink` — wipe your session.

## Running 24/7 (Windows home PC)
- Set the PC to never sleep; disable NIC power management and Fast Startup.
- Wrap `python bot.py` as a service with NSSM under a dedicated non-admin user.
- Long polling → no open ports, no port forwarding.

## Files
- `bot.py` — handlers / polling
- `riot_auth.py` — the proven auth+store chain
- `store_format.py` — skin-name enrichment + message
- `crypto_util.py` / `storage.py` / `config.py` — plumbing
- `gen_keys.py` / `seal_ssid.py` — one-time key + linking tools
