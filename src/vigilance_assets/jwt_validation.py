from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import EntraOboSettings


class AuthenticationError(ValueError):
    """Raised when the incoming API token cannot be authenticated."""


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
        self._jwks_client: Any | None = None

    @property
    def authority(self) -> str:
        return f"https://login.microsoftonline.com/{self._settings.tenant_id}/v2.0"

    def validate(self, bearer_token: str) -> AuthContext:
        import jwt
        from jwt import InvalidTokenError

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
                issuer=self.authority,
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


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
