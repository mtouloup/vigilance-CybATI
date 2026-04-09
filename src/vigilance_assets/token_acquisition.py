from __future__ import annotations

import time
from dataclasses import dataclass

from flask import g

from .config import EntraOboSettings

try:
    import msal  # type: ignore
except ModuleNotFoundError:  # pragma: no cover - handled at runtime when auth mode is enabled
    msal = None  # type: ignore[assignment]


class DownstreamTokenError(ValueError):
    """Raised when Graph token acquisition through OBO fails."""


class EntraOboTokenBroker:
    def __init__(self, settings: EntraOboSettings) -> None:
        self._settings = settings
        msal_module = msal
        if msal_module is None:
            raise DownstreamTokenError("MSAL is required for VIGILANCE_AUTH_MODE=entra_obo.")
        self._msal_app = msal_module.ConfidentialClientApplication(
            client_id=settings.client_id,
            authority=f"https://login.microsoftonline.com/{settings.tenant_id}",
            client_credential=settings.client_secret,
        )

    def acquire_graph_token(self, user_assertion: str) -> str:
        result = self._msal_app.acquire_token_on_behalf_of(
            user_assertion=user_assertion,
            scopes=list(self._settings.graph_scopes),
        )
        token = result.get("access_token") if isinstance(result, dict) else None
        if isinstance(token, str) and token.strip():
            return token
        error_code = result.get("error") if isinstance(result, dict) else "unknown_error"
        error_desc = result.get("error_description") if isinstance(result, dict) else ""
        raise DownstreamTokenError(
            f"Failed to acquire Graph delegated access token via OBO: {error_code} {error_desc}".strip()
        )


@dataclass(slots=True)
class _RequestTokenCache:
    token: str
    expires_at: float


class RequestScopedGraphTokenProvider:
    def __init__(self, broker: EntraOboTokenBroker) -> None:
        self._broker = broker

    def __call__(self) -> str:
        raw_token = getattr(g, "incoming_bearer_token", None)
        if not isinstance(raw_token, str) or not raw_token.strip():
            raise DownstreamTokenError("No incoming API bearer token is available for OBO exchange.")

        cached = getattr(g, "graph_access_token_cache", None)
        if isinstance(cached, _RequestTokenCache) and cached.expires_at > time.time() + 10:
            return cached.token

        token = self._broker.acquire_graph_token(raw_token)
        g.graph_access_token_cache = _RequestTokenCache(token=token, expires_at=time.time() + 300)
        return token
