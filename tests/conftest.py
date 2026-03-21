from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if 'swagger_ui_bundle' not in sys.modules:
    swagger_ui_bundle = types.ModuleType('swagger_ui_bundle')
    swagger_ui_bundle.swagger_ui_path = str(ROOT)
    sys.modules['swagger_ui_bundle'] = swagger_ui_bundle
