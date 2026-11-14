"""Ce que le site distribue doit correspondre aux sources. Sinon un PC installerait une
application ou un pont d'avant la dernière correction, sans que rien ne le signale."""
import importlib.util
import zipfile
import io
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("construire", RACINE / "construire.py")
construire = importlib.util.module_from_spec(spec)
spec.loader.exec_module(construire)

depot_complet = (construire.DEPOT / "meshcore-bridge" / "bridge.py").exists()
pytestmark = pytest.mark.skipif(not depot_complet, reason="dépôt incomplet (ponts absents)")


def test_l_archive_distribuee_est_a_jour():
    assert construire.perimes() == [], "relancez : python3 passerelle-windows/construire.py"


def test_l_archive_est_reproductible():
    assert construire.archive() == construire.archive()


def test_l_archive_contient_l_application_et_les_deux_ponts_sans_les_tests():
    noms = set(zipfile.ZipFile(io.BytesIO(construire.archive())).namelist())
    for attendu in ("passerelle/__main__.py", "passerelle/lanceur.py", "ponts/meshcore/bridge.py",
                    "ponts/meshcore/admin_meshcore.py", "ponts/meshtastic/bridge.py",
                    "ponts/meshtastic/crypto.py", "requirements.txt", "desinstaller.bat",
                    "passerelle.ico"):
        assert attendu in noms, attendu
    assert not [n for n in noms if "test_" in n]
