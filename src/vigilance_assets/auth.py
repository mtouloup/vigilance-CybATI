from __future__ import annotations

import logging
from typing import Any

from flask import Flask, g, request

from .config import AppRuntimeSettings
from .jwt_validation import AuthenticationError, EntraJwtValidator

LOGGER = logging.getLogger(__name__)


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
