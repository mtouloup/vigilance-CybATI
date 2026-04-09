from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, Response, current_app
from .blueprints import DELETE_MODES
from .schema import AssetSchemaCatalog, FieldDefinition

openapi_bp = Blueprint('openapi', __name__)


@openapi_bp.get('/openapi.json')
def openapi_document() -> Response:
    document = build_openapi_document(current_app)
    return Response(json.dumps(document, indent=2), mimetype='application/json')


@openapi_bp.get('/docs')
def swagger_ui() -> str:
    spec_url = current_app.config.get('OPENAPI_SPEC_URL', '/openapi.json')
    swagger_js = '/swaggerui/swagger-ui-bundle.js'
    swagger_css = '/swaggerui/swagger-ui.css'
    return f"""<!doctype html>
<html lang='en'>
  <head>
    <meta charset='utf-8'>
    <title>VIGILANCE Assets API Docs</title>
    <link rel='stylesheet' href='{swagger_css}'>
    <style>body {{ margin: 0; background: #fafafa; }}</style>
  </head>
  <body>
    <div id='swagger-ui'></div>
    <script src='{swagger_js}'></script>
    <script>
      window.ui = SwaggerUIBundle({{
        url: '{spec_url}',
        dom_id: '#swagger-ui',
        deepLinking: true,
        presets: [SwaggerUIBundle.presets.apis],
        layout: 'BaseLayout'
      }});
    </script>
  </body>
</html>"""


def build_openapi_document(app: Any) -> dict[str, Any]:
    catalog: AssetSchemaCatalog = app.config['ASSET_SERVICE'].repository.catalog
    server_url = app.config.get('OPENAPI_SERVER_URL', '/')
    asset_schema_name = 'AssetPayload'
    patch_schema_name = 'AssetPatchPayload'

    return {
        'openapi': '3.0.3',
        'info': {
            'title': 'VIGILANCE Asset Inventory API',
            'version': catalog.version,
            'description': 'Blueprint-organized Flask API over the canonical VIGILANCE asset schema.',
        },
        'servers': [{'url': server_url}],
        'tags': [
            {'name': 'Assets', 'description': 'CRUD, search, pagination, and quality reporting for assets.'},
            {'name': 'Vocabularies', 'description': 'Controlled vocabulary discovery endpoints.'},
            {'name': 'Schema', 'description': 'Canonical asset schema discovery endpoints.'},
        ],
        'paths': {
            '/assets': {
                'get': {
                    'tags': ['Assets'],
                    'summary': 'List assets',
                    'parameters': [
                        *_asset_list_parameters(catalog),
                    ],
                    'responses': {'200': _response_ref('AssetListEnvelope')},
                },
                'post': {
                    'tags': ['Assets'],
                    'summary': 'Create an asset',
                    'parameters': [_updated_by_header_parameter()],
                    'requestBody': _json_body_ref(asset_schema_name, required=True),
                    'responses': {'201': _response_ref('AssetEnvelope'), '400': _response_ref('ErrorEnvelope'), '409': _response_ref('ErrorEnvelope')},
                },
            },
            '/assets/{asset_id}': {
                'get': {
                    'tags': ['Assets'],
                    'summary': 'Get one asset',
                    'parameters': [_asset_id_parameter()],
                    'responses': {'200': _response_ref('AssetEnvelope'), '404': _response_ref('ErrorEnvelope')},
                },
                'patch': {
                    'tags': ['Assets'],
                    'summary': 'Patch an asset',
                    'parameters': [_asset_id_parameter(), _updated_by_header_parameter()],
                    'requestBody': _json_body_ref(patch_schema_name, required=True),
                    'responses': {'200': _response_ref('AssetEnvelope'), '400': _response_ref('ErrorEnvelope'), '404': _response_ref('ErrorEnvelope')},
                },
                'put': {
                    'tags': ['Assets'],
                    'summary': 'Replace an asset',
                    'parameters': [_asset_id_parameter(), _updated_by_header_parameter()],
                    'requestBody': _json_body_ref(asset_schema_name, required=True),
                    'responses': {'200': _response_ref('AssetEnvelope'), '400': _response_ref('ErrorEnvelope'), '404': _response_ref('ErrorEnvelope')},
                },
                'delete': {
                    'tags': ['Assets'],
                    'summary': 'Archive or delete an asset',
                    'parameters': [
                        _asset_id_parameter(),
                        {
                            'name': 'mode',
                            'in': 'query',
                            'schema': {'type': 'string', 'enum': sorted(DELETE_MODES), 'default': 'archive'},
                            'description': 'Delete strategy. `archive` marks the asset as Deprecated; `delete` removes it.',
                        },
                    ],
                    'responses': {'200': _response_ref('DeleteEnvelope'), '400': _response_ref('ErrorEnvelope'), '404': _response_ref('ErrorEnvelope')},
                },
            },
            '/assets/quality': {
                'get': {
                    'tags': ['Assets'],
                    'summary': 'Get inventory quality report',
                    'responses': {'200': _response_ref('QualityEnvelope')},
                },
            },
            '/vocabularies': {
                'get': {
                    'tags': ['Vocabularies'],
                    'summary': 'List all vocabularies',
                    'responses': {'200': _response_ref('VocabularyCollectionEnvelope')},
                }
            },
            '/vocabularies/{name}': {
                'get': {
                    'tags': ['Vocabularies'],
                    'summary': 'Get one vocabulary',
                    'parameters': [{'name': 'name', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}],
                    'responses': {'200': _response_ref('VocabularyEnvelope'), '404': _response_ref('ErrorEnvelope')},
                }
            },
            '/schema/assets': {
                'get': {
                    'tags': ['Schema'],
                    'summary': 'Get the canonical asset schema',
                    'responses': {'200': _response_ref('SchemaEnvelope')},
                }
            },
            '/schema/assets/{category}': {
                'get': {
                    'tags': ['Schema'],
                    'summary': 'Get the canonical schema for a single category',
                    'parameters': [{'name': 'category', 'in': 'path', 'required': True, 'schema': {'type': 'string', 'enum': list(catalog.category_fields)}}],
                    'responses': {'200': _response_ref('SchemaEnvelope'), '404': _response_ref('ErrorEnvelope')},
                }
            },
        },
        'components': {'schemas': _components(catalog)},
    }


