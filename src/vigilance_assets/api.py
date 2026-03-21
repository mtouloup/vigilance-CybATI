from __future__ import annotations

from typing import Any

from flask import Flask, send_from_directory

from .blueprints import assets_bp, error_response, schema_bp, vocabularies_bp
from .openapi import openapi_bp
from .repository import (
    AssetNotFoundError,
    AssetRepository,
    DuplicateAssetError,
    RepositoryError,
    UnsupportedCategoryError,
    UnsupportedVocabularyError,
)
from .service import AssetService
from .validation import ValidationError
from swagger_ui_bundle import swagger_ui_path


def create_app(service: AssetService | None = None, *, repository: AssetRepository | None = None) -> Flask:
    """Create the Flask application for the asset inventory API."""

    if service is None:
        if repository is None:
            raise ValueError('Either service or repository must be provided.')
        service = AssetService(repository)

    app = Flask(__name__)
    app.config['ASSET_SERVICE'] = service
    app.config.setdefault('OPENAPI_SPEC_URL', '/openapi.json')
    app.register_blueprint(assets_bp)
    app.register_blueprint(vocabularies_bp)
    app.register_blueprint(schema_bp)
    app.register_blueprint(openapi_bp)

    @app.get('/swaggerui/<path:filename>')
    def swaggerui_static(filename: str):
        return send_from_directory(swagger_ui_path, filename)

    @app.errorhandler(AssetNotFoundError)
    def handle_not_found(error: AssetNotFoundError) -> Any:
        return error_response(status=404, code='asset_not_found', message=str(error))

    @app.errorhandler(DuplicateAssetError)
    def handle_duplicate(error: DuplicateAssetError) -> Any:
        return error_response(status=409, code='duplicate_asset', message=f'Asset_ID already exists: {error}')

    @app.errorhandler(UnsupportedVocabularyError)
    def handle_unknown_vocabulary(error: UnsupportedVocabularyError) -> Any:
        return error_response(status=404, code='unsupported_vocabulary', message=str(error))

    @app.errorhandler(UnsupportedCategoryError)
    def handle_unknown_category(error: UnsupportedCategoryError) -> Any:
        return error_response(status=404, code='unsupported_category', message=str(error))

    @app.errorhandler(ValidationError)
    def handle_validation_error(error: ValidationError) -> Any:
        return error_response(status=400, code='validation_error', message='Request validation failed.', details=error.issues)

    @app.errorhandler(ValueError)
    def handle_bad_request(error: ValueError) -> Any:
        return error_response(status=400, code='invalid_request', message=str(error))

    @app.errorhandler(RepositoryError)
    def handle_repository_error(error: RepositoryError) -> Any:
        return error_response(status=500, code='repository_error', message=str(error))

    return app
