"""Grille d'altitude IGN de la simulation d'inondation (core/inondation.py) : relance des lots en
échec, refus de mettre en cache une grille incomplète, réutilisation d'une grille complète d'un
autre environnement -- correctif du 20/10/2026 (Portets en démo : l'IGN, lent, n'avait renvoyé que
~10 % des lots ; la grille trouée, cachée pour toujours, donnait 0,2 km² inondés au lieu de 7)."""
from unittest.mock import patch

import pytest

from core import inondation
from core.models import GrilleAltimetrieCommune

# Petite commune fictive : bbox minuscule -> quelques points seulement.
BBOX = (5.0, 45.0, 5.003, 45.002)
# Assez grande pour plusieurs lots de 200 points (pas de 20 m).
BBOX_GRANDE = (5.0, 45.0, 5.01, 45.008)


def _lot_toujours_ok(lons, lats, debut):
    return {debut + i: 100.0 + i for i in range(len(lons))}


@pytest.mark.django_db
class TestGrilleAltitude:

    def test_lots_en_echec_relances_puis_complets(self):
        appels = {}

        def lot_echoue_une_fois(lons, lats, debut):
            appels[debut] = appels.get(debut, 0) + 1
            if appels[debut] == 1:
                return {}          # 1re tentative : service muet pour CHAQUE lot
            return _lot_toujours_ok(lons, lats, debut)

        with patch.object(inondation, "_altitudes_lot", side_effect=lot_echoue_une_fois), \
             patch.object(inondation.time, "sleep"):
            altitudes = inondation._altitudes_ign_par_lots([5.0] * 450, [45.0] * 450, taille_lot=200)

        assert None not in altitudes
        assert all(n == 2 for n in appels.values())   # chaque lot relancé une fois

    def test_grille_incomplete_refusee_et_jamais_cachee(self):
        def lot_moitie(lons, lats, debut):
            return _lot_toujours_ok(lons, lats, debut) if debut == 0 else {}

        with patch.object(inondation, "_bbox_commune", return_value=BBOX_GRANDE), \
             patch.object(inondation, "_altitudes_lot", side_effect=lot_moitie), \
             patch.object(inondation.time, "sleep"):
            # pas de 20 m -> plusieurs lots ; seul le premier répond
            with pytest.raises(inondation.GrilleAltitudeIncomplete):
                inondation.grille_altitude_commune("99001", pas_metres=20, environment="DEMO")

        assert not GrilleAltimetrieCommune.objects.filter(commune_code="99001").exists()

    def test_grille_complete_mise_en_cache(self):
        with patch.object(inondation, "_bbox_commune", return_value=BBOX), \
             patch.object(inondation, "_altitudes_lot", side_effect=_lot_toujours_ok):
            points = inondation.grille_altitude_commune("99002", pas_metres=20, environment="DEMO")

        assert points
        assert GrilleAltimetrieCommune.objects.filter(commune_code="99002", environment="DEMO").exists()

    def test_grille_complete_d_un_autre_environnement_reutilisee_sans_ign(self):
        with patch.object(inondation, "_bbox_commune", return_value=BBOX), \
             patch.object(inondation, "_altitudes_lot", side_effect=_lot_toujours_ok):
            points_prod = inondation.grille_altitude_commune("99003", pas_metres=20, environment="PROD")

        with patch.object(inondation, "_bbox_commune", return_value=BBOX), \
             patch.object(inondation, "_altitudes_lot") as ign:
            points_demo = inondation.grille_altitude_commune("99003", pas_metres=20, environment="DEMO")

        ign.assert_not_called()
        assert points_demo == points_prod
        assert GrilleAltimetrieCommune.objects.filter(commune_code="99003", environment="DEMO").exists()
