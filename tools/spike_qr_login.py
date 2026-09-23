"""
PHASE 2 SPIKE — is Riot's QR / login-URL flow usable by this bot?

Run this against your OWN Riot account. It answers three questions, in order:

  1. Does Riot still hand a third party a QR login session at all?
  2. Does approving it on the phone return a durable `ssid` cookie, or only a
     short-lived access token?
  3. Does the resulting cookie work with this project's existing Riot chain?

Question 3 is the one that matters: if the cookie validates through
valstore.riot.session.validate, then a QR LinkMethod is a drop-in and nothing
downstream changes.

    python tools/spike_qr_login.py              # diagnose only
    python tools/spike_qr_login.py --link       # ...and link it to OWNER_ID

Nothing secret is printed. Cookie values are reported by length only.

Endpoint shapes follow RadiantConnect's QR sign-in implementation, which is the
maintained reference for this undocumented flow. They are Riot's own first-party
`riot-client` calls, so treat breakage as expected rather than surprising.
"""

import argparse
import json
import secrets
import sys
import time
import urllib.parse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from valstore.errors import ValstoreError  # noqa: E402

SDK_VERSION = "24.11.0.4602"
CLIENT_ID = "riot-client"

LOGIN_URL = "https://authenticate.riotgames.com/api/v1/login"
LOGIN_TOKEN_URL = "https://auth.riotgames.com/api/v1/login-token"
AUTHORIZATION_URL = "https://auth.riotgames.com/api/v1/authorization"
QR_TEMPLATE = (
    "https://qrlogin.riotgames.com/riotmobile"
    "?cluster={cluster}&suuid={suuid}&timestamp={timestamp}"
    "&utm_source=riotclient&utm_medium=client&utm_campaign=qrlogin-riotmobile"
)
QR_IMAGE = "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={data}"

# Riot's own cookie set; the project's chain wants them as one header.
WANTED_COOKIES = ("ssid", "tdid", "csid", "clid")

TIMEOUT = 20


def _ua(service: str) -> str:
    return (f"RiotGamesApi/{SDK_VERSION} {service} "
            "(Windows;10;;Professional, x64) riot_client/0")


def _traceparent() -> str:
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


def _headers(host: str, service: str, sdk_sid: str) -> dict:
    return {
        "Host": host,
        "User-Agent": _ua(service),
        "Accept": "application/json",
        "Accept-Encoding": "deflate, gzip, zstd",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "baggage": f"sdksid={sdk_sid}",
        "traceparent": _traceparent(),
    }


def _say(step: str, detail: str = "") -> None:
    print(f"  {step:<34} {detail}")


