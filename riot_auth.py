"""
riot_auth.py — the fragile joint of the whole project, isolated so we can prove
it works against a real account before building anything around it.

Chain: ssid cookie -> access token -> entitlements token -> puuid -> storefront

Nothing here stores or logs secrets. The caller owns the ssid.
"""

import base64
import json
import urllib.parse

import requests

# Base-64 client-platform blob that Riot's own web client sends. Documented as
# a value that works; decodes to {"platformType":"PC","platformOS":"Windows",...}
CLIENT_PLATFORM = (
    "ew0KCSJwbGF0Zm9ybVR5cGUiOiAiUEMiLA0KCSJwbGF0Zm9ybU9TIjogIldpbmRvd3MiLA0KCSJwbGF0"
    "Zm9ybU9TVmVyc2lvbiI6ICIxMC4wLjE5MDQyLjEuMjU2LjY0Yml0IiwNCgkicGxhdGZvcm1DaGlwc2V0"
    "IjogIlVua25vd24iDQp9"
)

# The reauth URL: Riot's own play-valorant-web-prod client, token response mode.
# A valid ssid cookie makes this 303-redirect with the access token in the URL
# fragment. We deliberately do NOT follow the redirect.
REAUTH_URL = (
    "https://auth.riotgames.com/authorize"
    "?redirect_uri=https%3A%2F%2Fplayvalorant.com%2Fopt_in"
    "&client_id=play-valorant-web-prod"
    "&response_type=token%20id_token"
    "&nonce=1"
    "&scope=account%20openid"
)

ENTITLEMENT_URL = "https://entitlements.auth.riotgames.com/api/token/v1"
VERSION_URL = "https://valorant-api.com/v1/version"

# Valorant Points currency UUID (the price you actually care about).
VP_CURRENCY_ID = "85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741"
RAD_CURRENCY_ID = "e59aa87c-4cbf-517a-5983-6e81511be9b7"  # Radianite (bundles)

# A plain browser UA. Riot's web auth endpoint is behind Cloudflare; sending a
# believable UA is what usually keeps the captcha from firing.
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class ReauthError(Exception):
    """The ssid did not produce an access token (expired/invalid/malformed)."""


class CloudflareBlock(ReauthError):
    """Riot's WAF challenged us instead of authenticating. The known risk."""


def _looks_like_cloudflare(resp):
    body = resp.text.lower()
    markers = ("cloudflare", "cf-ray", "attention required", "cf-chl", "just a moment")
    ct = resp.headers.get("Content-Type", "")
    return "text/html" in ct and any(m in body for m in markers)


