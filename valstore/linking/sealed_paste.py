"""Linking by pasting a sealed blob.

The original flow, kept because it always works: the cookie is sealed to the
bot's public key on the user's own machine, so the plaintext session never
transits Telegram. It asks a lot of a non-technical user, which is why it is the
fallback rather than the headline, but it is the one route that depends on
nothing Riot might change.
"""

import logging

from valstore import crypto
from valstore.errors import LinkError, ReauthError
from valstore.linking.method import LinkChallenge, LinkMethod
from valstore.models import LinkResult
from valstore.riot.session import validate

log = logging.getLogger("valstore.linking.sealed_paste")

_INSTRUCTIONS = (
    "On a computer, run the helper from the project folder:\n\n"
    "  python tools/seal_ssid.py --pubkey <BOT_PUBLIC_KEY>\n\n"
    "Paste your Riot cookie when it asks, then send me the line it prints. "
    "It is already encrypted to me, so nobody in between can read it."
)


class SealedPasteLinkMethod(LinkMethod):
    id = "sealed"
    title = "🔐 Paste a sealed session"
    summary = "Works anywhere, but needs a computer and a few steps."
    # The blob sits in the chat history until the user removes it.
    post_link_note = (
        "One more thing — please delete your last message. It carried your "
        "sealed session, and there's no reason to leave it in the chat."
    )

    def __init__(self, private_key_b64: str):
        self._private_key_b64 = private_key_b64

    def start(self, telegram_id):
        return LinkChallenge(instructions=_INSTRUCTIONS)

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
