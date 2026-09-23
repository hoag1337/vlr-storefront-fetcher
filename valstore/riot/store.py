"""Storefront endpoint."""

import requests

from valstore.riot.auth import CLIENT_PLATFORM, DEFAULT_UA, HTTP_TIMEOUT


def get_storefront(shard, puuid, access_token, entitlements_token, client_version,
                   user_agent=DEFAULT_UA):
    # Current live endpoint: the store moved from v2-GET to v3-POST with an empty
    # JSON body. The old v2 GET now returns RESOURCE_NOT_FOUND.
    url = f"https://pd.{shard}.a.pvp.net/store/v3/storefront/{puuid}"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "X-Riot-Entitlements-JWT": entitlements_token,
            "X-Riot-ClientPlatform": CLIENT_PLATFORM,
            "X-Riot-ClientVersion": client_version,
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        },
        json={},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    return resp.json()