def _components(catalog: AssetSchemaCatalog) -> dict[str, Any]:
    field_schema = {
        'type': 'object',
        'properties': {
            'name': {'type': 'string'},
            'sheet_header': {'type': 'string'},
            'field_type': {'type': 'string'},
            'required': {'type': 'boolean'},
            'nullable': {'type': 'boolean'},
            'description': {'type': 'string'},
            'enum_ref': {'type': 'string', 'nullable': True},
            'fmt': {'type': 'string', 'nullable': True},
            'constraints': {'type': 'object', 'nullable': True, 'additionalProperties': True},
            'filterable': {'type': 'boolean'},
            'sortable': {'type': 'boolean'},
            'searchable': {'type': 'boolean'},
            'updatable': {'type': 'boolean'},
            'server_managed': {'type': 'boolean'},
        },
        'required': ['name', 'sheet_header', 'field_type', 'required', 'nullable', 'description'],
    }
    asset_properties, asset_required = _payload_schema(catalog, include_required=True)
    patch_properties, _ = _payload_schema(catalog, include_required=False)
    telemetry_example = _telemetry_asset_example(catalog)
    return {
        'AssetPayload': {
            'type': 'object',
            'properties': asset_properties,
            'required': asset_required,
            'example': telemetry_example,
        },
        'AssetPatchPayload': {'type': 'object', 'properties': patch_properties, 'description': 'Partial asset update payload.'},
        'Asset': {
            'type': 'object',
            'properties': asset_properties,
            'required': asset_required,
            'example': telemetry_example,
        },
        'EnvelopeMeta': {'type': 'object', 'additionalProperties': True},
        'ErrorDetail': {'type': 'object', 'additionalProperties': True},
        'ErrorObject': {
            'type': 'object',
            'properties': {
                'code': {'type': 'string'},
                'message': {'type': 'string'},
                'details': {'type': 'array', 'items': {'$ref': '#/components/schemas/ErrorDetail'}},
            },
            'required': ['code', 'message'],
        },
        'AssetEnvelope': _envelope_schema({'$ref': '#/components/schemas/Asset'}),
        'AssetListEnvelope': _envelope_schema({
            'type': 'object',
            'properties': {'items': {'type': 'array', 'items': {'$ref': '#/components/schemas/Asset'}}},
            'required': ['items'],
        }),
        'DeleteEnvelope': _envelope_schema({
            'type': 'object',
            'properties': {'asset_id': {'type': 'string'}, 'mode': {'type': 'string', 'enum': sorted(DELETE_MODES)}},
            'required': ['asset_id', 'mode'],
        }),
        'VocabularyCollectionEnvelope': _envelope_schema({
            'type': 'object', 'additionalProperties': {'type': 'array', 'items': {'type': 'string'}}
        }),
        'VocabularyEnvelope': _envelope_schema({
            'type': 'object',
            'properties': {'name': {'type': 'string'}, 'values': {'type': 'array', 'items': {'type': 'string'}}},
            'required': ['name', 'values'],
        }),
        'SchemaField': field_schema,
        'SchemaView': {
            'type': 'object',
            'properties': {
                'id_field': {'type': 'string'},
                'common_fields': {'type': 'array', 'items': {'$ref': '#/components/schemas/SchemaField'}},
                'category_fields': {'type': 'object', 'additionalProperties': {'type': 'array', 'items': {'$ref': '#/components/schemas/SchemaField'}}},
                'vocabularies': {'type': 'object', 'additionalProperties': {'type': 'array', 'items': {'type': 'string'}}},
            },
            'required': ['id_field', 'common_fields', 'category_fields', 'vocabularies'],
        },
        'SchemaEnvelope': _envelope_schema({'$ref': '#/components/schemas/SchemaView'}),
        'ValidationSummary': {'type': 'object', 'additionalProperties': True},
        'ValidationIssue': {'type': 'object', 'additionalProperties': True},
        'QualityReport': {
            'type': 'object',
            'properties': {
                'assets': {'type': 'array', 'items': {'$ref': '#/components/schemas/ValidationSummary'}},
                'issues': {'type': 'array', 'items': {'$ref': '#/components/schemas/ValidationIssue'}},
            },
            'required': ['assets', 'issues'],
        },
        'QualityEnvelope': _envelope_schema({'$ref': '#/components/schemas/QualityReport'}),
        'ErrorEnvelope': {
            'type': 'object',
            'properties': {
                'data': {'nullable': True},
                'meta': {'type': 'object', 'additionalProperties': True},
                'error': {'$ref': '#/components/schemas/ErrorObject'},
            },
            'required': ['data', 'meta', 'error'],
        },
    }


