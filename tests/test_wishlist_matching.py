"""StorefrontSkins: which wishlisted skins are visible, from a raw payload."""

import unittest

from valstore.wishlist.matching import WEAPON_SKIN_LEVEL_TYPE_ID, StorefrontSkins


class _Map:
    """Stands in for SkinLevelCatalog without touching the network or disk."""

    def __init__(self, mapping):
        self._mapping = mapping

    def get(self, uuid, default=None):
        if not uuid:
            return default
        return self._mapping.get(uuid.lower(), default)


LEVELS = {
    "lvl-1": {"skin": "Reaver Vandal", "skin_uuid": "skin-reaver-vandal"},
    "lvl-2": {"skin": "Prime Phantom", "skin_uuid": "skin-prime-phantom"},
}


class StorefrontSkinsTest(unittest.TestCase):
    def setUp(self):
        self.extractor = StorefrontSkins(_Map(LEVELS))

    def test_daily_resolves_level_to_skin_uuid(self):
        store = {"SkinsPanelLayout": {"SingleItemStoreOffers": [
            {"Rewards": [{"ItemID": "lvl-1"}]},
        ]}}
        self.assertEqual(self.extractor.daily(store), {"skin-reaver-vandal"})

    def test_daily_ignores_offers_for_unknown_levels(self):
        store = {"SkinsPanelLayout": {"SingleItemStoreOffers": [
            {"Rewards": [{"ItemID": "not-in-catalog"}]},
        ]}}
        self.assertEqual(self.extractor.daily(store), set())

    def test_night_market_reads_the_inner_offer(self):
        store = {"BonusStore": {"BonusStoreOffers": [
            {"Offer": {"Rewards": [{"ItemID": "lvl-2"}]}, "DiscountPercent": 30},
        ]}}
        self.assertEqual(self.extractor.night_market(store), {"skin-prime-phantom"})

    def test_bundle_matches_only_weapon_skin_items(self):
        store = {"FeaturedBundle": {"Bundle": {"Items": [
            {"Item": {"ItemTypeID": WEAPON_SKIN_LEVEL_TYPE_ID, "ItemID": "lvl-1"}},
            {"Item": {"ItemTypeID": "some-other-type-id", "ItemID": "lvl-2"}},
        ]}}}
        self.assertEqual(self.extractor.bundle(store), {"skin-reaver-vandal"})

    def test_all_sources_combines_the_three(self):
        store = {
            "SkinsPanelLayout": {"SingleItemStoreOffers": [
                {"Rewards": [{"ItemID": "lvl-1"}]}]},
            "BonusStore": {"BonusStoreOffers": [
                {"Offer": {"Rewards": [{"ItemID": "lvl-2"}]}}]},
            "FeaturedBundle": {"Bundle": {"Items": [
                {"Item": {"ItemTypeID": WEAPON_SKIN_LEVEL_TYPE_ID,
                          "ItemID": "lvl-1"}}]}},
        }
        result = self.extractor.all_sources(store)
        self.assertEqual(result["daily"], {"skin-reaver-vandal"})
        self.assertEqual(result["night_market"], {"skin-prime-phantom"})
        self.assertEqual(result["bundle"], {"skin-reaver-vandal"})

    def test_malformed_payloads_do_not_raise(self):
        """Riot has reshaped this response before; none of it is assumed."""
        for payload in (
            {},
            {"SkinsPanelLayout": None},
            {"SkinsPanelLayout": {"SingleItemStoreOffers": [{}]}},
            {"SkinsPanelLayout": {"SingleItemStoreOffers": [{"Rewards": []}]}},
            {"BonusStore": None},
            {"BonusStore": {"BonusStoreOffers": [{}]}},
            {"BonusStore": {"BonusStoreOffers": ["not a dict"]}},
            {"FeaturedBundle": None},
            {"FeaturedBundle": {"Bundle": None}},
            {"FeaturedBundle": {"Bundle": {"Items": "not a list"}}},
            {"FeaturedBundle": {"Bundle": {"Items": [{"Item": None}]}}},
            {"FeaturedBundle": {"Bundle": {"Items": [
                {"Item": {"ItemTypeID": None, "ItemID": "lvl-1"}}]}}},
            "not a dict",
            None,
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.extractor.all_sources(payload),
                                 {"daily": set(), "night_market": set(),
                                  "bundle": set()})
