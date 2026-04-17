from __future__ import annotations

import sys
from pathlib import Path

_VENDORED_PACKAGE_DIR = Path(__file__).resolve().parent / "kogwistar"
if _VENDORED_PACKAGE_DIR.is_dir():
    sys.path.insert(0, str(_VENDORED_PACKAGE_DIR))

from kogwistar.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
