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


GEOJSON_DEUX_ZONES = (
    '{"type":"FeatureCollection","features":['
    '{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[5.0,45.0],[5.01,45.0],[5.01,45.01],[5.0,45.01],[5.0,45.0]]]}},'
    '{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[5.02,45.0],[5.03,45.0],[5.03,45.01],[5.02,45.01],[5.02,45.0]]]}}'
    ']}'
)


class _ReponseFactice:
    def __init__(self, corps):
        self.corps = corps.encode()

    def read(self):
        return self.corps

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestZonesDebordementGeorisques:

    def _zones(self, corps):
        from core.habitations import zones_georisques
        with patch.object(inondation, "_bbox_commune", return_value=(5.0, 45.0, 5.05, 45.02)), \
             patch("core.habitations.urllib.request.urlopen", return_value=_ReponseFactice(corps)):
            return zones_georisques("99010", "ALEA_SYNT_01_02MOY_FXX")

    def test_zones_unies(self):
        resultat = self._zones(GEOJSON_DEUX_ZONES)
        assert resultat["erreur"] is None
        assert resultat["polygone"].num_geom == 2

    def test_corps_vide_signifie_aucune_zone(self):
        resultat = self._zones("")
        assert resultat == {"polygone": None, "erreur": None}

    def test_point_dans_zone(self):
        from django.contrib.gis.geos import Point
        polygone = self._zones(GEOJSON_DEUX_ZONES)["polygone"]
        assert polygone.contains(Point(5.005, 45.005, srid=4326))
        assert not polygone.contains(Point(5.015, 45.005, srid=4326))


class TestDebitIgn:
    """L'IGN renvoie 429 au-delà de ~5 requêtes/s (20/10/2026) : le lot attend puis réessaie."""

    def test_lot_reessaye_apres_429(self):
        import urllib.error

        reponses = [
            urllib.error.HTTPError("u", 429, "Too Many Requests", {"Retry-After": "1"}, None),
            _ReponseFactice('{"elevations":[{"z":12.5},{"z":13.0}]}'),
        ]

        def urlopen(url, timeout):
            r = reponses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

        with patch.object(inondation.urllib.request, "urlopen", side_effect=urlopen), \
             patch.object(inondation.time, "sleep") as dodo:
            resultat = inondation._altitudes_lot([5.0, 5.001], [45.0, 45.0], 10)

        assert resultat == {10: 12.5, 11: 13.0}
        assert any(appel.args[0] >= 1 for appel in dodo.call_args_list)

    def test_creneaux_espaces(self, tmp_path):
        with patch.object(inondation, "_FICHIER_DEBIT_IGN", str(tmp_path / "debit")), \
             patch.object(inondation.time, "sleep") as dodo:
            for _ in range(3):
                inondation._attendre_creneau_ign()
        attentes = [appel.args[0] for appel in dodo.call_args_list]
        # 2e et 3e appels repoussés d'un intervalle (0,4 s) chacun environ
        assert len(attentes) == 2 and attentes[1] > attentes[0] > 0.3
