"""Static asset catalogs from valorant-api.com (public, no auth).

Every catalog needs the same thing: download a JSON document, reduce it to a
uuid -> value map, and keep it on disk so we don't refetch on every command.
That workflow lives once in AssetCatalog; a concrete catalog only declares
where to fetch from, where to cache, and how to reduce one API record.
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path

import requests

from valstore.errors import AssetUnavailable

log = logging.getLogger("valstore.assets")

CACHE_DIR = Path("data")
CACHE_TTL = 24 * 3600
HTTP_TIMEOUT = 20


class AssetCatalog(ABC):
    """uuid -> display data, fetched from valorant-api and cached to disk."""

    def __init__(self, cache_dir=CACHE_DIR, ttl=CACHE_TTL):
        self._cache_path = Path(cache_dir) / self.cache_name
        self._ttl = ttl
        self._map = None

    # ---- contract for concrete catalogs ----

    @property
    @abstractmethod
    def source_url(self):
        """valorant-api endpoint to download."""

    @property
    @abstractmethod
    def cache_name(self):
        """File name inside the cache directory."""

    @abstractmethod
    def build_map(self, records):
        """Reduce the API 'data' list to a JSON-serialisable uuid -> value map."""

    # ---- shared workflow ----

    def load(self):
        if self._map is None:
            self._map = self._read_cache(allow_stale=False) or self._refresh()
        return self._map

    def get(self, uuid, default=None):
        if not uuid:
            return default
        return self.load().get(uuid.lower(), default)

    def _read_cache(self, allow_stale):
        """Cached map, or None. A missing/corrupt/stale cache is not an error."""
        try:
            if not self._cache_path.exists():
                return None
            if not allow_stale:
                age = time.time() - self._cache_path.stat().st_mtime
                if age >= self._ttl:
                    return None
            return json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("Ignoring unreadable cache %s: %s", self._cache_path, exc)
            return None

    def _refresh(self):
        try:
            resp = requests.get(self.source_url, timeout=HTTP_TIMEOUT)
            resp.raise_for_status()
            records = resp.json().get("data") or []
            mapping = self.build_map(records)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            # Serving yesterday's names beats failing the whole command.
            stale = self._read_cache(allow_stale=True)
            if stale is not None:
                log.warning("Refresh of %s failed (%s); using stale cache.",
                            self.source_url, exc)
                return stale
            raise AssetUnavailable(
                f"Could not load {self.source_url} and no cache is available."
            ) from exc

        self._write_cache(mapping)
        return mapping

    def _write_cache(self, mapping):
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps(mapping), encoding="utf-8")
        except OSError as exc:
            # A read-only disk should not break an otherwise successful fetch.
            log.warning("Could not write cache %s: %s", self._cache_path, exc)


class ContentTierCatalog(AssetCatalog):
    """Tier uuid -> {name, rank}. Rank orders the editions: Select 0, Deluxe 1,
    Premium 2, Exclusive 3, Ultra 4."""

    source_url = "https://valorant-api.com/v1/contenttiers"
    cache_name = "content_tiers.json"

    def build_map(self, records):
        return {
            tier["uuid"].lower(): {
                "name": tier.get("displayName") or tier.get("devName") or "Unknown",
                "rank": tier["rank"],
            }
            for tier in records
            if tier.get("uuid") and tier.get("rank") is not None
        }


class SkinLevelCatalog(AssetCatalog):
    """Skin-level uuid -> {skin, skin_uuid, tier_uuid}.

    Entitlements hand back the *level* uuids a player owns, but the content
    tier hangs off the parent skin — so every level is indexed back to its
    skin. Standard weapons carry no tier and map to tier_uuid None.
    """

    source_url = "https://valorant-api.com/v1/weapons/skins"
    cache_name = "skin_levels.json"

    def build_map(self, records):
        mapping = {}
        for skin in records:
            skin_uuid = skin.get("uuid")
            if not skin_uuid:
                continue
            tier_uuid = skin.get("contentTierUuid")
            entry = {
                "skin": skin.get("displayName") or "Unknown skin",
                "skin_uuid": skin_uuid.lower(),
                "tier_uuid": tier_uuid.lower() if tier_uuid else None,
            }
            for level in skin.get("levels") or []:
                level_uuid = level.get("uuid")
                if level_uuid:
                    mapping[level_uuid.lower()] = entry
        return mapping


class SkinNameCatalog(AssetCatalog):
    """Skin-level uuid -> display name, for storefront offers.

    The storefront names offers by skin *level*, so this is a flat name lookup
    rather than SkinLevelCatalog's tier-aware index. It replaces the hand-rolled
    cache that used to live in store_format, and so inherits the stale-cache
    fallback that one lacked.
    """

    source_url = "https://valorant-api.com/v1/weapons/skinlevels"
    cache_name = "skins.json"

    def build_map(self, records):
        return {
            level["uuid"].lower(): level.get("displayName") or "Unknown skin"
            for level in records
            if level.get("uuid")
        }


class Catalogs:
    """The catalogs the render layer needs, constructed once and injected.

    Previously these were module-level globals in inventory_format, which made
    them impossible to substitute in a test and gave each importer its own cache.
    """

    def __init__(self, cache_dir=CACHE_DIR, ttl=CACHE_TTL):
        self.content_tiers = ContentTierCatalog(cache_dir, ttl)
        self.skin_levels = SkinLevelCatalog(cache_dir, ttl)
        self.skin_names = SkinNameCatalog(cache_dir, ttl)

    def skin_uuid_to_name(self) -> dict:
        """Skin uuid -> display name, deduplicated across levels.

        skin_levels is keyed by level uuid with several levels sharing one
        parent skin; this collapses it to the one lookup a wishlist actually
        needs (by skin, not by level).
        """
        return {
            level["skin_uuid"]: level["skin"]
            for level in self.skin_levels.load().values()
        }

    def search_skins(self, query: str, limit: int = 10) -> list:
        """(skin_uuid, name) pairs whose name contains query, case-insensitive.

        There is no name -> uuid index in the raw catalogs (they're all keyed
        by uuid), so this builds the search index. valorant-api.com has a
        few thousand skin levels at most, so a linear scan needs no caching.
        """
        needle = query.strip().lower()
        if not needle:
            return []
        hits = [
            (uuid, name)
            for uuid, name in self.skin_uuid_to_name().items()
            if needle in name.lower()
        ]
        hits.sort(key=lambda pair: pair[1].lower())
        return hits[:limit]
