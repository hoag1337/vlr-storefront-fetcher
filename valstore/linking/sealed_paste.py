"""Linking by pasting a sealed blob.

The cookie is sealed to the bot's public key on the user's own machine, so the
plaintext session never transits Telegram. The friendly path is the in-browser
sealing page (docs/), which does the sealing for a non-technical user; the
command-line helper (tools/seal_ssid.py) remains for anyone who prefers it.
Either way the bot receives the same sealed blob, and this is the one route that
depends on nothing Riot might change.
"""

import logging

from valstore import crypto
from valstore.config import DEFAULT_LINK_PAGE_URL
from valstore.errors import LinkError, ReauthError
from valstore.linking.method import LinkChallenge, LinkMethod
from valstore.models import LinkResult
from valstore.riot.session import validate

log = logging.getLogger("valstore.linking.sealed_paste")


def _instructions(page_url: str) -> str:
    return (
        "Let's link an account. You'll need a computer for this one step "
        "(a phone can't do it) — after that everything works from your phone.\n\n"
        f"1. On a computer, open this page:\n{page_url}\n\n"
        "2. Follow the three steps there. It never sends anything anywhere — it "
        "just locks your session to me right in your browser.\n\n"
        "3. Copy the /link line it gives you and send it to me here.\n\n"
        "Prefer the terminal? Run  python tools/seal_ssid.py --pubkey "
        "<BOT_PUBLIC_KEY>  instead — it produces the same line."
    )


class SealedPasteLinkMethod(LinkMethod):
    id = "sealed"
    title = "🔗 Link from a computer"
    summary = "Open a short web page on any computer — no install."
    # The blob sits in the chat history until the user removes it.
    post_link_note = (
        "One more thing — please delete your last message. It carried your "
        "sealed session, and there's no reason to leave it in the chat."
    )

    def __init__(self, private_key_b64: str, link_page_url: str = DEFAULT_LINK_PAGE_URL):
        self._private_key_b64 = private_key_b64
        self._link_page_url = link_page_url

    def start(self, telegram_id):
        return LinkChallenge(instructions=_instructions(self._link_page_url))

    def complete(self, telegram_id, response):
        blob = (response or "").strip()
        # Tolerate someone pasting the whole "/link <blob>" line the helper prints.
        if blob.lower().startswith("/link"):
            blob = blob[len("/link"):].strip()
        if not blob:
            raise LinkError("That message had no sealed session in it.")

        try:
            cookie_header = crypto.unseal(self._private_key_b64, blob)
        except Exception as exc:
            log.info("unseal failed for %s: %s", telegram_id, type(exc).__name__)
            raise LinkError(
                "I couldn't open that. Re-run the helper with my current public "
                "key and send the new line."
            ) from exc

        if "ssid=" not in cookie_header:
            raise LinkError(
                "That opened, but it doesn't contain a Riot session cookie."
            )

        try:
            shard, identity = validate(cookie_header)
        except ReauthError as exc:
            raise LinkError(
                "Riot didn't accept that session. Log in again and reseal a "
                f"fresh cookie. ({exc})"
            ) from exc

        return LinkResult(cookie_header=cookie_header, shard=shard,
                          identity=identity)
