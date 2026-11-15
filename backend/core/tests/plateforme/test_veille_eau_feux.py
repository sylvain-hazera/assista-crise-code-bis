"""Veille du territoire, deuxième lot (15/11/2026) : vigilance crues par tronçon (Vigicrues),
restrictions d'eau (VigiEau), surfaces brûlées (EFFIS), météo des forêts (Météo-France).

Aucun test n'appelle l'extérieur. Les trois premières sources sont rejouées d'après des
extraits réels réduits. La quatrième a été écrite HORS SAISON, sans réponse réelle à lire :
ses tests portent sur ce qui peut être tenu sans la connaître -- l'état « hors saison », la
conservation de la réponse brute, et le signalement d'une réponse non comprise."""
import datetime
import json
from unittest import mock

import pytest
import requests
from django.contrib.gis.geos import MultiLineString, LineString, MultiPolygon, Point, Polygon
from django.urls import reverse
from django.utils import timezone

from core import (
    feux_satellite, meteo_forets, meteo_france, restrictions_eau, sources_ouvertes,
    vigilance_crues,
)
from core.models import (
    DangerFeuForet, ReleveMeteoForets, ReleveSourceOuverte, RestrictionEau, TronconVigilanceCrues,
    ZoneBrulee,
)

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 9, 30, tzinfo=UTC)


# ── Vigilance crues ─────────────────────────────────────────────────────────────────────────

def _troncon(code, nom, niveau, points=((4.38, 45.43), (4.40, 45.45), (4.42, 45.46))):
    return {"type": "Feature",
            "properties": {"CdEntCru": code, "lbentcru": nom, "NivInfViCr": niveau},
            "geometry": {"type": "MultiLineString", "coordinates": [[list(p) for p in points]]}}


def _fichier(*troncons):
    return {"type": "FeatureCollection", "DtHrInfoVigiCru": "2026-11-15T08:55:47+00:00",
            "features": list(troncons)}


