"""Owned items from the in-game API.

Same credential chain as the storefront, just a different endpoint. Nothing here
stores or logs secrets.
"""

import requests

from valstore.riot.auth import CLIENT_PLATFORM, DEFAULT_UA, HTTP_TIMEOUT

# Entitlement categories are one endpoint distinguished by this id. Only skin
# levels are wired up today; the rest are listed so adding one is a constant.
ITEM_TYPE_SKIN_LEVELS = "e7c63390-eda7-46e0-bb7a-a6abdacd2433"
ITEM_TYPE_BUDDIES = "dd3bf334-87f7-4713-b198-7a2b31d90ec6"
ITEM_TYPE_SPRAYS = "d5f120f8-ff8c-4aac-92ea-f2b5acbe9475"
ITEM_TYPE_PLAYER_CARDS = "3f296c07-64c3-494c-923b-fe692a4fa1bd"
ITEM_TYPE_TITLES = "de7caa6b-adf7-4588-bbd1-143831e786c6"


def get_entitlements(shard, puuid, item_type_id, access_token, entitlements_token,
                     client_version, user_agent=DEFAULT_UA):
    """Raw entitlements payload for one item category."""
    url = (f"https://pd.{shard}.a.pvp.net/store/v1/entitlements/"
           f"{puuid}/{item_type_id}")
    resp = requests.get(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Riot-Entitlements-JWT": entitlements_token,
            "X-Riot-ClientPlatform": CLIENT_PLATFORM,
            "X-Riot-ClientVersion": client_version,
            "User-Agent": user_agent,
        },
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()


def owned_skin_level_ids(shard, puuid, access_token, entitlements_token,
                         client_version, user_agent=DEFAULT_UA):
    """Lower-cased skin-level uuids the player owns.

    Riot has changed response shapes before, so every field is treated as
    optional rather than assumed present.
    """
    payload = get_entitlements(shard, puuid, ITEM_TYPE_SKIN_LEVELS, access_token,
                               entitlements_token, client_version, user_agent)
    if not isinstance(payload, dict):
        return []
    return [
        item["ItemID"].lower()
        for item in (payload.get("Entitlements") or [])
        if isinstance(item, dict) and item.get("ItemID")
    ]
