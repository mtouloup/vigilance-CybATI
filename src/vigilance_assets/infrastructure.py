from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .config import AppRuntimeSettings, SpreadsheetBackendSettings, load_runtime_settings
from .google_sheets import build_google_sheets_gateway
from .repository import SpreadsheetAssetRepository
from .spreadsheet import SpreadsheetTableGateway


class SpreadsheetGatewayFactoryError(RuntimeError):
    """Raised when a spreadsheet gateway factory is not available or fails."""


GatewayFactory = Callable[[SpreadsheetBackendSettings], SpreadsheetTableGateway]


@dataclass(slots=True)
class SpreadsheetGatewayFactoryRegistry:
    """Infrastructure registry for backend-specific spreadsheet gateway builders."""

    _factories: dict[str, GatewayFactory] = field(default_factory=dict)

    def register(self, backend: str, factory: GatewayFactory) -> None:
        self._factories[backend] = factory

    def create_gateway(self, settings: SpreadsheetBackendSettings) -> SpreadsheetTableGateway:
        try:
            factory = self._factories[settings.backend]
        except KeyError as exc:
            raise SpreadsheetGatewayFactoryError(
                f"No spreadsheet gateway factory registered for backend: {settings.backend}"
            ) from exc
        return factory(settings)


DEFAULT_GATEWAY_FACTORIES = SpreadsheetGatewayFactoryRegistry()
DEFAULT_GATEWAY_FACTORIES.register("google_sheets", build_google_sheets_gateway)


def build_spreadsheet_repository(
    settings: AppRuntimeSettings | None = None,
    *,
    gateway_factories: SpreadsheetGatewayFactoryRegistry | None = None,
    env: Mapping[str, str] | None = None,
) -> SpreadsheetAssetRepository:
    """Build a spreadsheet repository from runtime settings without embedding backend SDK logic.

    Real Google Sheets or workbook adapters should be registered via ``gateway_factories``.
    This helper keeps environment and infrastructure concerns out of the domain/service layers.
    """

    resolved_settings = settings or load_runtime_settings(env)
    registry = gateway_factories or DEFAULT_GATEWAY_FACTORIES
    gateway = registry.create_gateway(resolved_settings.spreadsheet)
    return SpreadsheetAssetRepository(
        workbook_reference=resolved_settings.spreadsheet.resolved_workbook_reference,
        gateway=gateway,
    )
