"""What handlers call to manage a wishlist. No SQL and no Riot logic here."""

from dataclasses import dataclass

from valstore.errors import WishlistLimitReached
from valstore.wishlist.models import WishlistItem


@dataclass(frozen=True)
class WishlistEntry:
    """A wishlist row, with its skin name already resolved for display."""

    item_id: int
    skin_uuid: str
    name: str


class WishlistService:
    """Add, remove, list, and search — the wishlist's whole lifecycle."""

    def __init__(self, repository, catalogs, max_items: int):
        self._repo = repository
        self._catalogs = catalogs
        self._max_items = max_items

    def list_items(self, telegram_id: int) -> list[WishlistEntry]:
        names = self._catalogs.skin_uuid_to_name()
        return [
            WishlistEntry(
                item_id=item.id,
                skin_uuid=item.skin_uuid,
                name=names.get(item.skin_uuid, "Unknown skin"),
            )
            for item in self._repo.list_for(telegram_id)
        ]

    def search(self, query: str, limit: int = 10) -> list[tuple[str, str]]:
        """(skin_uuid, name) pairs matching query, for the "add a skin" picker."""
        return self._catalogs.search_skins(query, limit=limit)

    def name_for(self, skin_uuid: str) -> str:
        return self._catalogs.skin_uuid_to_name().get(skin_uuid, "Unknown skin")

    def at_capacity(self, telegram_id: int) -> bool:
        return self._repo.count_for(telegram_id) >= self._max_items

    def add(self, telegram_id: int, skin_uuid: str) -> tuple[WishlistItem, bool]:
        """Returns (item, was_new). A repeat add is a no-op, never an error.

        The cap only blocks a genuinely new skin — same reasoning as
        AccountService.link(): someone already at the limit must still be
        able to no-op on a skin they already wishlisted.
        """
        already = skin_uuid in self._repo.skin_uuids_for(telegram_id)
        if not already and self._repo.count_for(telegram_id) >= self._max_items:
            raise WishlistLimitReached(
                f"You've reached the limit of {self._max_items} wishlisted "
                "skins. Remove one first and you can add another."
            )
        return self._repo.add(telegram_id, skin_uuid)

    def remove(self, item_id: int, telegram_id: int) -> bool:
        return self._repo.remove(item_id, telegram_id)

    @property
    def max_items(self) -> int:
        return self._max_items
