"""Make scripts/ importable, so the tests can attack the publish pipeline's decisions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
