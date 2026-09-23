"""Turning Riot payloads into Telegram messages.

Both renderers take their catalogs by injection rather than reaching for module
globals, so a test can hand them a fixed map and assert on exact output without
a network or a cache directory.
"""

import logging

from valstore.riot.auth import VP_CURRENCY_ID

log = logging.getLogger("valstore.rendering")

# Telegram hard-caps a message at 4096 characters; leave room for the header.
MESSAGE_LIMIT = 3500

# Select 0, Deluxe 1, Premium 2, Exclusive 3, Ultra 4.
PREMIUM_RANK = 2

UNKNOWN_SKIN = "Unknown skin"


def chunk(lines, limit=MESSAGE_LIMIT):
    """Pack lines into messages under limit, never splitting a line.

    A single line longer than the limit is still emitted whole: truncating a
    skin name mid-word would be worse than one oversized message, and Telegram
    rejects it loudly rather than silently corrupting the list.
    """
    chunks, current = [], ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit and current:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


class StoreRenderer:
    """The daily shop, the night market, and whether a bundle is up."""

    def __init__(self, catalogs):
        self._names = catalogs.skin_names

    def _name(self, item_id):
        return self._names.get(item_id, UNKNOWN_SKIN) if item_id else UNKNOWN_SKIN

    @staticmethod
    def _vp(cost_map):
        """Valorant Points for an offer, or None.

        Deliberately does not fall back to 'whatever currency is first': bundles
        are priced in Radianite too, and printing that number beside a VP label
        silently misreports the price.
        """
        if not isinstance(cost_map, dict):
            return None
        return cost_map.get(VP_CURRENCY_ID)

    @classmethod
    def _price(cls, cost_map):
        vp = cls._vp(cost_map)
        return f"{vp} VP" if vp is not None else "price unavailable"

    @staticmethod
    def _first_reward_id(offer):
        """Item id of an offer, tolerating a missing or reshaped Rewards list."""
        if not isinstance(offer, dict):
            return None
        rewards = offer.get("Rewards")
        if not isinstance(rewards, list) or not rewards:
            return None
        first = rewards[0]
        return first.get("ItemID") if isinstance(first, dict) else None

    def render(self, store):
        if not isinstance(store, dict):
            return ["Riot returned an unreadable store. Try again shortly."]

        lines = []
        panel = store.get("SkinsPanelLayout") or {}
        offers = panel.get("SingleItemStoreOffers") or []
        secs = panel.get("SingleItemOffersRemainingDurationInSeconds") or 0
        lines.append(f"🛒 DAILY STORE — resets in ~{secs // 3600}h")
        for offer in offers:
            item_id = self._first_reward_id(offer)
            lines.append(f"• {self._name(item_id)} — "
                         f"{self._price(offer.get('Cost'))}")

        night = store.get("BonusStore") or {}
        bonus_offers = night.get("BonusStoreOffers") or []
        if bonus_offers:
            lines.append("\n🌙 NIGHT MARKET is live!")
            for bonus in bonus_offers:
                if not isinstance(bonus, dict):
                    continue
                inner = bonus.get("Offer") or {}
                item_id = self._first_reward_id(inner)
                disc = self._price(bonus.get("DiscountCosts"))
                base = self._price(inner.get("Cost"))
                pct = bonus.get("DiscountPercent", 0)
                lines.append(f"• {self._name(item_id)} — {disc} "
                             f"(-{pct}%, was {base})")

        bundle = (store.get("FeaturedBundle") or {}).get("Bundle")
        if isinstance(bundle, dict):
            days = (bundle.get("DurationRemainingInSeconds") or 0) // 86400
            lines.append(f"\n📦 Featured bundle active — leaves in ~{days}d")

        return chunk(lines)


class InventoryRenderer:
    """Owned skins at Premium Edition or above, grouped by tier."""

    def __init__(self, catalogs):
        self._skin_levels = catalogs.skin_levels
        self._content_tiers = catalogs.content_tiers

    def collect(self, level_ids, min_rank=PREMIUM_RANK):
        """Owned skins at or above min_rank, de-duplicated by skin.

        A player owns each *level* they have unlocked, so one skin can appear
        several times; group by the parent skin and keep it once.

        Returns (skins, unresolved) where skins is sorted by tier descending
        then name, and unresolved counts uuids valorant-api does not know yet.
        """
        by_skin = {}
        unresolved = 0

        for level_id in level_ids:
            level = self._skin_levels.get(level_id)
            if not level:
                unresolved += 1
                continue

            tier = self._content_tiers.get(level.get("tier_uuid"))
            if not tier:
                # Standard weapons have no tier at all; a genuinely new tier
                # would also land here, so make that visible rather than silent.
                if level.get("tier_uuid"):
                    log.warning("Unknown content tier %s on skin %s",
                                level["tier_uuid"], level.get("skin"))
                continue

            if tier["rank"] < min_rank:
                continue

            by_skin[level["skin_uuid"]] = {
                "name": level["skin"],
                "tier": tier["name"],
                "rank": tier["rank"],
            }

        skins = sorted(by_skin.values(),
                       key=lambda s: (-s["rank"], s["name"].lower()))
        return skins, unresolved

    def render(self, level_ids, min_rank=PREMIUM_RANK):
        skins, unresolved = self.collect(level_ids, min_rank)

        # level_ids counts unlocked *levels*, not skins, so it would not be a
        # meaningful denominator here.
        header = f"🎒 PREMIUM+ SKINS — {len(skins)} owned"
        if not skins:
            return [f"{header}\n\nNothing at Premium Edition or above."]

        counts = {}
        for skin in skins:
            counts[skin["tier"]] = counts.get(skin["tier"], 0) + 1

        lines = [header]
        current_tier = None
        for skin in skins:
            if skin["tier"] != current_tier:
                current_tier = skin["tier"]
                lines.append(f"\n{current_tier} ({counts[current_tier]})")
            lines.append(f"• {skin['name']}")

        if unresolved:
            lines.append(f"\n({unresolved} item(s) too new to identify)")

        return chunk(lines)
