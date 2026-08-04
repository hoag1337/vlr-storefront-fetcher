"""Configuration, loaded from environment. Nothing secret is hardcoded."""

import os


def _require(name):
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required env var {name}. See .env.example and run gen_keys.py."
        )
    return val


class Config:
    def __init__(self):
        self.telegram_token = _require("TELEGRAM_TOKEN")
        # AES/Fernet key for encrypting cookies at rest (url-safe base64, 32 bytes)
        self.at_rest_key = _require("AT_REST_KEY").encode()
        # NaCl private key (base64) that unseals the /link blobs
        self.bot_private_key_b64 = _require("BOT_PRIVATE_KEY")
        # Comma-separated Telegram user IDs allowed to use the bot
        raw = _require("ALLOWED_IDS")
        self.allowed_ids = {int(x.strip()) for x in raw.split(",") if x.strip()}
        self.db_path = os.environ.get("DB_PATH", "data/valstore.db")


def load():
    return Config()
