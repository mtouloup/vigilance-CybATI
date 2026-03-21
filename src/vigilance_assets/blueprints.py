from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from collections.abc import Iterable
from typing import Any

from flask import Blueprint, current_app, jsonify, request

from .repository import AssetListQuery, AssetRepository, AssetSchemaView, AssetSort, DeleteMode
from .service import AssetService

assets_bp = Blueprint('assets', __name__)
vocabularies_bp = Blueprint('vocabularies', __name__)
schema_bp = Blueprint('schema', __name__)

ASSET_LIST_RESERVED_PARAMS = frozenset({'page', 'page_size', 'search', 'sort'})
DELETE_MODES: frozenset[str] = frozenset({'archive', 'delete'})


def get_asset_service() -> AssetService:
    return current_app.config['ASSET_SERVICE']


@assets_bp.get('/assets')
def list_assets() -> Any:
    service = get_asset_service()
    query = _build_asset_list_query(request.args, service.repository)
    page = service.list_assets(query)
    return _success_response(
        data={'items': [_serialize_asset(item) for item in page.items]},
        meta={
            'page': page.page,
            'page_size': page.page_size,
            'total': page.total,
            'returned': len(page.items),
            'filters': dict(query.filters),
            'search': query.search,
            'sort': [asdict(sort) for sort in query.sort],
        },
    )


@assets_bp.get('/assets/<asset_id>')
def get_asset(asset_id: str) -> Any:
    return _success_response(data=_serialize_asset(get_asset_service().get_asset(asset_id)))


@assets_bp.get('/assets/quality')
def get_asset_quality() -> Any:
    service = get_asset_service()
    report = service.get_asset_quality_report()
    return _success_response(
        data={
            'assets': [asdict(asset) for asset in report.assets],
            'issues': [asdict(issue) for issue in report.issues],
        },
        meta={
            'total_assets': report.total_assets,
            'assets_with_issues': report.assets_with_issues,
            'issue_count': report.issue_count,
            'schema_name': service.repository.catalog.schema_name,
            'schema_version': service.repository.catalog.version,
            'id_field': service.repository.catalog.id_field,
        },
    )


@assets_bp.post('/assets')
def create_asset() -> Any:
    service = get_asset_service()
    asset = service.create_asset(_require_json_object(), updated_by=_request_updated_by())
    return _success_response(data=_serialize_asset(asset), status=201)


@assets_bp.patch('/assets/<asset_id>')
def patch_asset(asset_id: str) -> Any:
    service = get_asset_service()
    asset = service.patch_asset(asset_id, _require_json_object(), updated_by=_request_updated_by())
    return _success_response(data=_serialize_asset(asset))


@assets_bp.put('/assets/<asset_id>')
def replace_asset(asset_id: str) -> Any:
    service = get_asset_service()
    asset = service.replace_asset(asset_id, _require_json_object(), updated_by=_request_updated_by())
    return _success_response(data=_serialize_asset(asset))


@assets_bp.delete('/assets/<asset_id>')
def delete_asset(asset_id: str) -> Any:
    service = get_asset_service()
    mode = _parse_delete_mode(request.args.get('mode'))
    service.delete_asset(asset_id, mode=mode)
    return _success_response(data={'asset_id': asset_id, 'mode': mode}, status=200)


@vocabularies_bp.get('/vocabularies')
def get_vocabularies() -> Any:
    vocabularies = get_asset_service().get_vocabularies()
    return _success_response(
        data={name: list(values) for name, values in vocabularies.items()},
        meta={'total': len(vocabularies)},
    )


@vocabularies_bp.get('/vocabularies/<name>')
def get_vocabulary(name: str) -> Any:
    values = get_asset_service().get_vocabulary(name)
    return _success_response(data={'name': name, 'values': list(values)}, meta={'total': len(values)})


@schema_bp.get('/schema/assets')
def get_asset_schema() -> Any:
    return _success_response(data=_serialize_schema_view(get_asset_service().get_asset_schema()))


@schema_bp.get('/schema/assets/<category>')
def get_category_schema(category: str) -> Any:
    return _success_response(data=_serialize_schema_view(get_asset_service().get_category_schema(category)))


