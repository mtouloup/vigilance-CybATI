from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import jwt
import msal
from flask import Flask, g, request
from jwt import InvalidTokenError

from .config import AppRuntimeSettings, EntraOboSettings

LOGGER = logging.getLogger(__name__)


class AuthenticationError(ValueError):
    """Raised when the incoming API token cannot be authenticated."""


class DownstreamTokenError(ValueError):
    """Raised when Graph token acquisition through OBO fails."""


@dataclass(frozen=True, slots=True)
class AuthContext:
    subject: str
    tenant_id: str
    audience: str
    app_id: str | None
    upn: str | None
    name: str | None


class EntraJwtValidator:
    def __init__(self, settings: EntraOboSettings, *, timeout_seconds: float = 10.0) -> None:
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._jwks_client: jwt.PyJWKClient | None = None

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self._settings.tenant_id}/v2.0"

    def validate(self, bearer_token: str) -> AuthContext:
        if not bearer_token:
            raise AuthenticationError("Bearer token is missing.")
        jwks_client = self._jwks_client
        if jwks_client is None:
            jwks_client = jwt.PyJWKClient(f"{self.authority}/discovery/v2.0/keys")
            self._jwks_client = jwks_client
        try:
            signing_key = jwks_client.get_signing_key_from_jwt(bearer_token)
            payload = jwt.decode(
                bearer_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._settings.api_audience,
                issuer=f"{self.authority}",
                options={"require": ["exp", "iat", "iss", "aud", "tid", "sub"]},
            )
        except InvalidTokenError as exc:
            raise AuthenticationError("Bearer token validation failed.") from exc

        token_tenant_id = str(payload.get("tid") or "")
        if token_tenant_id != self._settings.tenant_id:
            raise AuthenticationError("Bearer token tenant does not match configured tenant.")

        subject = str(payload.get("sub") or "").strip()
        if not subject:
            raise AuthenticationError("Bearer token is missing subject claim.")

        return AuthContext(
            subject=subject,
            tenant_id=token_tenant_id,
            audience=str(payload.get("aud") or ""),
            app_id=_as_optional_str(payload.get("azp") or payload.get("appid")),
            upn=_as_optional_str(payload.get("preferred_username") or payload.get("upn")),
            name=_as_optional_str(payload.get("name")),
        )


class EntraOboTokenBroker:
    def __init__(self, settings: EntraOboSettings) -> None:
        self._settings = settings
        self._msal_app = msal.ConfidentialClientApplication(
            client_id=settings.client_id,
            authority=f"https://login.microsoftonline.com/{settings.tenant_id}",
            client_credential=settings.client_secret,
        )

    def acquire_graph_token(self, user_assertion: str) -> str:
        result = self._msal_app.acquire_token_on_behalf_of(user_assertion=user_assertion, scopes=list(self._settings.graph_scopes))
        token = result.get("access_token") if isinstance(result, dict) else None
        if isinstance(token, str) and token.strip():
            return token
        error_code = result.get("error") if isinstance(result, dict) else "unknown_error"
        error_desc = result.get("error_description") if isinstance(result, dict) else ""
        raise DownstreamTokenError(f"Failed to acquire Graph delegated access token via OBO: {error_code} {error_desc}".strip())


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


def configure_auth(app: Flask, settings: AppRuntimeSettings) -> None:
    if settings.auth_mode == "none":
        app.config["AUTH_MODE"] = "none"
        LOGGER.warning("Authentication disabled (VIGILANCE_AUTH_MODE=none).")
        return

    if settings.auth_mode != "entra_obo" or settings.entra_obo is None:
        raise ValueError(f"Unsupported auth mode: {settings.auth_mode}")

    validator = EntraJwtValidator(settings.entra_obo)
    app.config["AUTH_MODE"] = "entra_obo"
    app.config["JWT_VALIDATOR"] = validator
    public_paths = tuple(_normalize_public_path(path) for path in settings.auth_public_paths if path.strip())
    app.config["AUTH_PUBLIC_PATHS"] = public_paths

    @app.before_request
    def _require_authentication() -> Any:
        if _is_public_path(request.path, public_paths):
            return None

        auth_header = request.headers.get("Authorization", "")
        prefix = "Bearer "
        if not auth_header.startswith(prefix):
            return _auth_error("Missing bearer token.", status=401)

        token = auth_header[len(prefix):].strip()
        if not token:
            return _auth_error("Missing bearer token.", status=401)

        try:
            context = validator.validate(token)
        except AuthenticationError:
            return _auth_error("Invalid bearer token.", status=401)

        g.auth_context = context
        g.incoming_bearer_token = token
        LOGGER.debug(
            "Authenticated request subject=%s tenant=%s upn=%s",
            context.subject,
            context.tenant_id,
            context.upn or "n/a",
        )
        return None


def _auth_error(message: str, *, status: int) -> tuple[dict[str, Any], int]:
    return {"data": None, "meta": {}, "error": {"code": "authentication_failed", "message": message}}, status


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _is_public_path(request_path: str, public_paths: tuple[str, ...]) -> bool:
    normalized_request_path = _normalize_request_path(request_path)
    for public_path in public_paths:
        if normalized_request_path == public_path:
            return True
        if public_path != "/" and normalized_request_path.startswith(f"{public_path}/"):
            return True
    return False


def _normalize_public_path(path: str) -> str:
    normalized = path.strip()
    if not normalized:
        return "/"
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized or "/"


def _normalize_request_path(path: str) -> str:
    if not path:
        return "/"
    normalized = path if path.startswith("/") else f"/{path}"
    if normalized != "/":
        normalized = normalized.rstrip("/")
    return normalized or "/"
