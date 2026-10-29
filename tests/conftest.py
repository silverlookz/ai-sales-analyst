import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    from generate_data import build
    return build(tmp_path_factory.mktemp("db") / "sales.db")