def _payload_schema(catalog: AssetSchemaCatalog, *, include_required: bool) -> tuple[dict[str, Any], list[str]]:
    definitions = list(catalog.common_fields)
    for fields in catalog.category_fields.values():
        definitions.extend(fields)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in definitions:
        properties[field.name] = _field_to_schema(field, catalog)
        if include_required and field.required:
            required.append(field.name)
    return properties, required


def _field_to_schema(field: FieldDefinition, catalog: AssetSchemaCatalog) -> dict[str, Any]:
    schema: dict[str, Any] = {'description': field.description}
    schema['type'] = {'integer': 'integer', 'number': 'number', 'boolean': 'boolean'}.get(field.field_type, 'string')
    if field.nullable:
        schema['nullable'] = True
    if field.enum_ref:
        schema['enum'] = list(catalog.vocabularies[field.enum_ref])
    if field.fmt:
        schema['format'] = field.fmt
    if field.name == 'Documentation_Link':
        schema['format'] = 'uri'
    if field.name == 'Last_Updated':
        schema['format'] = 'date-time'
    if field.constraints:
        if 'min' in field.constraints:
            schema['minimum'] = field.constraints['min']
        if 'max' in field.constraints:
            schema['maximum'] = field.constraints['max']
    if not field.updatable:
        schema['readOnly'] = True
    return schema


