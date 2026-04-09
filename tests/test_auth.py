from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from flask import Flask, g

from vigilance_assets.auth import configure_auth
from vigilance_assets.config import AppRuntimeSettings, EntraOboSettings, GoogleSheetsSettings, SharePointSettings
from vigilance_assets.jwt_validation import AuthContext, AuthenticationError
from vigilance_assets.token_acquisition import DownstreamTokenError, EntraOboTokenBroker, RequestScopedGraphTokenProvider


class AuthLayerTests(unittest.TestCase):
    def _entra_settings(self) -> EntraOboSettings:
        return EntraOboSettings(
            tenant_id='tenant-id',
            client_id='client-id',
            client_secret='secret',
            api_audience='api://asset-api',
        )

    def test_auth_middleware_denies_missing_or_invalid_tokens(self) -> None:
        app = Flask(__name__)

        @app.get('/protected')
        def _protected():
            return {'ok': True}, 200

        settings = AppRuntimeSettings(
            auth_mode='entra_obo',
            storage_backend='google_sheets',
            google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet-1', read_only_public_fallback=True),
            sharepoint=SharePointSettings(site_id='site', item_id='item'),
            entra_obo=self._entra_settings(),
        )
        configure_auth(app, settings)
        validator = app.config['JWT_VALIDATOR']

        client = app.test_client()
        no_token = client.get('/protected')
        self.assertEqual(no_token.status_code, 401)

        with patch.object(validator, 'validate', side_effect=AuthenticationError('invalid')):
            bad_token = client.get('/protected', headers={'Authorization': 'Bearer bad-token'})
            self.assertEqual(bad_token.status_code, 401)

    def test_auth_middleware_accepts_valid_tokens_and_sets_context(self) -> None:
        app = Flask(__name__)

        @app.get('/protected')
        def _protected():
            context = g.auth_context
            return {'subject': context.subject, 'tenant': context.tenant_id}, 200

        settings = AppRuntimeSettings(
            auth_mode='entra_obo',
            storage_backend='google_sheets',
            google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet-1', read_only_public_fallback=True),
            sharepoint=SharePointSettings(site_id='site', item_id='item'),
            entra_obo=self._entra_settings(),
        )
        configure_auth(app, settings)
        validator = app.config['JWT_VALIDATOR']
        validator.validate = Mock(return_value=AuthContext('sub-1', 'tenant-id', 'api://asset-api', None, 'a@b.com', 'Alice'))

        client = app.test_client()
        response = client.get('/protected', headers={'Authorization': 'Bearer valid-token'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['subject'], 'sub-1')

    def test_auth_middleware_allows_configured_public_paths_without_token(self) -> None:
        app = Flask(__name__)

        @app.get('/docs')
        def _docs():
            return {'ok': True}, 200

        @app.get('/docs/<path:filename>')
        def _docs_asset(filename: str):
            return {'name': filename}, 200

        @app.get('/docs-private')
        def _docs_private():
            return {'ok': True}, 200

        settings = AppRuntimeSettings(
            auth_mode='entra_obo',
            storage_backend='google_sheets',
            google_sheets=GoogleSheetsSettings(spreadsheet_id='sheet-1', read_only_public_fallback=True),
            sharepoint=SharePointSettings(site_id='site', item_id='item'),
            entra_obo=self._entra_settings(),
            auth_public_paths=('/docs',),
        )
        configure_auth(app, settings)

        client = app.test_client()
        self.assertEqual(client.get('/docs').status_code, 200)
        self.assertEqual(client.get('/docs/').status_code, 404)
        self.assertEqual(client.get('/docs/swagger-ui.css').status_code, 200)
        self.assertEqual(client.get('/docs-private').status_code, 401)

    @patch('vigilance_assets.token_acquisition.msal', create=True)
    def test_obo_token_broker_uses_on_behalf_of_flow(self, msal_module: Mock) -> None:
        app_instance = msal_module.ConfidentialClientApplication.return_value
        app_instance.acquire_token_on_behalf_of.return_value = {'access_token': 'graph-token'}
        broker = EntraOboTokenBroker(self._entra_settings())

        token = broker.acquire_graph_token('incoming-api-token')

        self.assertEqual(token, 'graph-token')
        app_instance.acquire_token_on_behalf_of.assert_called_once()

    def test_request_scoped_graph_token_provider_reuses_token_within_request(self) -> None:
        app = Flask(__name__)
        broker = Mock()
        broker.acquire_graph_token.return_value = 'graph-token'
        provider = RequestScopedGraphTokenProvider(broker)

        with app.test_request_context('/x'):
            g.incoming_bearer_token = 'api-token'
            first = provider()
            second = provider()

        self.assertEqual(first, 'graph-token')
        self.assertEqual(second, 'graph-token')
        broker.acquire_graph_token.assert_called_once_with('api-token')

    def test_request_scoped_graph_token_provider_requires_incoming_token(self) -> None:
        app = Flask(__name__)
        provider = RequestScopedGraphTokenProvider(Mock())

        with app.test_request_context('/x'):
            with self.assertRaisesRegex(DownstreamTokenError, 'No incoming API bearer token'):
                provider()


if __name__ == '__main__':
    unittest.main()