class TestVigilanceCrues:

    def test_un_troncon_devient_une_ligne_avec_son_niveau(self):
        publie_le, (troncon,) = vigilance_crues.analyser(_fichier(_troncon("LO12", "Furan", 3)))

        assert publie_le == datetime.datetime(2026, 11, 15, 8, 55, 47, tzinfo=UTC)
        assert (troncon["code"], troncon["nom"], troncon["niveau"]) == ("LO12", "Furan", 3)
        assert troncon["geometrie"].geom_type == "MultiLineString" and troncon["geometrie"].srid == 4326

    def test_le_trace_est_allege_sans_etre_perdu(self):
        """Le fichier d'origine porte un point tous les quelques mètres."""
        dense = [(4.38 + i * 0.00001, 45.43) for i in range(500)]

        _publie, (troncon,) = vigilance_crues.analyser(_fichier(_troncon("LO12", "Furan", 1, dense)))

        assert 2 <= troncon["geometrie"].num_coords < 20
        assert abs(troncon["geometrie"].extent[2] - dense[-1][0]) < 1e-6     # les bouts restent

    @pytest.mark.parametrize("defaut", [
        {"CdEntCru": ""}, {"NivInfViCr": None}, {"NivInfViCr": 9}, {"NivInfViCr": "rouge"},
    ])
    def test_un_troncon_sans_code_ou_au_niveau_illisible_est_ignore(self, defaut):
        casse = _troncon("LO12", "Furan", 1)
        casse["properties"].update(defaut)

        _publie, troncons = vigilance_crues.analyser(_fichier(casse, _troncon("LO13", "Gier", 2)))

        assert [t["code"] for t in troncons] == ["LO13"]

    def test_un_trace_illisible_ne_fait_pas_perdre_les_autres(self):
        casse = _troncon("LO12", "Furan", 1)
        casse["geometry"] = {"type": "MultiLineString", "coordinates": "pas un tracé"}

        _publie, troncons = vigilance_crues.analyser(_fichier(casse, _troncon("LO13", "Gier", 2)))

        assert [t["code"] for t in troncons] == ["LO13"]

    @pytest.mark.django_db
    def test_un_fichier_tronque_ne_remplace_pas_la_copie(self, monkeypatch):
        monkeypatch.setattr(vigilance_crues, "MINIMUM_PLAUSIBLE", 2)
        publie_le, troncons = vigilance_crues.analyser(
            _fichier(_troncon("A", "Furan", 1), _troncon("B", "Gier", 2), _troncon("C", "Ondaine", 1)))
        vigilance_crues.enregistrer(publie_le, troncons)

        with pytest.raises(ValueError):
            vigilance_crues.enregistrer(publie_le, troncons[:1])

        assert TronconVigilanceCrues.objects.count() == 3

    @pytest.mark.django_db
    def test_le_releve_met_a_jour_les_niveaux_et_retire_ce_qui_a_disparu(self, monkeypatch):
        monkeypatch.setattr(vigilance_crues, "MINIMUM_PLAUSIBLE", 2)
        publie_le, troncons = vigilance_crues.analyser(
            _fichier(_troncon("A", "Furan", 1), _troncon("B", "Gier", 1), _troncon("C", "Ondaine", 1)))
        vigilance_crues.enregistrer(publie_le, troncons)

        publie_le, troncons = vigilance_crues.analyser(
            _fichier(_troncon("A", "Furan", 3), _troncon("B", "Gier", 1)))
        vigilance_crues.enregistrer(publie_le, troncons)

        assert dict(TronconVigilanceCrues.objects.values_list("code", "niveau")) == {"A": 3, "B": 1}

    @pytest.mark.django_db
    def test_la_lecture_rend_les_troncons_de_l_emprise_les_plus_preoccupants_d_abord(self, api_client):
        def troncon(code, nom, niveau, lon, lat):
            TronconVigilanceCrues.objects.create(
                code=code, nom=nom, niveau=niveau, releve_le=timezone.now(),
                geometrie=MultiLineString(LineString((lon, lat), (lon + 0.02, lat + 0.02)), srid=4326))
        troncon("A", "Furan", 1, 4.38, 45.43)
        troncon("B", "Gier", 3, 4.50, 45.47)
        troncon("C", "Seine", 4, 2.34, 48.85)

        parametres = {"lat": "45.44", "lon": "4.39", "rayon_km": "30"}
        liste = api_client.get(reverse("vigilance_crues"), parametres).json()
        carte = api_client.get(reverse("vigilance_crues"), {**parametres, "trace": "1"}).json()

        assert [(t["nom"], t["couleur"]) for t in liste["resultats"]] == [("Gier", "orange"), ("Furan", "vert")]
        assert "trace" not in liste["resultats"][0]
        assert carte["resultats"][0]["trace"]["type"] == "MultiLineString"
        assert liste["source"].startswith("Vigicrues")


# ── Restrictions d'eau ──────────────────────────────────────────────────────────────────────

def _departement(code, maximum=None, sup=None, sou=None, aep=None):
    return {"code": code, "nom": "x", "region": "y", "niveauGraviteMax": maximum,
            "niveauGraviteSupMax": sup, "niveauGraviteSouMax": sou, "niveauGraviteAepMax": aep}