def _telemetry_asset_example(catalog: AssetSchemaCatalog) -> dict[str, Any]:
    def _first(name: str, default: str) -> str:
        values = catalog.vocabularies.get(name, ())
        return values[0] if values else default

    return {
        'Asset_ID': 'AST-TELE-001',
        'Asset_Name': 'Pilot Telemetry Stream',
        'Asset_Category': 'Data Stream / Data Source / Telemetry',
        'Owner_Org': 'OpenAI Security Lab',
        'Owner_Contact': 'telemetry-owner@example.org',
        'Pilot_s': 'Pilot A',
        'Purpose': 'Ingests telemetry from pilot infrastructure and simulation inputs.',
        'Status': _first('Status', 'Active'),
        'TRL_Start': 4,
        'TRL_Current': 5,
        'TRL_Target': 7,
        'Related_Result': 'RS3',
        'Related_WP_Task': 'T5.3',
        'Deployment_Context': _first('Deployment_Context', 'Cloud'),
        'Standards_Compliance': 'IEC 62443',
        'Security_Domain': _first('Security_Domain', 'Cloud Security'),
        'Documentation_Link': 'https://example.org/assets/telemetry-stream',
        'Last_Updated': '2026-03-21T10:00:00+00:00',
        'Updated_By': 'telemetry-owner@example.org',
        'Telemetry_Type': 'Network flow telemetry',
        'Data_Format': 'JSON',
        'Frequency': 'real-time',
        'Data_Sensitivity': 'Restricted',
        'Sharing_Policy': _first('Sharing_Policy', 'Consortium-internal'),
        'Data_Origin': _first('Data_Origin', 'Real-world'),
    }


def _asset_list_parameters(catalog: AssetSchemaCatalog) -> list[dict[str, Any]]:
    parameters = [
        {'name': 'page', 'in': 'query', 'schema': {'type': 'integer', 'minimum': 1, 'default': 1}, 'description': '1-based page number.'},
        {'name': 'page_size', 'in': 'query', 'schema': {'type': 'integer', 'minimum': 1, 'default': 50}, 'description': 'Number of assets per page.'},
        {'name': 'search', 'in': 'query', 'schema': {'type': 'string'}, 'description': f"Free-text search across: {', '.join(catalog.searchable_fields)}."},
        {'name': 'sort', 'in': 'query', 'schema': {'type': 'array', 'items': {'type': 'string'}}, 'style': 'form', 'explode': True, 'description': f"Sort directives using sortable fields: {', '.join(catalog.sortable_fields)}. Prefix with '-' for descending."},
    ]
    for field_name in catalog.filterable_fields:
        field = catalog.field_definition(field_name)
        if field is None:
            continue
        parameters.append({
            'name': field_name,
            'in': 'query',
            'schema': _field_to_schema(field, catalog),
            'description': f"Filter by {field_name}. Repeat the parameter to match any of multiple values.",
        })
    return parameters


def _updated_by_header_parameter() -> dict[str, Any]:
    return {
        'name': 'X-Updated-By',
        'in': 'header',
        'required': False,
        'schema': {'type': 'string'},
        'description': 'Optional override for the Updated_By field during create, patch, and replace operations.',
    }


def _asset_id_parameter() -> dict[str, Any]:
    return {'name': 'asset_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}


def _json_body_ref(schema_name: str, *, required: bool) -> dict[str, Any]:
    return {'required': required, 'content': {'application/json': {'schema': {'$ref': f'#/components/schemas/{schema_name}'}}}}


def _response_ref(schema_name: str) -> dict[str, Any]:
    return {'description': 'Successful response', 'content': {'application/json': {'schema': {'$ref': f'#/components/schemas/{schema_name}'}}}}


def _envelope_schema(data_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        'type': 'object',
        'properties': {
            'data': data_schema,
            'meta': {'type': 'object', 'additionalProperties': True},
            'error': {'nullable': True, 'allOf': [{'$ref': '#/components/schemas/ErrorObject'}]},
        },
        'required': ['data', 'meta', 'error'],
    }
