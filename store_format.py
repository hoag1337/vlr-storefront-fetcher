"""Turn raw storefront JSON into a readable Telegram message. Skin names come
from valorant-api.com (static, no auth), cached to disk for a day."""

import json
import time
from pathlib import Path

import requests

import riot_auth as ra

SKINLEVELS_URL = "https://valorant-api.com/v1/weapons/skinlevels"
CACHE_PATH = Path("data/skins.json")
CACHE_TTL = 24 * 3600


def _load_skin_map():
    if CACHE_PATH.exists() and (time.time() - CACHE_PATH.stat().st_mtime) < CACHE_TTL:
        return json.loads(CACHE_PATH.read_text())
    resp = requests.get(SKINLEVELS_URL, timeout=20)
    resp.raise_for_status()
    mapping = {lvl["uuid"].lower(): lvl["displayName"] for lvl in resp.json()["data"]}
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(mapping))
    return mapping


def _vp(cost_map):
    return cost_map.get(ra.VP_CURRENCY_ID, next(iter(cost_map.values()), "?"))


def _name(skins, item_id):
    return skins.get(item_id.lower(), "Unknown skin")


def format_store(store: dict) -> str:
    skins = _load_skin_map()
    lines = []

    panel = store.get("SkinsPanelLayout", {})
    offers = panel.get("SingleItemStoreOffers", [])
    secs = panel.get("SingleItemOffersRemainingDurationInSeconds", 0)
    lines.append(f"🛒 DAILY STORE — resets in ~{secs // 3600}h")
    for offer in offers:
        item_id = offer["Rewards"][0]["ItemID"]
        lines.append(f"• {_name(skins, item_id)} — {_vp(offer['Cost'])} VP")

    night = store.get("BonusStore")
    if night:
        lines.append("\n🌙 NIGHT MARKET is live!")
        for bo in night["BonusStoreOffers"]:
            item_id = bo["Offer"]["Rewards"][0]["ItemID"]
            disc = _vp(bo["DiscountCosts"])
            base = _vp(bo["Offer"]["Cost"])
            pct = bo["DiscountPercent"]
            lines.append(f"• {_name(skins, item_id)} — {disc} VP (-{pct}%, was {base})")

    bundle = store.get("FeaturedBundle", {}).get("Bundle")
    if bundle:
        days = bundle.get("DurationRemainingInSeconds", 0) // 86400
        lines.append(f"\n📦 Featured bundle active — leaves in ~{days}d")

    return "\n".join(lines)
