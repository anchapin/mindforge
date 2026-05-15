"""OAuth provider strategy interface (#57).

Each `OAuthProvider` adapts the generic /api/oauth/{provider}/start +
/callback routes to a concrete OAuth broker. The Phase 4 default is the
Composio-mediated flow declared by ADR-0001.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class OAuthProviderError(Exception):
    """Raised when a provider cannot serve the request.

    The HTTP layer maps this to a 503 with the original message so the
    user sees a clear "Composio is disabled" / "missing key" failure
    instead of a stack trace.
    """


@dataclass(frozen=True)
class OAuthStartResult:
    """Return value of `OAuthProvider.start`.

    `auth_url` is the URL the dashboard redirects the user's browser to.
    `state` is an opaque string MindForge must echo back on the callback
    to defeat CSRF (validated via Fernet round-trip in the route layer).
    """

    auth_url: str
    state: str


class OAuthProvider(Protocol):
    """Strategy contract for OAuth brokers (Composio today; direct later)."""

    name: str

    def is_enabled(self) -> bool:
        """Return True only if this provider is fully configured.

        Routes call this first so a disabled provider returns a
        structured 503 instead of attempting any work.
        """
        ...

    async def start(self, app: str, redirect_uri: str) -> OAuthStartResult:
        """Begin an OAuth grant for `app` (e.g. ``"gmail"``).

        Implementations must NOT make a network call when ``is_enabled()``
        is False; they should raise ``OAuthProviderError`` instead.
        """
        ...

    async def complete(self, app: str, callback_params: dict[str, str]) -> dict[str, str]:
        """Finalise the grant.

        Returns a dict of opaque, broker-specific identifiers that the
        route layer Fernet-encrypts and stores on the `integration` row.
        Composio returns ``{"connected_account_id": "..."}``; a future
        direct-OAuth provider would return ``{"access_token": ...,
        "refresh_token": ..., "expires_at": ...}``.
        """
        ...


_REGISTRY: dict[str, OAuthProvider] = {}


def register_provider(provider: OAuthProvider) -> None:
    _REGISTRY[provider.name] = provider


def get_provider(name: str) -> OAuthProvider | None:
    return _REGISTRY.get(name)
