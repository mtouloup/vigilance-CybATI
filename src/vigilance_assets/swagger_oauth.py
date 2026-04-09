from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class SwaggerOAuthConfig:
    enabled: bool
    tenant_id: str = ""
    client_id: str = ""
    scopes: tuple[str, ...] = ()
    authorization_url: str = ""
    token_url: str = ""

    @property
    def scopes_string(self) -> str:
        return " ".join(self.scopes)

    def as_openapi_security(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        return [{"entraOAuth2": list(self.scopes)}]


def resolve_swagger_oauth_config(config: Mapping[str, Any]) -> SwaggerOAuthConfig:
    enabled = bool(config.get("SWAGGER_USE_OAUTH"))
    tenant_id = str(config.get("SWAGGER_ENTRA_TENANT_ID") or "").strip()
    client_id = str(config.get("SWAGGER_CLIENT_ID") or "").strip()
    raw_scopes = config.get("SWAGGER_OAUTH_SCOPES", ())
    scopes = tuple(
        scope.strip()
        for scope in raw_scopes
        if isinstance(scope, str) and scope.strip()
    )
    authorization_url = str(config.get("SWAGGER_OAUTH_AUTHORIZATION_URL") or "").strip()
    token_url = str(config.get("SWAGGER_OAUTH_TOKEN_URL") or "").strip()

    if tenant_id and (not authorization_url or not token_url):
        authority_root = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0"
        authorization_url = authorization_url or f"{authority_root}/authorize"
        token_url = token_url or f"{authority_root}/token"

    if not (enabled and tenant_id and client_id and scopes and authorization_url and token_url):
        return SwaggerOAuthConfig(enabled=False)

    return SwaggerOAuthConfig(
        enabled=True,
        tenant_id=tenant_id,
        client_id=client_id,
        scopes=scopes,
        authorization_url=authorization_url,
        token_url=token_url,
    )
