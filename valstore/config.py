"""Configuration. Loads a local .env file (if present) then reads from the
environment, so `python bot.py` works without any extra dependency. Real
environment variables (e.g. from a systemd EnvironmentFile) take precedence.

ALLOWED_IDS is deliberately gone: who may use the bot is no longer a restart-time
decision. What remains here is only what cannot change at runtime.
"""

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        # An unreadable .env is not fatal; real env vars may still carry everything.
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        # strip surrounding quotes, else strip any trailing inline comment
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]
        else:
            hpos = val.find(" #")
            if hpos != -1:
                val = val[:hpos].strip()
        # don't override a real env var that's already set
        if key and key not in os.environ:
            os.environ[key] = val


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required env var {name}. Fill it in .env "
            "(run gen_keys.py for the key values)."
        )
    return val


def _optional_int(name: str) -> int | None:
    """None when unset or unparsable — a typo in OWNER_ID must not stop the bot
    booting, it must only mean nobody holds the owner lever."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _int_with_default(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class Config:
    telegram_token: str
    at_rest_key: bytes
    bot_private_key_b64: str
    db_path: str
    owner_id: int | None
    max_accounts_per_user: int
    link_attempts_per_hour: int
    global_link_attempts_per_hour: int
    link_page_url: str
    wishlist_poll_interval_seconds: int
    max_wishlist_items_per_user: int


# The in-browser sealing page (docs/, hosted on GitHub Pages). Overridable so a
# fork can host it elsewhere without touching code.
DEFAULT_LINK_PAGE_URL = "https://hoag1337.github.io/vlr-storefront-fetcher/"


def load() -> Config:
    _load_dotenv()
    return Config(
        telegram_token=_require("TELEGRAM_TOKEN"),
        at_rest_key=_require("AT_REST_KEY").encode(),
        bot_private_key_b64=_require("BOT_PRIVATE_KEY"),
        db_path=os.environ.get("DB_PATH", "data/valstore.db"),
        # Not an allowlist — just who may use the owner-only commands.
        owner_id=_optional_int("OWNER_ID"),
        max_accounts_per_user=_int_with_default("MAX_ACCOUNTS_PER_USER", 5),
        link_attempts_per_hour=_int_with_default("LINK_ATTEMPTS_PER_HOUR", 10),
        global_link_attempts_per_hour=_int_with_default(
            "GLOBAL_LINK_ATTEMPTS_PER_HOUR", 100
        ),
        link_page_url=os.environ.get("LINK_PAGE_URL", DEFAULT_LINK_PAGE_URL),
        # The shop, Night Market and bundles all rotate at most once a day, and
        # a wishlist change triggers its own immediate check regardless — so a
        # daily sweep is enough to catch a rotation nobody was around to see.
        wishlist_poll_interval_seconds=_int_with_default(
            "WISHLIST_POLL_INTERVAL_SECONDS", 24 * 3600
        ),
        max_wishlist_items_per_user=_int_with_default(
            "MAX_WISHLIST_ITEMS_PER_USER", 25
        ),
    )
