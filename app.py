from __future__ import annotations

import os

from dotenv import load_dotenv

from vigilance_assets.runtime import create_runtime_app

load_dotenv()

app = create_runtime_app()


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    host = os.getenv("VIGILANCE_HOST", "0.0.0.0")
    port = int(os.getenv("PORT", os.getenv("VIGILANCE_PORT", "8000")))
    debug = _env_flag("FLASK_DEBUG") or _env_flag("VIGILANCE_DEBUG")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