def reauth(ssid=None, cookie_header=None, user_agent=DEFAULT_UA):
    """Exchange a session cookie for a fresh access token.

    Pass either ssid (just the cookie value) or cookie_header (the full
    'name=value; name2=value2' string copied from the browser). The full
    header is more reliable if the bare ssid alone gets rejected.

    Returns (access_token, id_token, rotated_ssid). rotated_ssid may be None;
    if present, persist it — Riot sometimes hands back a refreshed cookie.
    """
    if not ssid and not cookie_header:
        raise ValueError("Provide ssid or cookie_header")

    cookie_value = cookie_header if cookie_header else f"ssid={ssid}"

    session = requests.Session()
    resp = session.get(
        REAUTH_URL,
        headers={"User-Agent": user_agent, "Cookie": cookie_value},
        allow_redirects=False,
        timeout=15,
    )

    if _looks_like_cloudflare(resp):
        raise CloudflareBlock(
            "Cloudflare challenged the reauth request (status "
            f"{resp.status_code}). This is the WAF risk we flagged. Try again "
            "from a residential IP / your home PC, or fall back to the local "
            "webview capture."
        )

    location = resp.headers.get("Location", "")
    parsed = urllib.parse.urlparse(location)
    fragment_params = urllib.parse.parse_qs(parsed.fragment)
    query_params = urllib.parse.parse_qs(parsed.query)

    access_token = fragment_params.get("access_token", [None])[0]
    id_token = fragment_params.get("id_token", [None])[0]

    if not access_token:
        # Diagnose instead of guessing. On failure there is no token to leak;
        # the redirect target itself is the evidence we need.
        err = (fragment_params.get("error", [None])[0]
               or query_params.get("error", [None])[0])
        # scheme://host/path only — strip query+fragment so nothing sensitive shows
        dest = f"{parsed.scheme}://{parsed.netloc}{parsed.path}" if location else "(no Location header)"

        if err:
            raise ReauthError(
                f"Riot returned error='{err}' (HTTP {resp.status_code}). This is "
                "usually a session that isn't valid for the valorant web client — "
                "re-login and copy the FULL cookie set, or log in via the client flow."
            )
        if "login" in parsed.path.lower() or "auth" in parsed.path.lower():
            raise ReauthError(
                f"Redirect went to {dest} instead of playvalorant.com — the session "
                f"was NOT recognized (HTTP {resp.status_code}). Bare ssid is likely "
                "insufficient; retry with --cookies using the full cookie header."
            )
        raise ReauthError(
            f"No access_token in redirect. Destination: {dest} (HTTP {resp.status_code}). "
            "Retry with --cookies (full cookie header); if it still fails, send me this "
            "destination."
        )

    rotated_ssid = session.cookies.get("ssid")
    return access_token, id_token, rotated_ssid


def get_entitlement(access_token, user_agent=DEFAULT_UA):
    resp = requests.post(
        ENTITLEMENT_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        },
        json={},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["entitlements_token"]


def puuid_from_token(access_token):
    """The access token is a JWT; its 'sub' claim is the PUUID. No extra call,
    and we intentionally do not verify the signature (we did not mint it)."""
    payload_segment = access_token.split(".")[1]
    payload_segment += "=" * (-len(payload_segment) % 4)  # fix base64 padding
    payload = json.loads(base64.urlsafe_b64decode(payload_segment))
    return payload["sub"]


def get_client_version():
    resp = requests.get(VERSION_URL, timeout=15)
    resp.raise_for_status()
    return resp.json()["data"]["riotClientVersion"]


GEO_URL = "https://riot-geo.pas.si.riotgames.com/pas/v1/product/valorant"


def get_live_shard(access_token, id_token, user_agent=DEFAULT_UA):
    """Authoritative shard from Riot's geo service. Returns 'na'/'eu'/'ap'/'kr'.
    Proven reliable in Phase 0 (returned the correct 'ap')."""
    resp = requests.put(
        GEO_URL,
        headers={"Authorization": f"Bearer {access_token}", "User-Agent": user_agent},
        json={"id_token": id_token},
        timeout=15,
    )
    resp.raise_for_status()
    # response body is a JWT; decode payload for affinities.live
    seg = resp.text.split(".")[1]
    seg += "=" * (-len(seg) % 4)
    payload = json.loads(base64.urlsafe_b64decode(seg))
    return payload["affinities"]["live"]


def replace_ssid(cookie_header, new_ssid):
    """Return cookie_header with its ssid value swapped for new_ssid, so a
    rotated cookie can be persisted to prolong the session."""
    if not new_ssid:
        return cookie_header
    parts = [p.strip() for p in cookie_header.split(";") if p.strip()]
    out, replaced = [], False
    for p in parts:
        if p.lower().startswith("ssid="):
            out.append(f"ssid={new_ssid}")
            replaced = True
        else:
            out.append(p)
    if not replaced:
        out.append(f"ssid={new_ssid}")
    return "; ".join(out)


def get_storefront(shard, puuid, access_token, entitlements_token, client_version,
                   user_agent=DEFAULT_UA):
    # Current live endpoint (confirmed against a working 2025+ checker): the
    # store moved from v2-GET to v3-POST with an empty JSON body. The old
    # v2 GET now returns RESOURCE_NOT_FOUND.
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
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()