def _build_asset_list_query(args: Any, repository: AssetRepository) -> AssetListQuery:
    _validate_asset_list_query_params(args.keys(), repository)
    page = _parse_positive_int(args.get('page', '1'), field='page')
    page_size = _parse_positive_int(args.get('page_size', '50'), field='page_size')
    search = _normalize_search_term(args.get('search'))

    filters: dict[str, Any] = {}
    for field in repository.catalog.filterable_fields:
        values = [_coerce_field_value(field, value, repository) for value in args.getlist(field) if value != '']
        if values:
            filters[field] = values[0] if len(values) == 1 else tuple(values)

    sort = _parse_sort(args.getlist('sort'), repository)
    return AssetListQuery(filters=filters, search=search, sort=sort, page=page, page_size=page_size)


def _validate_asset_list_query_params(param_names: Iterable[str], repository: AssetRepository) -> None:
    allowed = ASSET_LIST_RESERVED_PARAMS | set(repository.catalog.filterable_fields)
    unexpected = sorted({name for name in param_names if name not in allowed})
    if unexpected:
        raise ValueError(f"Unsupported query parameter(s) for /assets: {', '.join(unexpected)}")


def _normalize_search_term(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    normalized = raw_value.strip()
    return normalized or None


def _coerce_field_value(field: str, raw_value: str, repository: AssetRepository) -> Any:
    definition = repository.catalog.field_definition(field)
    if definition and definition.field_type == 'integer':
        return _parse_integer(raw_value, field=field)
    return raw_value


def _parse_sort(raw_sort_values: list[str], repository: AssetRepository) -> tuple[AssetSort, ...]:
    sortable_fields = set(repository.catalog.sortable_fields)
    parsed: list[AssetSort] = []
    for raw_value in raw_sort_values:
        for part in raw_value.split(','):
            token = part.strip()
            if not token:
                continue
            direction = 'desc' if token.startswith('-') else 'asc'
            field = token[1:] if token[:1] in {'-', '+'} else token
            if field not in sortable_fields:
                raise ValueError(f'Invalid sort field: {field}')
            parsed.append(AssetSort(field=field, direction=direction))
    return tuple(parsed)


def _require_json_object() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise ValueError('Request body must be a JSON object.')
    return payload


def _request_updated_by() -> str | None:
    updated_by = request.headers.get('X-Updated-By')
    if updated_by is None:
        return None
    normalized = updated_by.strip()
    return normalized or None


def _parse_delete_mode(raw_mode: str | None) -> DeleteMode:
    mode = (raw_mode or 'archive').strip().lower()
    if mode not in DELETE_MODES:
        raise ValueError(f"Unsupported delete mode: {raw_mode}. Expected one of: {', '.join(sorted(DELETE_MODES))}")
    return mode  # type: ignore[return-value]


def _parse_positive_int(raw_value: Any, *, field: str) -> int:
    value = _parse_integer(raw_value, field=field)
    if value <= 0:
        raise ValueError(f'{field} must be a positive integer.')
    return value


def _parse_integer(raw_value: Any, *, field: str) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{field} must be an integer.') from exc


def _serialize_schema_view(schema_view: AssetSchemaView) -> dict[str, Any]:
    return {
        'id_field': schema_view.id_field,
        'common_fields': [_serialize_value(field) for field in schema_view.common_fields],
        'category_fields': {
            category: [_serialize_value(field) for field in fields]
            for category, fields in schema_view.category_fields.items()
        },
        'vocabularies': {name: list(values) for name, values in schema_view.vocabularies.items()},
    }


def _serialize_asset(asset: Any) -> dict[str, Any]:
    return _serialize_value(asset.to_dict())


def _serialize_value(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _serialize_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


def _success_response(*, data: Any, meta: dict[str, Any] | None = None, status: int = 200) -> Any:
    return jsonify({'data': data, 'meta': meta or {}, 'error': None}), status


def error_response(*, status: int, code: str, message: str, details: Any = None) -> Any:
    error: dict[str, Any] = {'code': code, 'message': message}
    if details is not None:
        error['details'] = _serialize_value(details)
    return jsonify({'data': None, 'meta': {}, 'error': error}), status
