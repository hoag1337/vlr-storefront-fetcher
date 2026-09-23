"""Commands that act on one linked account.

/store and /inventory differ only in which endpoint they call and how the result
reads, so the shared part — open the credential chain, report any rotated cookie
— lives once in AccountCommand and each command supplies the two halves that
genuinely differ.

Everything here is synchronous and network-bound, including render (the asset
catalogs fetch on a cold cache), so the whole run belongs on a worker thread.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from valstore.rendering import InventoryRenderer, StoreRenderer
from valstore.riot import inventory as riot_inventory
from valstore.riot import store as riot_store
from valstore.riot.session import RiotSession, open_session


@dataclass(frozen=True)
class CommandOutcome:
    """Messages to send, plus session facts worth persisting."""

    messages: list[str]
    rotated_cookie: str | None
    puuid: str


class AccountCommand(ABC):
    """Fetch something for an account and turn it into Telegram messages."""

    #: Shown while the Riot chain runs, so a slow call never looks like a hang.
    busy_text: str = "Working…"

    @abstractmethod
    def fetch(self, session: RiotSession, shard: str):
        """Call Riot. Runs on a worker thread."""

    @abstractmethod
    def render(self, payload) -> list[str]:
        """Turn the payload into messages within Telegram's size limit."""

    def run(self, cookie_header: str, shard: str) -> CommandOutcome:
        """The shared workflow. Synchronous by design — call it in a thread."""
        session = open_session(cookie_header)
        payload = self.fetch(session, shard)
        return CommandOutcome(
            messages=self.render(payload),
            rotated_cookie=session.rotated_cookie,
            puuid=session.puuid,
        )


class StoreCommand(AccountCommand):
    busy_text = "Fetching your store…"

    def __init__(self, catalogs):
        self._renderer = StoreRenderer(catalogs)

    def fetch(self, session, shard):
        return riot_store.get_storefront(
            shard, session.puuid, session.access_token,
            session.entitlements_token, session.client_version,
        )

    def render(self, payload):
        return self._renderer.render(payload)


class InventoryCommand(AccountCommand):
    busy_text = "Fetching your inventory…"

    def __init__(self, catalogs):
        self._renderer = InventoryRenderer(catalogs)

    def fetch(self, session, shard):
        return riot_inventory.owned_skin_level_ids(
            shard, session.puuid, session.access_token,
            session.entitlements_token, session.client_version,
        )

    def render(self, payload):
        return self._renderer.render(payload)
