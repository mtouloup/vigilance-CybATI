from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from collections.abc import Iterable
from typing import Any

from flask import Flask, jsonify, request

from .repository import (
    AssetListQuery,
    AssetNotFoundError,
    AssetPage,
    AssetRepository,
    AssetSchemaView,
    AssetSort,
    DeleteMode,
    DuplicateAssetError,
    RepositoryError,
    UnsupportedCategoryError,
    UnsupportedVocabularyError,
)
from .service import AssetService
from .validation import ValidationError


def create_app(service: AssetService | None = None, *, repository: AssetRepository | None = None) -> Flask:
    """Create the Flask application for the asset inventory API."""

    if service is None:
        if repository is None:
            raise ValueError("Either service or repository must be provided.")
        service = AssetService(repository)

    app = Flask(__name__)
    app.config["ASSET_SERVICE"] = service

    @app.get("/assets")
    def list_assets() -> Any:
        query = _build_asset_list_query(request.args, service.repository)
        page = service.list_assets(query)
        return _success_response(
            data={
                "items": [_serialize_asset(item) for item in page.items],
            },
            meta={
                "page": page.page,
                "page_size": page.page_size,
                "total": page.total,
                "returned": len(page.items),
                "filters": dict(query.filters),
                "search": query.search,
                "sort": [asdict(sort) for sort in query.sort],
            },
        )

    @app.get("/assets/<asset_id>")
    def get_asset(asset_id: str) -> Any:
        asset = service.get_asset(asset_id)
        return _success_response(data=_serialize_asset(asset))

    @app.get("/assets/quality")
    def get_asset_quality() -> Any:
        report = service.get_asset_quality_report()
        return _success_response(
            data={
                "assets": [asdict(asset) for asset in report.assets],
                "issues": [asdict(issue) for issue in report.issues],
            },
            meta={
                "total_assets": report.total_assets,
                "assets_with_issues": report.assets_with_issues,
                "issue_count": report.issue_count,
                "schema_name": service.repository.catalog.schema_name,
                "schema_version": service.repository.catalog.version,
                "id_field": service.repository.catalog.id_field,
            },
        )

    @app.post("/assets")
    def create_asset() -> Any:
        asset = service.create_asset(_require_json_object(), updated_by=_request_updated_by())
        return _success_response(data=_serialize_asset(asset), status=201)

    @app.patch("/assets/<asset_id>")
    def patch_asset(asset_id: str) -> Any:
        asset = service.patch_asset(asset_id, _require_json_object(), updated_by=_request_updated_by())
        return _success_response(data=_serialize_asset(asset))

    @app.put("/assets/<asset_id>")
    def replace_asset(asset_id: str) -> Any:
        asset = service.replace_asset(asset_id, _require_json_object(), updated_by=_request_updated_by())
        return _success_response(data=_serialize_asset(asset))

    @app.delete("/assets/<asset_id>")
    def delete_asset(asset_id: str) -> Any:
        mode = _parse_delete_mode(request.args.get("mode"))
        service.delete_asset(asset_id, mode=mode)
        return _success_response(data={"asset_id": asset_id, "mode": mode}, status=200)

    @app.get("/vocabularies")
    def get_vocabularies() -> Any:
        vocabularies = service.get_vocabularies()
        return _success_response(
            data={name: list(values) for name, values in vocabularies.items()},
            meta={"total": len(vocabularies)},
        )

    @app.get("/vocabularies/<name>")
    def get_vocabulary(name: str) -> Any:
        values = service.get_vocabulary(name)
        return _success_response(
            data={"name": name, "values": list(values)},
            meta={"total": len(values)},
        )

    @app.get("/schema/assets")
    def get_asset_schema() -> Any:
        schema_view = service.get_asset_schema()
        return _success_response(data=_serialize_schema_view(schema_view))

    @app.get("/schema/assets/<category>")
    def get_category_schema(category: str) -> Any:
        schema_view = service.get_category_schema(category)
        return _success_response(data=_serialize_schema_view(schema_view))

    @app.errorhandler(AssetNotFoundError)
    def handle_not_found(error: AssetNotFoundError) -> Any:
        return _error_response(
            status=404,
            code="asset_not_found",
            message=str(error),
        )

    @app.errorhandler(DuplicateAssetError)
    def handle_duplicate(error: DuplicateAssetError) -> Any:
        return _error_response(
            status=409,
            code="duplicate_asset",
            message=f"Asset_ID already exists: {error}",
        )

    @app.errorhandler(UnsupportedVocabularyError)
    def handle_unknown_vocabulary(error: UnsupportedVocabularyError) -> Any:
        return _error_response(
            status=404,
            code="unsupported_vocabulary",
            message=str(error),
        )

    @app.errorhandler(UnsupportedCategoryError)
    def handle_unknown_category(error: UnsupportedCategoryError) -> Any:
        return _error_response(
            status=404,
            code="unsupported_category",
            message=str(error),
        )

    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError) -> Any:
        return _error_response(
            status=400,
            code="validation_error",
            message="Request validation failed.",
            details=[asdict(issue) for issue in error.issues],
        )

    @app.errorhandler(ValueError)
    def handle_bad_request(error: ValueError) -> Any:
        return _error_response(
            status=400,
            code="invalid_request",
            message=str(error),
        )

    @app.errorhandler(RepositoryError)
    def handle_repository_error(error: RepositoryError) -> Any:
        return _error_response(
            status=500,
            code="repository_error",
            message=str(error),
        )

    return app


