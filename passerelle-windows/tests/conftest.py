import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def dossier_isole(tmp_path, monkeypatch):
    """Chaque test a son propre dossier de données, et le coffre de développement."""
    monkeypatch.setenv("ASSISTA_PASSERELLE_DOSSIER", str(tmp_path / "donnees"))
    monkeypatch.setenv("ASSISTA_PASSERELLE_DEV", "1")
    return tmp_path
