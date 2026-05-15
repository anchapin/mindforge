"""OAuth provider strategies for /api/oauth/{provider}/* routes (#57).

Per ADR-0001 Composio is the umbrella OAuth broker: MindForge does not
implement raw Google OAuth itself, it delegates to Composio's hosted flow
and stores the resulting `connected_account_id` Fernet-encrypted on the
existing `integration` row.

The provider strategy is pluggable so a future direct-OAuth path
(needed if Composio ever drops support for a critical app) can be added
behind the same route surface without breaking callers.
"""

from .composio_provider import COMPOSIO_PROVIDER, ComposioOAuthProvider
from .provider import (
    OAuthProvider,
    OAuthProviderError,
    OAuthStartResult,
    get_provider,
    register_provider,
)

__all__ = [
    "COMPOSIO_PROVIDER",
    "ComposioOAuthProvider",
    "OAuthProvider",
    "OAuthProviderError",
    "OAuthStartResult",
    "get_provider",
    "register_provider",
]
