"""Make `web/py` importable so the bridge can be tested off-browser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py"))
