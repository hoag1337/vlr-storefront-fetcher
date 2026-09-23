"""Which wishlisted skins are visible right now, from a raw storefront payload.

Pure and I/O-free on purpose, like rendering.StoreRenderer: give it a dict and
a skin_levels catalog, get back skin uuids, so the watcher's polling loop can
be tested without a network call or a Telegram bot.
"""

import logging

log = logging.getLogger("valstore.wishlist.matching")

DAILY = "daily"
NIGHT_MARKET = "night_market"
BUNDLE = "bundle"

# Riot's well-known item-type id for an equippable weapon skin level. Bundles
# mix skins with buddies/sprays/cards/titles, so this is what separates them.
# Not exercised by this codebase before this feature — verify against one real
# FeaturedBundle payload (see the wishlist plan's verification notes) before
# relying on it in production.
WEAPON_SKIN_LEVEL_TYPE_ID = "e7c63390-eda7-46e0-bb7a-a6abdacd2433"


class StorefrontSkins:
    """Extracts the skin uuids on offer in each shop section."""

    def __init__(self, skin_levels_catalog):
        self._skin_levels = skin_levels_catalog

    def _skin_uuid(self, level_id):
        """Parent skin uuid for a level uuid, tolerating an unresolvable one."""
        if not level_id:
            return None
        level = self._skin_levels.get(level_id)
        return level.get("skin_uuid") if level else None

    @staticmethod
    def _first_reward_id(offer):
        """Item id of an offer. Mirrors rendering.StoreRenderer._first_reward_id
        so the two stay in agreement about the payload's shape."""
        if not isinstance(offer, dict):
            return None
        rewards = offer.get("Rewards")
        if not isinstance(rewards, list) or not rewards:
            return None
        first = rewards[0]
        return first.get("ItemID") if isinstance(first, dict) else None

    def daily(self, store: dict) -> set[str]:
        if not isinstance(store, dict):
            return set()
        panel = store.get("SkinsPanelLayout") or {}
        offers = panel.get("SingleItemStoreOffers") or []
        uuids = (self._skin_uuid(self._first_reward_id(o)) for o in offers)
        return {u for u in uuids if u}

    def night_market(self, store: dict) -> set[str]:
        if not isinstance(store, dict):
            return set()
        night = store.get("BonusStore") or {}
        offers = night.get("BonusStoreOffers") or []
        uuids = set()
        for bonus in offers:
            if not isinstance(bonus, dict):
                continue
            inner = bonus.get("Offer") or {}
            uuid = self._skin_uuid(self._first_reward_id(inner))
            if uuid:
                uuids.add(uuid)
        return uuids

    def bundle(self, store: dict) -> set[str]:
        if not isinstance(store, dict):
            return set()
        bundle = (store.get("FeaturedBundle") or {}).get("Bundle")
        if not isinstance(bundle, dict):
            return set()
        items = bundle.get("Items")
        if not isinstance(items, list):
            return set()

        uuids = set()
        for entry in items:
            if not isinstance(entry, dict):
                continue
            item = entry.get("Item")
            if not isinstance(item, dict):
                continue
            if (item.get("ItemTypeID") or "").lower() != WEAPON_SKIN_LEVEL_TYPE_ID:
                continue
            uuid = self._skin_uuid(item.get("ItemID"))
            if uuid:
                uuids.add(uuid)
        return uuids

    def all_sources(self, store: dict) -> dict[str, set[str]]:
        return {
            DAILY: self.daily(store),
            NIGHT_MARKET: self.night_market(store),
            BUNDLE: self.bundle(store),
        }