class TestRestrictionsEau:

    def test_les_niveaux_sont_lus_par_type_d_eau(self):
        (loire, allier) = restrictions_eau.analyser([
            _departement("42", "alerte_renforcee", "alerte_renforcee", "alerte", None),
            _departement("03"),
        ])

        assert loire == {"departement_code": "42", "niveau": "alerte_renforcee",
                         "niveau_superficielle": "alerte_renforcee", "niveau_souterraine": "alerte",
                         "niveau_potable": ""}
        assert allier["niveau"] == ""           # aucune restriction : chaîne vide, pas None

    def test_un_niveau_inconnu_n_est_pas_recopie(self):
        (departement,) = restrictions_eau.analyser([_departement("42", "catastrophe", "alerte")])

        assert departement["niveau"] == "" and departement["niveau_superficielle"] == "alerte"

    def test_tant_que_le_jour_n_est_pas_publie_on_prend_la_veille(self):
        pas_encore = mock.Mock(status_code=404)
        hier = mock.Mock(status_code=200, json=lambda: [_departement("42", "alerte")],
                         raise_for_status=lambda: None)

        with mock.patch("core.restrictions_eau.requests.get", side_effect=[pas_encore, hier]) as appel:
            date, donnees = restrictions_eau.telecharger(MAINTENANT)

        assert date == datetime.date(2026, 11, 14) and len(donnees) == 1
        assert [a.kwargs["params"]["date"] for a in appel.call_args_list] == ["2026-11-15", "2026-11-14"]

    def test_sans_aucune_date_publiee_le_releve_echoue_proprement(self):
        with mock.patch("core.restrictions_eau.requests.get", return_value=mock.Mock(status_code=404)):
            with pytest.raises(ValueError):
                restrictions_eau.telecharger(MAINTENANT)

    @pytest.mark.django_db
    def test_une_reponse_tronquee_ne_remplace_pas_la_copie(self):
        with pytest.raises(ValueError):
            restrictions_eau.enregistrer(datetime.date(2026, 11, 14), restrictions_eau.analyser(
                [_departement("42", "alerte")]))

        assert RestrictionEau.objects.count() == 0

    @pytest.mark.django_db
    def test_la_lecture_donne_mon_departement_et_classe_les_autres_par_gravite(self, api_client, monkeypatch):
        monkeypatch.setattr(restrictions_eau, "MINIMUM_PLAUSIBLE", 2)
        restrictions_eau.enregistrer(datetime.date(2026, 11, 14), restrictions_eau.analyser([
            _departement("42", "alerte", "alerte", None, None),
            _departement("69", "crise", "crise", "crise", "alerte"),
            _departement("03"),
        ]))

        corps = api_client.get(reverse("restrictions_eau"), {"departement": "42"}).json()

        assert corps["mon_departement"]["nom"] == "Loire" and corps["mon_departement"]["niveau"] == "alerte"
        assert [d["departement_code"] for d in corps["departements"]] == ["69", "42"]   # l'Allier n'y est pas
        assert corps["libelles"]["alerte_renforcee"] == "Alerte renforcée"
        assert corps["date_donnees"] == "2026-11-14"


# ── Surfaces brûlées ────────────────────────────────────────────────────────────────────────

def _zone(reference, pays="FR", commune="Casamaccioli", surface="30"):
    return {"type": "Feature",
            "properties": {"id": reference, "FIREDATE": "2026-10-16 12:19:00", "COUNTRY": pays,
                           "PROVINCE": "Haute-Corse", "COMMUNE": commune, "AREA_HA": surface},
            "geometry": {"type": "Polygon", "coordinates": [[
                [9.0, 42.3], [9.01, 42.3], [9.01, 42.31], [9.0, 42.31], [9.0, 42.3]]]}}