def _build_asset_list_query(args: Any, repository: AssetRepository) -> AssetListQuery:
    _validate_asset_list_query_params(args.keys(), repository)

    page = _parse_positive_int(args.get("page", "1"), field="page")
    page_size = _parse_positive_int(args.get("page_size", "50"), field="page_size")
    search = _normalize_search_term(args.get("search"))

    filters: dict[str, Any] = {}
    for field in repository.catalog.filterable_fields:
        values = [_coerce_field_value(field, value, repository) for value in args.getlist(field) if value != ""]
        if not values:
            continue
        filters[field] = values[0] if len(values) == 1 else tuple(values)

    sort = _parse_sort(args.getlist("sort"), repository)
    return AssetListQuery(filters=filters, search=search, sort=sort, page=page, page_size=page_size)


ASSET_LIST_RESERVED_PARAMS = frozenset({"page", "page_size", "search", "sort"})
DELETE_MODES: frozenset[str] = frozenset({"archive", "delete"})


def _validate_asset_list_query_params(param_names: Iterable[str], repository: AssetRepository) -> None:
    allowed = ASSET_LIST_RESERVED_PARAMS | set(repository.catalog.filterable_fields)
    unexpected = sorted({name for name in param_names if name not in allowed})
    if unexpected:
        formatted = ", ".join(unexpected)
        raise ValueError(f"Unsupported query parameter(s) for /assets: {formatted}")


def _normalize_search_term(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    return normalized or None


def _coerce_field_value(field: str, raw_value: str, repository: AssetRepository) -> Any:
    definition = repository.catalog.field_definition(field)
    if definition is None:
        return raw_value
    if definition.field_type == "integer":
        return _parse_integer(raw_value, field=field)
    return raw_value


def _parse_sort(raw_sort_values: list[str], repository: AssetRepository) -> tuple[AssetSort, ...]:
    sortable_fields = set(repository.catalog.sortable_fields)
    parsed: list[AssetSort] = []
    for raw_value in raw_sort_values:
        for part in raw_value.split(","):
            token = part.strip()
            if not token:
                continue
            direction = "desc" if token.startswith("-") else "asc"
            field = token[1:] if token[:1] in {"-", "+"} else token
            if field not in sortable_fields:
                raise ValueError(f"Invalid sort field: {field}")
            parsed.append(AssetSort(field=field, direction=direction))
    return tuple(parsed)


def _require_json_object() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if payload is None:
        raise ValueError("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise ValueError("Request body must be a JSON object.")
    return payload


def _request_updated_by() -> str | None:
    updated_by = request.headers.get("X-Updated-By")
    if updated_by is None:
        return None
    normalized = updated_by.strip()
    return normalized or None


def _parse_delete_mode(raw_mode: str | None) -> DeleteMode:
    if raw_mode is None:
        return "archive"
    normalized = raw_mode.strip().lower()
    if normalized not in DELETE_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(DELETE_MODES))}.")
    return normalized  # type: ignore[return-value]


def _parse_positive_int(raw_value: str, *, field: str) -> int:
    value = _parse_integer(raw_value, field=field)
    if value < 1:
        raise ValueError(f"{field} must be a positive integer.")
    return value


def _parse_integer(raw_value: str, *, field: str) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc


def _serialize_asset(asset: Any) -> dict[str, Any]:
    payload = asset.to_dict()
    return {key: _serialize_value(value) for key, value in payload.items()}


def _serialize_schema_view(schema_view: AssetSchemaView) -> dict[str, Any]:
    return {
        "id_field": schema_view.id_field,
        "common_fields": [_serialize_dataclass(field) for field in schema_view.common_fields],
        "category_fields": {
            category: [_serialize_dataclass(field) for field in fields]
            for category, fields in schema_view.category_fields.items()
        },
        "vocabularies": {name: list(values) for name, values in schema_view.vocabularies.items()},
    }


def _serialize_dataclass(instance: Any) -> Any:
    if is_dataclass(instance):
        return {key: _serialize_value(value) for key, value in asdict(instance).items()}
    return _serialize_value(instance)


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value


def _success_response(*, data: Any, meta: dict[str, Any] | None = None, status: int = 200):
    response = {"data": data, "error": None}
    if meta is not None:
        response["meta"] = meta
    return jsonify(response), status


def _error_response(*, status: int, code: str, message: str, details: list[dict[str, Any]] | None = None):
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return jsonify({"data": None, "error": error}), status
