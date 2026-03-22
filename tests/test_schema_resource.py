from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from importlib import resources

from vigilance_assets.schema import load_schema_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]


class SchemaResourceTests(unittest.TestCase):
    def test_package_schema_resource_matches_canonical_schema_json(self) -> None:
        canonical_schema = json.loads((REPO_ROOT / 'schema' / 'assets_schema.json').read_text(encoding='utf-8'))
        packaged_schema = json.loads(
            resources.files('vigilance_assets').joinpath('resources', 'assets_schema.json').read_text(encoding='utf-8')
        )

        self.assertEqual(packaged_schema, canonical_schema)

    def test_load_schema_catalog_works_from_installed_package_without_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            temp_path = Path(tmp_dir)
            install_dir = temp_path / 'site'
            install_dir.mkdir()

            subprocess.run(
                [sys.executable, '-m', 'pip', 'install', '--quiet', '--target', str(install_dir), str(REPO_ROOT)],
                check=True,
                cwd=temp_path,
                env={**os.environ, 'PIP_DISABLE_PIP_VERSION_CHECK': '1'},
            )

            probe_script = temp_path / 'probe_schema.py'
            probe_script.write_text(
                textwrap.dedent(
                    f"""
                    import json
                    import os
                    import sys

                    sys.path = [{str(install_dir)!r}] + [path for path in sys.path if path not in ('', {str(REPO_ROOT)!r})]
                    os.chdir({str(temp_path)!r})

                    from vigilance_assets.schema import load_schema_catalog

                    catalog = load_schema_catalog()
                    print(json.dumps({{
                        'schema_name': catalog.schema_name,
                        'id_field': catalog.id_field,
                        'common_fields': len(catalog.common_fields),
                    }}))
                    """
                ),
                encoding='utf-8',
            )

            completed = subprocess.run(
                [sys.executable, str(probe_script)],
                check=True,
                capture_output=True,
                text=True,
                cwd=temp_path,
            )

        payload = json.loads(completed.stdout)
        self.assertEqual(payload['schema_name'], load_schema_catalog().schema_name)
        self.assertEqual(payload['id_field'], 'Asset_ID')
        self.assertGreater(payload['common_fields'], 0)


if __name__ == '__main__':
    unittest.main()
