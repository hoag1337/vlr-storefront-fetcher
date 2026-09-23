"""Every user-facing string, in one place.

Kept together because the tone is a feature: people are handing this bot access
to a game account, so the copy says plainly what is stored and what is not, and
never asks anyone to do something it hasn't explained.
"""

WELCOME = (
    "👋 This bot shows your Valorant shop without launching the game.\n\n"
    "What I store: an encrypted Riot session, nothing else.\n"
    "What I never see: your password.\n\n"
    "Link an account to get started — you can add more later, and remove any of "
    "them at any time."
)

HELP = (
    "🛒 /store — today's shop\n"
    "🎒 /inventory — your skins, Premium Edition and above\n"
    "👤 /accounts — add, rename, or remove accounts\n"
    "❓ /help — this message"
)

NO_ACCOUNTS = (
    "You have no accounts linked yet.\n\n"
    "Tap below to link one — it takes a moment and you can remove it whenever "
    "you like."
)

ACCOUNTS_HEADER = "👤 Your accounts ({count})\n\nTap one to use or manage it."

ACCOUNT_DETAIL = (
    "👤 {title}\nRegion: {shard}{default_note}\n\nWhat would you like to do?"
)

DEFAULT_NOTE = "\n⭐ Used by default for /store and /inventory"

AT_CAPACITY = (
    "You've reached the limit of {max} linked accounts. Remove one first and "
    "you can link another."
)

# ---- linking ----

CHOOSE_LINK_METHOD = "How would you like to link your account?"

LINK_CANCELLED = "Cancelled. Nothing was linked and nothing was stored."

LINK_VALIDATING = "Checking that session with Riot…"

LINK_SUCCESS = (
    "✅ Linked {title} (region {shard}).\n\n"
    "Your session is encrypted before it's stored. Use /store any time, or "
    "/accounts to manage it."
)

LINK_REFRESHED = (
    "🔄 Refreshed {title} (region {shard}).\n\n"
    "That account was already linked, so I updated its session instead of "
    "adding a duplicate."
)

LINKING_DISABLED = (
    "Linking is paused right now. Please try again later."
)

# ---- account management ----

CONFIRM_REMOVE = (
    "Remove {title}?\n\nIts stored session is deleted immediately and I lose "
    "all access to that account. You can always link it again later."
)

REMOVED = "🗑 Removed {title}. Its stored session is gone."

RENAME_PROMPT = (
    "What should I call {title}?\n\nSend me the new name, or /cancel to keep "
    "it as it is."
)

RENAMED = "✏️ Renamed to {label}."

RENAME_EMPTY = "That name was empty, so I kept the old one."

DEFAULT_SET = "⭐ {title} is now your default account."

NOTHING_TO_CANCEL = "Nothing to cancel."

# ---- failures ----

ERR_NO_SUCH_ACCOUNT = "That account is no longer linked. Try /accounts."

ERR_SESSION_EXPIRED = (
    "That account's session has expired — Riot does that periodically.\n\n"
    "Link it again and everything else stays as it was."
)

ERR_SESSION_UNREADABLE = (
    "I couldn't decrypt that account's stored session, so it has to be linked "
    "again. (This happens if the bot's encryption key changed.)"
)

ERR_CLOUDFLARE = (
    "Riot's protection blocked the request. This usually clears up on its own — "
    "try again in a few minutes."
)

ERR_CATALOG = (
    "I couldn't load the skin catalogue just now, so names would be missing. "
    "Try again shortly."
)

ERR_RATE_LIMITED = "Too many attempts. Try again in about {minutes} minute(s)."

ERR_UNEXPECTED = (
    "Something went wrong on my side. It's been logged — try again shortly."
)