class TestSurfacesBrulees:

    def test_une_zone_devient_un_contour_date_et_mesure(self):
        (zone,) = feux_satellite.analyser({"features": [_zone("288759")]})

        assert zone["reference"] == "288759" and zone["commune_nom"] == "Casamaccioli"
        assert zone["surface_ha"] == 30.0
        assert zone["date_feu"] == datetime.datetime(2026, 10, 16, 12, 19, tzinfo=UTC)
        assert zone["geometrie"].geom_type == "MultiPolygon"
        assert round(zone["location"].x, 3) == 9.005

    def test_seules_les_zones_situees_en_france_sont_gardees(self):
        """L'emprise demandée est un rectangle : elle déborde sur l'Italie et l'Espagne."""
        zones = feux_satellite.analyser({"features": [_zone("1", pays="IT"), _zone("2"), _zone("3", pays="ES")]})

        assert [z["reference"] for z in zones] == ["2"]

    def test_la_demande_porte_sur_la_france_entiere_latitude_d_abord(self):
        with mock.patch("core.feux_satellite.requests.get") as appel:
            appel.return_value.json.return_value = {"features": []}
            feux_satellite.telecharger()

        assert appel.call_args.kwargs["params"]["bbox"] == "41,-5.5,51.5,10,EPSG:4326"

    def test_une_reponse_sans_liste_est_une_panne_pas_une_absence_de_feu(self):
        with mock.patch("core.feux_satellite.requests.get") as appel:
            appel.return_value.json.return_value = {"erreur": "service indisponible"}
            with pytest.raises(ValueError):
                feux_satellite.telecharger()

    @pytest.mark.django_db
    def test_l_hiver_une_liste_vide_vide_la_table_sans_erreur(self):
        feux_satellite.enregistrer(feux_satellite.analyser({"features": [_zone("1"), _zone("2")]}))

        assert feux_satellite.enregistrer([]) == 0
        assert ZoneBrulee.objects.count() == 0

    @pytest.mark.django_db
    def test_la_lecture_borne_a_l_emprise_et_ne_joint_le_contour_que_sur_demande(self, api_client):
        feux_satellite.enregistrer(feux_satellite.analyser({"features": [_zone("1")]}))
        ZoneBrulee.objects.create(
            reference="loin", surface_ha=80, location=Point(-1.5, 43.3, srid=4326), releve_le=timezone.now(),
            geometrie=MultiPolygon(Polygon(((-1.5, 43.3), (-1.49, 43.3), (-1.49, 43.31), (-1.5, 43.3))), srid=4326))

        parametres = {"lat": "42.3", "lon": "9.0", "rayon_km": "20"}
        liste = api_client.get(reverse("zones_brulees"), parametres).json()
        carte = api_client.get(reverse("zones_brulees"), {**parametres, "trace": "1"}).json()

        assert [z["reference"] for z in liste["resultats"]] == ["1"]
        assert "trace" not in liste["resultats"][0] and liste["resultats"][0]["distance_km"] < 2
        assert carte["resultats"][0]["trace"]["type"] == "MultiPolygon"
        assert "Copernicus" in liste["source"]


# ── Météo des forêts ────────────────────────────────────────────────────────────────────────

@pytest.fixture
def cle_meteo(tmp_path, monkeypatch):
    fichier = tmp_path / "cle"
    fichier.write_text("a.b.c")
    monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))


def _reponse(statut, contenu=b"", type_contenu="application/json"):
    reponse = mock.Mock(status_code=statut, content=contenu, headers={"content-type": type_contenu})
    reponse.raise_for_status.side_effect = (
        requests.HTTPError(response=reponse) if statut >= 400 else None)
    return reponse


