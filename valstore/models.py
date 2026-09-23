"""Immutable value objects passed between layers.

Frozen on purpose: an Account handed to the render layer must not be mutated
into disagreeing with the row it came from.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RiotIdentity:
    """Who a session belongs to, as Riot reports it."""

    puuid: str
    game_name: str | None = None
    tag_line: str | None = None

    @property
    def display_name(self) -> str:
        """'Player#NA1' when Riot told us, else a short puuid so the user still
        sees something stable rather than an empty label."""
        if self.game_name and self.tag_line:
            return f"{self.game_name}#{self.tag_line}"
        if self.game_name:
            return self.game_name
        return f"Account {self.puuid[:8]}"


@dataclass(frozen=True)
class Account:
    """One linked Riot account belonging to one Telegram user."""

    id: int
    telegram_id: int
    label: str
    shard: str
    enc_cookie: bytes
    is_default: bool
    linked_at: float
    puuid: str | None = None
    riot_name: str | None = None
    riot_tag: str | None = None
    last_used: float | None = None

    @property
    def riot_handle(self) -> str | None:
        if self.riot_name and self.riot_tag:
            return f"{self.riot_name}#{self.riot_tag}"
        return self.riot_name

    @property
    def title(self) -> str:
        """Label plus the Riot handle when it adds information. Keeping both
        matters once someone has 'Main' and 'Smurf' on different regions."""
        handle = self.riot_handle
        if handle and handle != self.label:
            return f"{self.label} — {handle}"
        return self.label


@dataclass(frozen=True)
class LinkResult:
    """What every LinkMethod must produce, whatever route it took to get there."""

    cookie_header: str
    shard: str
    identity: RiotIdentity | None = None

    @property
    def suggested_label(self) -> str:
        return self.identity.display_name if self.identity else "New account"
