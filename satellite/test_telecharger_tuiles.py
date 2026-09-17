"""Tests de telecharger_tuiles.py — bbox_zone est vérifié contre le vrai fichier
data/departements_limitrophes.json (généré depuis des géométries officielles, pas un mock) ;
extraire() est vérifié avec subprocess.run mocké, aucun vrai téléchargement en test."""
from unittest.mock import patch

import pytest

import telecharger_tuiles as tt


def test_departements_limitrophes_charge_96_departements():
    departements = tt._charger_departements()
    assert len(departements) == 96


def test_bbox_zone_sans_limitrophes_egale_la_bbox_du_departement():
    departements = tt._charger_departements()
    bbox = tt.bbox_zone("38", inclure_limitrophes=False, departements=departements)
    assert tuple(bbox) == tuple(departements["38"]["bbox"])


def test_bbox_zone_avec_limitrophes_est_plus_large():
    departements = tt._charger_departements()
    bbox_seule = tt.bbox_zone("38", inclure_limitrophes=False, departements=departements)
    bbox_large = tt.bbox_zone("38", inclure_limitrophes=True, departements=departements)
    assert bbox_large[0] <= bbox_seule[0]
    assert bbox_large[1] <= bbox_seule[1]
    assert bbox_large[2] >= bbox_seule[2]
    assert bbox_large[3] >= bbox_seule[3]


def test_bbox_zone_departement_inconnu_leve_une_erreur():
    with pytest.raises(ValueError):
        tt.bbox_zone("999", departements=tt._charger_departements())


def test_isere_a_les_bons_limitrophes_connus():
    # Sanity check contre la géographie réelle, pas juste contre le fichier lui-même — si ce
    # test casse après une régénération du fichier, c'est le fichier qu'il faut suspecter.
    departements = tt._charger_departements()
    assert departements["38"]["limitrophes"] == ["01", "05", "07", "26", "42", "69", "73"]


def test_paris_a_les_bons_limitrophes_connus():
    departements = tt._charger_departements()
    assert departements["75"]["limitrophes"] == ["92", "93", "94"]


def test_extraire_appelle_pmtiles_avec_la_bonne_bbox(tmp_path):
    sortie = str(tmp_path / "tuiles.pmtiles")
    with patch("telecharger_tuiles.subprocess.run") as mock_run:
        tt.extraire("38", sortie, source="https://example.test/build.pmtiles", maxzoom=12)

    mock_run.assert_called_once()
    commande = mock_run.call_args.args[0]
    assert commande[0] == "pmtiles"
    assert commande[1] == "extract"
    assert commande[2] == "https://example.test/build.pmtiles"
    assert commande[3] == sortie
    assert any(arg.startswith("--bbox=") for arg in commande)
    assert "--maxzoom=12" in commande


def test_extraire_sans_source_leve_une_erreur_claire(monkeypatch):
    monkeypatch.setattr(tt, "PMTILES_SOURCE_DEFAUT", None)
    with pytest.raises(RuntimeError):
        tt.extraire("38", "/tmp/sortie.pmtiles", source=None)