def start_qr_session(session, sdk_sid, persist):
    """Ask Riot for a QR login session. Returns the Stage-3 payload."""
    body = {
        "client_id": CLIENT_ID,
        "language": "en_US",
        "platform": "windows",
        "remember": persist,
        "type": "auth",
        "qrcode": {},
        "sdkVersion": SDK_VERSION,
        # Every other sign-in method must be explicitly absent.
        "apple": None, "campaign": None, "code": None, "facebook": None,
        "gamecenter": None, "google": None, "mockDeviceId": None,
        "mockPlatform": None, "multifactor": None, "nintendo": None,
        "playstation": None, "riot_identity": None,
        "riot_identity_signup": None, "rso": None, "xbox": None,
    }
    resp = session.post(
        LOGIN_URL,
        headers=_headers("authenticate.riotgames.com", "rso-authenticator", sdk_sid),
        json=body,
        timeout=TIMEOUT,
    )
    _say("POST /api/v1/login", f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        raise SystemExit(
            f"\n  VERDICT: Riot refused to open a QR session (HTTP "
            f"{resp.status_code}).\n  Body: {resp.text[:400]}"
        )
    payload = resp.json()
    _say("response keys", ", ".join(sorted(payload)))
    if payload.get("captcha"):
        _say("note", "response carries a captcha block (may not be required)")
    return payload


def poll_for_approval(session, sdk_sid, timeout_seconds):
    """Poll until the user approves on their phone. Returns the success block."""
    deadline = time.time() + timeout_seconds
    last_type = None
    while time.time() < deadline:
        resp = session.get(
            LOGIN_URL,
            headers=_headers("authenticate.riotgames.com", "rso-authenticator",
                             sdk_sid),
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            _say("poll", f"HTTP {resp.status_code} — {resp.text[:120]}")
            time.sleep(2)
            continue

        try:
            payload = resp.json()
        except ValueError:
            time.sleep(2)
            continue

        kind = payload.get("type")
        if kind != last_type:
            _say("poll", f"type={kind}   (waiting for approval…)")
            last_type = kind

        if payload.get("success"):
            return payload["success"]
        time.sleep(2)

    raise SystemExit("\n  VERDICT: timed out waiting for approval on the phone.")


def exchange_for_session(session, sdk_sid, login_token, persist):
    """Turn the approved login token into Riot cookies."""
    resp = session.post(
        LOGIN_TOKEN_URL,
        headers={**_headers("auth.riotgames.com", "rso-auth", sdk_sid),
                 "Cache-Control": "no-cache"},
        json={
            "authentication_type": None,
            "code_verifier": "",
            "login_token": login_token,
            # The question this spike exists to answer.
            "persist_login": persist,
        },
        timeout=TIMEOUT,
    )
    _say("POST /api/v1/login-token", f"HTTP {resp.status_code}")
    if resp.status_code not in (200, 204):
        raise SystemExit(f"  Body: {resp.text[:400]}")

    resp = session.post(
        AUTHORIZATION_URL,
        headers=_headers("auth.riotgames.com", "rso-auth", sdk_sid),
        json={
            "acr_values": "",
            "claims": "",
            "client_id": CLIENT_ID,
            "code_challenge": "",
            "code_challenge_method": "",
            "nonce": secrets.token_urlsafe(16),
            "redirect_uri": "http://localhost/redirect",
            "response_type": "token id_token",
            "scope": "openid link lol_region lol summoner offline_access ban",
        },
        timeout=TIMEOUT,
    )
    _say("POST /api/v1/authorization", f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        raise SystemExit(f"  Body: {resp.text[:400]}")
    return resp.json()


def collect_cookies(session):
    """The cookie header this project's chain already accepts."""
    found = {}
    for cookie in session.cookies:
        if cookie.name in WANTED_COOKIES and cookie.name not in found:
            found[cookie.name] = cookie.value
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=180,
                        help="seconds to wait for phone approval (default 180)")
    parser.add_argument("--no-persist", action="store_true",
                        help="ask for a non-persistent session, to compare")
    parser.add_argument("--link", action="store_true",
                        help="on success, link the account to OWNER_ID")
    args = parser.parse_args()
    persist = not args.no_persist

    session = requests.Session()
    sdk_sid = secrets.token_hex(16)

    print("\n=== STAGE 1: open a QR login session ===")
    stage3 = start_qr_session(session, sdk_sid, persist)

    missing = [k for k in ("suuid", "cluster", "timestamp") if not stage3.get(k)]
    if missing:
        raise SystemExit(
            f"\n  VERDICT: no QR session returned (missing {missing}).\n"
            f"  Payload: {json.dumps(stage3)[:400]}"
        )

    login_url = QR_TEMPLATE.format(cluster=stage3["cluster"],
                                   suuid=stage3["suuid"],
                                   timestamp=stage3["timestamp"])

    print("\n=== STAGE 2: approve on your phone ===")
    print("\n  Open this on the phone (it should hand off to Riot Mobile):\n")
    print(f"    {login_url}\n")
    print("  Or scan this QR image with the Riot Mobile app:\n")
    print(f"    {QR_IMAGE.format(data=urllib.parse.quote(login_url, safe=''))}\n")
    print(f"  Waiting up to {args.timeout}s…\n")

    success = poll_for_approval(session, sdk_sid, args.timeout)
    _say("approved", f"puuid={'yes' if success.get('puuid') else 'no'}, "
                     f"auth_method={success.get('auth_method')}")

    login_token = success.get("login_token")
    if not login_token:
        raise SystemExit("\n  VERDICT: approval returned no login_token.")

    print("\n=== STAGE 3: exchange for a session ===")
    exchange_for_session(session, sdk_sid, login_token, persist)
    cookies = collect_cookies(session)

    for name in WANTED_COOKIES:
        value = cookies.get(name)
        _say(f"cookie {name}", f"{len(value)} chars" if value else "ABSENT")

    print("\n=== VERDICT ===\n")
    if not cookies.get("ssid"):
        print("  ✗ No ssid cookie. This flow cannot feed the existing chain,")
        print("    so the fallback (tap Riot's link, paste the redirect) stands.")
        return 1

    cookie_header = "; ".join(f"{k}={cookies[k]}"
                              for k in WANTED_COOKIES if k in cookies)
    print("  ✓ Got an ssid cookie — the same shape the bot already stores.")

    print("\n  Validating it through the project's own chain…")
    from valstore.riot.session import validate
    try:
        shard, identity = validate(cookie_header)
    except ValstoreError as exc:
        print(f"  ✗ The cookie did not validate: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - spike: report anything
        print(f"  ✗ Unexpected failure validating: {type(exc).__name__}: {exc}")
        return 1

    print(f"  ✓ Validated: {identity.display_name} on shard '{shard}'.")
    print("\n  => A QR LinkMethod is a drop-in. Nothing downstream changes.")
    print("     Durability: re-run tomorrow; if it still validates, the session")
    print(f"     persists (this run used persist_login={persist}).")

    if args.link:
        from valstore import config
        from valstore.models import LinkResult
        from valstore.repository import SqliteAccountRepository
        from valstore.service import AccountService

        cfg = config.load()
        if cfg.owner_id is None:
            print("\n  --link needs OWNER_ID set in .env; skipped.")
            return 0
        repo = SqliteAccountRepository(cfg.db_path)
        accounts = AccountService(repo, cfg.at_rest_key, cfg.max_accounts_per_user)
        account, relinked = accounts.link(
            cfg.owner_id,
            LinkResult(cookie_header=cookie_header, shard=shard, identity=identity),
        )
        verb = "Refreshed" if relinked else "Linked"
        print(f"\n  {verb} '{account.title}' for Telegram id {cfg.owner_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
