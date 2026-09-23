"""How a Riot session reaches the bot.

Linking is the one part of this project whose best mechanism is still open —
Riot's captcha rules out a password form, and an HttpOnly cookie rules out
reading it from a page — so it sits behind an interface. Every method converges
on the same thing: a cookie header that riot.auth.reauth already accepts. That
is why swapping the method changes nothing downstream.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from valstore.models import LinkResult


@dataclass(frozen=True)
class LinkChallenge:
    """What the user must see to produce a response."""

    instructions: str
    url: str | None = None
    #: False for a method that completes on its own (a polled or pushed flow),
    #: so the bot knows not to sit waiting for the user to send something.
    expects_reply: bool = True


class LinkMethod(ABC):
    """One route from 'a person wants to link' to 'a validated session'."""

    #: Stable key — goes in callback data, so it must not change casually.
    id: str = ""
    #: Button label.
    title: str = ""
    #: One line under the button.
    summary: str = ""
    #: Sent after a successful link, when this method leaves something behind
    #: that the user should clean up. None for methods that leave no trace.
    post_link_note: str | None = None

    @property
    def available(self) -> bool:
        """False hides the method rather than offering something that will fail."""
        return True

    @abstractmethod
    def start(self, telegram_id: int) -> LinkChallenge:
        """What to show the user."""

    @abstractmethod
    def complete(self, telegram_id: int, response: str) -> LinkResult:
        """Turn the user's response into a validated session.

        Synchronous and network-bound — callers run it on a worker thread.
        Raises LinkError with a message the user can act on.
        """


class LinkMethodRegistry:
    """The methods on offer, in the order they should be presented."""

    def __init__(self, methods):
        self._methods = [m for m in methods if m.available]

    def __iter__(self):
        return iter(self._methods)

    def __len__(self):
        return len(self._methods)

    def get(self, method_id: str) -> LinkMethod | None:
        for method in self._methods:
            if method.id == method_id:
                return method
        return None

    @property
    def only(self) -> LinkMethod | None:
        """The single method, when there is exactly one — lets the bot skip a
        pointless 'choose how to link' step."""
        return self._methods[0] if len(self._methods) == 1 else None
