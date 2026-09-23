"""Immutable value object for one wishlisted skin.

Frozen for the same reason as valstore.models: a row handed to the render or
matching layer must not silently drift from what is actually stored.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WishlistItem:
    """One skin a Telegram user wants to be notified about.

    Scoped to telegram_id, not to a specific linked account: the wishlist is a
    standing preference of the person, checked against every account they
    happen to have linked.
    """

    id: int
    telegram_id: int
    skin_uuid: str
    added_at: float
