"""Catalog caching: a Riot/valorant-api outage must degrade, not fail."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from valstore.assets import AssetCatalog
from valstore.errors import AssetUnavailable


class _Unreachable(AssetCatalog):
    """Points at a host that cannot resolve, so _refresh always fails."""

    source_url = "https://valorant-api.invalid/v1/nothing"
    cache_name = "unreachable.json"

    def build_map(self, records):  # pragma: no cover - never reached
        return {}


class StaleCacheTest(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.dir = Path(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def _write_cache(self, payload, age_seconds):
        path = self.dir / "unreachable.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        old = time.time() - age_seconds
        os.utime(path, (old, old))
        return path

    def test_stale_cache_is_served_when_refresh_fails(self):
        """Yesterday's skin names beat failing the whole command."""
        self._write_cache({"abc": "Yesterday's Vandal"}, age_seconds=48 * 3600)

        catalog = _Unreachable(cache_dir=self.dir, ttl=3600)

        self.assertEqual(catalog.get("abc"), "Yesterday's Vandal")

    def test_fresh_cache_is_used_without_any_fetch(self):
        self._write_cache({"abc": "Fresh Vandal"}, age_seconds=10)
        catalog = _Unreachable(cache_dir=self.dir, ttl=3600)
        self.assertEqual(catalog.get("abc"), "Fresh Vandal")

    def test_no_cache_and_no_network_is_an_explicit_error(self):
        catalog = _Unreachable(cache_dir=self.dir, ttl=3600)
        with self.assertRaises(AssetUnavailable):
            catalog.load()

    def test_a_corrupt_cache_is_ignored_rather_than_crashing(self):
        path = self.dir / "unreachable.json"
        path.write_text("{not json", encoding="utf-8")
        catalog = _Unreachable(cache_dir=self.dir, ttl=3600)
        with self.assertRaises(AssetUnavailable):
            catalog.load()

    def test_lookup_is_case_insensitive_and_tolerates_none(self):
        self._write_cache({"abc": "Vandal"}, age_seconds=10)
        catalog = _Unreachable(cache_dir=self.dir, ttl=3600)
        self.assertEqual(catalog.get("ABC"), "Vandal")
        self.assertIsNone(catalog.get(None))
        self.assertEqual(catalog.get("missing", "fallback"), "fallback")
