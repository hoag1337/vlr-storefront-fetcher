"""Every failure the bot can surface, in one hierarchy.

Handlers catch these to turn a failure into a sentence a non-technical user can
act on. Anything not derived from ValstoreError is a genuine bug and is logged
with a traceback rather than shown.
"""


class ValstoreError(Exception):
    """Base for every expected failure."""


# ---- Riot chain ----

class RiotError(ValstoreError):
    """Riot's API refused or could not be reached."""


class ReauthError(RiotError):
    """The session cookie did not produce an access token (expired/invalid)."""


class CloudflareBlock(ReauthError):
    """Riot's WAF challenged us instead of authenticating. The known risk."""


# ---- assets ----

class AssetUnavailable(ValstoreError):
    """No usable catalog: the fetch failed and there is no cache to fall back on."""


# ---- accounts ----

class AccountNotFound(ValstoreError):
    """The account id does not exist, or belongs to a different Telegram user."""


class DuplicateAccount(ValstoreError):
    """That Riot account is already linked to this Telegram user."""


class AccountLimitReached(ValstoreError):
    """Adding another account would exceed the per-user cap.

    Raised only for a genuinely new account: refreshing one already linked must
    never be blocked by the cap, since an expired session is the common case.
    """


class SessionDecryptError(ValstoreError):
    """The stored cookie could not be decrypted — almost always a changed AT_REST_KEY."""


# ---- wishlist ----

class WishlistLimitReached(ValstoreError):
    """Adding another wishlisted skin would exceed the per-user cap."""


# ---- linking ----

class LinkError(ValstoreError):
    """A link attempt failed in a way the user can fix and retry."""


class RateLimited(ValstoreError):
    """Too many link attempts. Carries the wait in seconds so callers can say it."""

    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Too many attempts. Try again in {retry_after_seconds} seconds."
        )
