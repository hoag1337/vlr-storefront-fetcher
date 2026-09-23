"""The fragile joint of the whole project: ssid cookie -> access token.

Chain: ssid cookie -> access token -> entitlements token -> puuid -> storefront

Nothing here stores or logs secrets. The caller owns the ssid.
"""

import base64
import json
import urllib.parse

import requests

from valstore.errors import CloudflareBlock, ReauthError

__all__ = [
    "CLIENT_PLATFORM", "DEFAULT_UA", "VP_CURRENCY_ID", "RAD_CURRENCY_ID",
    "ReauthError", "CloudflareBlock",
    "reauth", "get_entitlement", "puuid_from_token", "get_client_version",
    "get_live_shard", "replace_ssid",
]

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
GEO_URL = "https://riot-geo.pas.si.riotgames.com/pas/v1/product/valorant"
AUTH_COOKIE_DOMAIN = "auth.riotgames.com"

# Valorant Points currency UUID (the price you actually care about).
VP_CURRENCY_ID = "85ad13f7-3d1b-5128-9eb2-7cd8ee0b5741"
RAD_CURRENCY_ID = "e59aa87c-4cbf-517a-5983-6e81511be9b7"  # Radianite (bundles)

# A plain browser UA. Riot's web auth endpoint is behind Cloudflare; sending a
# believable UA is what usually keeps the captcha from firing.
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

HTTP_TIMEOUT = 15


def _looks_like_cloudflare(resp):
    body = resp.text.lower()
    markers = ("cloudflare", "cf-ray", "attention required", "cf-chl", "just a moment")
    ct = resp.headers.get("Content-Type", "")
    return "text/html" in ct and any(m in body for m in markers)


def _extract_ssid(jar):
    """Rotated ssid from a cookie jar, preferring the auth domain.

    requests' cookies.get() raises CookieConflictError when more than one domain
    set a cookie of the same name, which is a real possibility across the auth
    redirect chain. Resolving the domain explicitly avoids turning a successful
    login into an exception.
    """
    candidates = [c for c in jar if c.name == "ssid"]
    if not candidates:
        return None
    for cookie in candidates:
        if cookie.domain and AUTH_COOKIE_DOMAIN in cookie.domain:
            return cookie.value
    return candidates[0].value


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
    try:
        resp = session.get(
            REAUTH_URL,
            headers={"User-Agent": user_agent, "Cookie": cookie_value},
            allow_redirects=False,
            timeout=HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise ReauthError(f"Could not reach Riot's auth service: {exc}") from exc

    if _looks_like_cloudflare(resp):
        raise CloudflareBlock(
            "Cloudflare challenged the reauth request (status "
            f"{resp.status_code})."
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
        dest = (f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
                if location else "(no Location header)")

        if err:
            raise ReauthError(
                f"Riot returned error='{err}' (HTTP {resp.status_code}). Usually a "
                "session that isn't valid for the valorant web client."
            )
        if "login" in parsed.path.lower() or "auth" in parsed.path.lower():
            raise ReauthError(
                f"Redirect went to {dest} instead of playvalorant.com — the session "
                f"was NOT recognized (HTTP {resp.status_code})."
            )
        raise ReauthError(
            f"No access_token in redirect. Destination: {dest} "
            f"(HTTP {resp.status_code})."
        )

    return access_token, id_token, _extract_ssid(session.cookies)


def get_entitlement(access_token, user_agent=DEFAULT_UA):
    resp = requests.post(
        ENTITLEMENT_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": user_agent,
        },
        json={},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    token = payload.get("entitlements_token") if isinstance(payload, dict) else None
    if not token:
        raise ReauthError("Riot did not return an entitlements token.")
    return token


def _decode_jwt_payload(token):
    """Claims from a JWT we did not mint, so the signature is intentionally not
    verified — we only ever read identifiers Riot already gave us."""
    parts = token.split(".")
    if len(parts) < 2:
        raise ReauthError("Malformed token from Riot.")
    segment = parts[1] + "=" * (-len(parts[1]) % 4)  # fix base64 padding
    try:
        return json.loads(base64.urlsafe_b64decode(segment))
    except (ValueError, TypeError) as exc:
        raise ReauthError("Could not read Riot's token payload.") from exc


def puuid_from_token(access_token):
    """The access token is a JWT; its 'sub' claim is the PUUID. No extra call."""
    payload = _decode_jwt_payload(access_token)
    puuid = payload.get("sub")
    if not puuid:
        raise ReauthError("Riot's token carried no account id.")
    return puuid


def get_client_version():
    resp = requests.get(VERSION_URL, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    data = resp.json().get("data") or {}
    version = data.get("riotClientVersion")
    if not version:
        raise ReauthError("valorant-api did not report a client version.")
    return version


def get_live_shard(access_token, id_token, user_agent=DEFAULT_UA):
    """Authoritative shard from Riot's geo service. Returns 'na'/'eu'/'ap'/'kr'."""
    resp = requests.put(
        GEO_URL,
        headers={"Authorization": f"Bearer {access_token}", "User-Agent": user_agent},
        json={"id_token": id_token},
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    payload = _decode_jwt_payload(resp.text)
    shard = (payload.get("affinities") or {}).get("live")
    if not shard:
        raise ReauthError("Riot's geo service did not report a shard.")
    return shard


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
