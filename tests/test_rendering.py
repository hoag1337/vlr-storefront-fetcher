"""Message construction: Telegram's size cap, and price correctness."""

import unittest

from valstore.rendering import (
    MESSAGE_LIMIT,
    InventoryRenderer,
    StoreRenderer,
    chunk,
)
from valstore.riot.auth import RAD_CURRENCY_ID, VP_CURRENCY_ID

TIER_PREMIUM = "aaaaaaaa-0000-0000-0000-000000000002"
TIER_ULTRA = "aaaaaaaa-0000-0000-0000-000000000004"
TIER_SELECT = "aaaaaaaa-0000-0000-0000-000000000000"


class _Map:
    """Stands in for an AssetCatalog without touching the network or disk."""

    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, uuid, default=None):
        if not uuid:
            return default
        return self._mapping.get(uuid.lower(), default)


class _Catalogs:
    def __init__(self, names=None, levels=None, tiers=None):
        self.skin_names = _Map(names or {})
        self.skin_levels = _Map(levels or {})
        self.content_tiers = _Map(tiers or {})


class ChunkTest(unittest.TestCase):
    def test_short_input_is_one_message(self):
        self.assertEqual(chunk(["a", "b"]), ["a\nb"])

    def test_every_chunk_respects_the_limit(self):
        lines = [f"• Skin number {n}" for n in range(1200)]
        chunks = chunk(lines)
        self.assertGreater(len(chunks), 1)
        for part in chunks:
            self.assertLessEqual(len(part), MESSAGE_LIMIT)

    def test_no_line_is_split_across_messages(self):
        lines = [f"• Skin {n}" for n in range(1200)]
        rejoined = "\n".join(chunk(lines)).split("\n")
        self.assertEqual(rejoined, lines)

    def test_an_oversized_single_line_is_kept_whole(self):
        """Truncating a name would silently corrupt the list; emit it intact."""
        giant = "x" * (MESSAGE_LIMIT + 50)
        self.assertEqual(chunk([giant]), [giant])

    def test_empty_input(self):
        self.assertEqual(chunk([]), [])


class StoreRendererTest(unittest.TestCase):
    def setUp(self):
        self.catalogs = _Catalogs(names={"item-1": "Reaver Vandal"})
        self.renderer = StoreRenderer(self.catalogs)

    def _store(self, cost):
        return {"SkinsPanelLayout": {
            "SingleItemStoreOffers": [
                {"Rewards": [{"ItemID": "item-1"}], "Cost": cost}
            ],
            "SingleItemOffersRemainingDurationInSeconds": 7200,
        }}

    def test_vp_price_is_shown(self):
        text = "\n".join(self.renderer.render(self._store({VP_CURRENCY_ID: 1775})))
        self.assertIn("Reaver Vandal — 1775 VP", text)
        self.assertIn("resets in ~2h", text)

    def test_a_non_vp_price_is_not_reported_as_vp(self):
        """Radianite priced at 20 must never print as '20 VP'."""
        text = "\n".join(self.renderer.render(self._store({RAD_CURRENCY_ID: 20})))
        self.assertNotIn("20 VP", text)
        self.assertIn("price unavailable", text)

    def test_unknown_item_still_renders(self):
        store = {"SkinsPanelLayout": {
            "SingleItemStoreOffers": [
                {"Rewards": [{"ItemID": "not-in-catalog"}],
                 "Cost": {VP_CURRENCY_ID: 1}}
            ]}}
        self.assertIn("Unknown skin", "\n".join(self.renderer.render(store)))

    def test_malformed_payloads_do_not_raise(self):
        """Riot has reshaped this response before; none of it is assumed."""
        for payload in ({}, {"SkinsPanelLayout": None},
                        {"SkinsPanelLayout": {"SingleItemStoreOffers": [{}]}},
                        {"SkinsPanelLayout": {"SingleItemStoreOffers": [
                            {"Rewards": []}]}},
                        "not a dict", None):
            with self.subTest(payload=payload):
                self.assertTrue(self.renderer.render(payload))

    def test_night_market_and_bundle(self):
        store = {
            "SkinsPanelLayout": {"SingleItemStoreOffers": []},
            "BonusStore": {"BonusStoreOffers": [{
                "Offer": {"Rewards": [{"ItemID": "item-1"}],
                          "Cost": {VP_CURRENCY_ID: 1775}},
                "DiscountCosts": {VP_CURRENCY_ID: 900},
                "DiscountPercent": 49,
            }]},
            "FeaturedBundle": {"Bundle": {"DurationRemainingInSeconds": 172800}},
        }
        text = "\n".join(self.renderer.render(store))
        self.assertIn("NIGHT MARKET", text)
        self.assertIn("900 VP (-49%, was 1775 VP)", text)
        self.assertIn("leaves in ~2d", text)


class InventoryRendererTest(unittest.TestCase):
    def setUp(self):
        levels = {
            "lvl-1": {"skin": "Ultra Knife", "skin_uuid": "s1",
                      "tier_uuid": TIER_ULTRA},
            "lvl-1b": {"skin": "Ultra Knife", "skin_uuid": "s1",
                       "tier_uuid": TIER_ULTRA},
            "lvl-2": {"skin": "Premium Vandal", "skin_uuid": "s2",
                      "tier_uuid": TIER_PREMIUM},
            "lvl-3": {"skin": "Cheap Sheriff", "skin_uuid": "s3",
                      "tier_uuid": TIER_SELECT},
            "lvl-4": {"skin": "Plain Classic", "skin_uuid": "s4",
                      "tier_uuid": None},
        }
        tiers = {
            TIER_ULTRA: {"name": "Ultra Edition", "rank": 4},
            TIER_PREMIUM: {"name": "Premium Edition", "rank": 2},
            TIER_SELECT: {"name": "Select Edition", "rank": 0},
        }
        self.renderer = InventoryRenderer(_Catalogs(levels=levels, tiers=tiers))

    def test_multiple_levels_of_one_skin_count_once(self):
        skins, _ = self.renderer.collect(["lvl-1", "lvl-1b"])
        self.assertEqual([s["name"] for s in skins], ["Ultra Knife"])

    def test_below_premium_is_filtered_out(self):
        skins, _ = self.renderer.collect(["lvl-2", "lvl-3", "lvl-4"])
        self.assertEqual([s["name"] for s in skins], ["Premium Vandal"])

    def test_sorted_by_tier_then_name(self):
        skins, _ = self.renderer.collect(["lvl-2", "lvl-1"])
        self.assertEqual([s["name"] for s in skins],
                         ["Ultra Knife", "Premium Vandal"])

    def test_unknown_uuids_are_counted_not_dropped_silently(self):
        skins, unresolved = self.renderer.collect(["lvl-2", "brand-new-uuid"])
        self.assertEqual(len(skins), 1)
        self.assertEqual(unresolved, 1)

    def test_rendered_output_groups_and_counts(self):
        text = "\n".join(self.renderer.render(["lvl-1", "lvl-1b", "lvl-2"]))
        self.assertIn("2 owned", text)
        self.assertIn("Ultra Edition (1)", text)
        self.assertIn("Premium Edition (1)", text)

    def test_empty_inventory_says_so(self):
        text = "\n".join(self.renderer.render([]))
        self.assertIn("Nothing at Premium Edition or above", text)
