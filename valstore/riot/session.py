"""The credential chain every authenticated Riot call needs.

Built once per command so /store and /inventory share exactly one code path to
the tokens, and so a rotated cookie is reported the same way regardless of
which command triggered the refresh.
"""

from dataclasses import dataclass

from valstore.models import RiotIdentity
from valstore.riot import auth
from valstore.riot.identity import fetch_identity


@dataclass(frozen=True)
class RiotSession:
    """Everything downstream endpoints require, plus any refreshed cookie."""

    access_token: str
    puuid: str
    entitlements_token: str
    client_version: str
    rotated_cookie: str | None = None


def open_session(cookie_header: str) -> RiotSession:
    """Run the full chain for a stored cookie. Synchronous: call in a thread."""
    version = auth.get_client_version()
    access_token, _id_token, rotated_ssid = auth.reauth(cookie_header=cookie_header)
    puuid = auth.puuid_from_token(access_token)
    entitlements = auth.get_entitlement(access_token)

    rotated_cookie = None
    if rotated_ssid:
        candidate = auth.replace_ssid(cookie_header, rotated_ssid)
        if candidate != cookie_header:
            rotated_cookie = candidate

    return RiotSession(
        access_token=access_token,
        puuid=puuid,
        entitlements_token=entitlements,
        client_version=version,
        rotated_cookie=rotated_cookie,
    )


def validate(cookie_header: str) -> tuple[str, RiotIdentity]:
    """Prove a cookie works and discover where it lives.

    Shared by every LinkMethod: whatever route produced the cookie, this is what
    decides it is real. Returns (shard, identity).
    """
    access_token, id_token, _rotated = auth.reauth(cookie_header=cookie_header)
    shard = auth.get_live_shard(access_token, id_token)
    return shard, fetch_identity(access_token)