class TestMeteoDesForets:

    @pytest.mark.django_db
    def test_hors_saison_le_releve_reussit_a_vide(self, cle_meteo):
        """Constaté le 15/11/2026 : l'API répond 404 « no matching blob » d'octobre à mai."""
        DangerFeuForet.objects.create(departement_code="13", niveau_demain=4, releve_le=MAINTENANT)

        with mock.patch("core.meteo_forets.requests.get", return_value=_reponse(404, b'{"detail":"no matching blob"}')):
            assert meteo_forets.relever(MAINTENANT) == 0

        assert DangerFeuForet.objects.count() == 0       # le danger de l'été dernier ne reste pas affiché
        etat = ReleveMeteoForets.objects.get()
        assert etat.en_saison is False and etat.compris is True

    @pytest.mark.django_db
    def test_hors_saison_la_source_n_est_pas_signalee_en_panne(self, cle_meteo):
        with mock.patch("core.meteo_forets.requests.get", return_value=_reponse(404)):
            assert sources_ouvertes.relever_source("METEO_FORETS", forcer=True) == "réussi"

        assert ReleveSourceOuverte.objects.get(pk="METEO_FORETS").erreur == ""
        assert sources_ouvertes.est_perime("METEO_FORETS") is False

    @pytest.mark.parametrize("contenu", [
        # Trois formes plausibles : la vraie n'a pas pu être constatée (voir l'en-tête du module).
        {"departements": [{"code": "13", "niveau_j1": 4, "niveau_j2": 3}, {"code": "2A", "niveau_j1": 2, "niveau_j2": 2}]},
        [{"dep": "13", "danger_demain": 4, "danger_apres_demain": 3}, {"dep": "2A", "danger_demain": 2, "danger_apres_demain": 2}],
        {"product": {"zones": [{"domain_id": "13", "risque": {"j1": 4, "j2": 3}}, {"domain_id": "2A", "risque": {"j1": 2, "j2": 2}}]}},
    ])
    def test_l_analyse_ne_depend_pas_des_noms_de_champs(self, contenu):
        niveaux = meteo_forets.analyser("application/json", json.dumps(contenu).encode())

        assert niveaux == {"13": (4, 3), "2A": (2, 2)}

    def test_un_niveau_hors_echelle_n_est_pas_pris(self):
        contenu = json.dumps([{"code": "13", "niveau_j1": 7}, {"code": "83", "niveau_j1": 3}]).encode()

        assert meteo_forets.analyser("application/json", contenu) == {"83": (3, None)}

    def test_une_reponse_qui_n_est_pas_du_json_ne_fait_rien_planter(self):
        assert meteo_forets.analyser("application/zip", b"PK\x03\x04\x00\xff") == {}

    @pytest.mark.django_db
    def test_une_carte_comprise_est_ecrite_et_la_reponse_brute_gardee(self, cle_meteo):
        contenu = json.dumps([{"code": "13", "niveau_j1": 4, "niveau_j2": 3}]).encode()

        with mock.patch("core.meteo_forets.requests.get", return_value=_reponse(200, contenu)):
            assert meteo_forets.relever(MAINTENANT) == 1

        danger = DangerFeuForet.objects.get(pk="13")
        assert (danger.niveau_demain, danger.niveau_apres_demain) == (4, 3)
        etat = ReleveMeteoForets.objects.get()
        assert etat.en_saison and etat.compris and bytes(etat.brut) == contenu

    @pytest.mark.django_db
    def test_une_carte_non_comprise_est_signalee_et_son_contenu_garde(self, cle_meteo):
        """Le cas pour lequel tout ce dispositif existe : en juin, la vraie réponse n'a pas la
        forme devinée. Il ne faut ni afficher « rien à signaler », ni perdre l'échantillon."""
        contenu = b"PK\x03\x04 une archive, par exemple"

        with mock.patch("core.meteo_forets.requests.get", return_value=_reponse(200, contenu, "application/zip")):
            assert sources_ouvertes.relever_source("METEO_FORETS", forcer=True) == "échec"

        etat = ReleveMeteoForets.objects.get()
        assert etat.en_saison is True and etat.compris is False
        assert bytes(etat.brut) == contenu and etat.type_contenu == "application/zip"
        assert "non comprise" in ReleveSourceOuverte.objects.get(pk="METEO_FORETS").erreur

    @pytest.mark.django_db
    def test_la_lecture_dit_hors_saison_ou_donne_le_danger(self, api_client):
        assert api_client.get(reverse("meteo_forets")).json()["en_saison"] is False

        ReleveMeteoForets.objects.create(pk=1, en_saison=True, compris=True, releve_le=timezone.now())
        DangerFeuForet.objects.create(departement_code="13", niveau_demain=4, niveau_apres_demain=3, releve_le=timezone.now())
        DangerFeuForet.objects.create(departement_code="42", niveau_demain=1, niveau_apres_demain=2, releve_le=timezone.now())

        corps = api_client.get(reverse("meteo_forets"), {"departement": "42"}).json()

        assert corps["en_saison"] is True and corps["compris"] is True
        assert corps["mon_departement"]["niveau_apres_demain"] == 2
        assert [d["departement_code"] for d in corps["departements"]] == ["13"]    # élevé ou plus
        assert corps["libelles"]["4"] == "très élevé"

    def test_sans_cle_rien_ne_part(self, tmp_path, monkeypatch):
        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(tmp_path / "absente"))
        with mock.patch("core.meteo_forets.requests.get") as appel:
            with pytest.raises(meteo_france.CleAbsente):
                meteo_forets.telecharger()
        appel.assert_not_called()
