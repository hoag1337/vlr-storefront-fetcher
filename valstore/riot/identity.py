"""Who a session belongs to.

One extra call at link time buys a label a human recognises ("Player#NA1")
instead of a shard code, which is most of what makes the account picker
readable once somebody links a second account.
"""

import logging

import requests

from valstore.models import RiotIdentity
from valstore.riot.auth import DEFAULT_UA, HTTP_TIMEOUT, puuid_from_token

log = logging.getLogger("valstore.riot.identity")

USERINFO_URL = "https://auth.riotgames.com/userinfo"


def fetch_identity(access_token, user_agent=DEFAULT_UA) -> RiotIdentity:
    """Riot identity for this token.

    Never fatal: the puuid is already recoverable from the token itself, so a
    failure here costs a pretty name, not the link. Falling back keeps a Riot
    outage from blocking an otherwise valid session.
    """
    puuid = puuid_from_token(access_token)
    try:
        resp = requests.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}",
                     "User-Agent": user_agent},
            timeout=HTTP_TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        log.warning("Could not read Riot userinfo (%s); using puuid only.", exc)
        return RiotIdentity(puuid=puuid)

    if not isinstance(payload, dict):
        return RiotIdentity(puuid=puuid)
    acct = payload.get("acct")
    if not isinstance(acct, dict):
        return RiotIdentity(puuid=puuid)
    return RiotIdentity(
        puuid=payload.get("sub") or puuid,
        game_name=acct.get("game_name"),
        tag_line=acct.get("tag_line"),
    )
