from __future__ import annotations

import importlib
import os
import sys
import unittest
from unittest.mock import patch


class AppEntryTests(unittest.TestCase):
    def tearDown(self) -> None:
        sys.modules.pop('app', None)

    def test_app_module_loads_dotenv_and_creates_runtime_app(self) -> None:
        fake_app = object()
        with patch('dotenv.load_dotenv') as load_dotenv, patch(
            'vigilance_assets.runtime.create_runtime_app', return_value=fake_app
        ) as create_runtime_app:
            module = importlib.import_module('app')

        load_dotenv.assert_called_once_with()
        create_runtime_app.assert_called_once_with()
        self.assertIs(module.app, fake_app)

    def test_main_uses_local_defaults_and_env_overrides(self) -> None:
        fake_app = type('FakeApp', (), {'run': unittest.mock.Mock()})()
        with patch('dotenv.load_dotenv'), patch('vigilance_assets.runtime.create_runtime_app', return_value=fake_app):
            module = importlib.import_module('app')

        env = {
            'VIGILANCE_HOST': '127.0.0.1',
            'VIGILANCE_PORT': '9000',
            'VIGILANCE_DEBUG': 'true',
            'PORT': '9100',
        }
        with patch.dict(os.environ, env, clear=False):
            module.main()

        fake_app.run.assert_called_once_with(host='127.0.0.1', port=9100, debug=True)


if __name__ == '__main__':
    unittest.main()
