"""Run the FastHTML app: python -m web"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main() -> None:
    host = os.environ.get("WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("WEB_PORT", "8088"))
    reload = os.environ.get("WEB_RELOAD", "0") == "1"
    uvicorn.run("web.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
