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
    avalanche, feux_satellite, meteo_forets, meteo_france, restrictions_eau, sources_ouvertes,
    vigilance_crues,
)
from core.models import (
    DangerFeuForet, ReleveMeteoForets, ReleveSourceOuverte, RestrictionEau, RisqueAvalanche,
    TronconVigilanceCrues,
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


# ── Risque d'avalanche ──────────────────────────────────────────────────────────────────────

def _massifs(*codes):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"code": code, "mountain": "Alpes du Nord", "title": f"Massif {code}",
                        "Departement": "Savoie", "Dep2": "Isère" if code == 2 else None},
         "geometry": {"type": "MultiPolygon", "coordinates": [[[
             [6.0 + code, 45.0], [6.5 + code, 45.0], [6.5 + code, 45.5], [6.0 + code, 45.5], [6.0 + code, 45.0]]]]}}
        for code in codes]}


def _bulletin(risque="3", demain="4"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<BULLETINS_NEIGE_AVALANCHE TYPEBULLETIN="BRA" ID="1" MASSIF="Chablais"
    DATEBULLETIN="2026-11-14T16:00:00" DATEVALIDITE="2026-11-15T18:00:00">
  <CARTOUCHERISQUE>
    <RISQUE RISQUE1="{risque}" RISQUEMAXI="{risque}" COMMENTAIRE="Indice de risque marqué." RISQUEMAXIJ2="{demain}"/>
    <RESUME>Départs spontanés : possibles

Déclenchements skieurs : plaques à vent</RESUME>
  </CARTOUCHERISQUE>
</BULLETINS_NEIGE_AVALANCHE>""".encode()


@pytest.fixture
def massifs_de_test(monkeypatch, cle_meteo):
    """Trois massifs suffisent, et l'attente entre deux bulletins est supprimée."""
    monkeypatch.setattr(avalanche, "MINIMUM_MASSIFS", 2)
    monkeypatch.setattr(avalanche.time, "sleep", lambda _secondes: None)


def _service(bulletins):
    """Faux service : `bulletins` donne, par code de massif, des octets XML, 404 ou une panne."""
    def repondre(adresse, params=None, **_reste):
        if adresse.endswith("liste-massifs"):
            return mock.Mock(status_code=200, json=lambda: _massifs(*bulletins), raise_for_status=lambda: None)
        reponse = bulletins[params["id-massif"]]
        if isinstance(reponse, Exception):
            raise reponse
        if reponse == 404:
            return mock.Mock(status_code=404)
        return mock.Mock(status_code=200, content=reponse, raise_for_status=lambda: None)
    return repondre


class TestRisqueAvalanche:

    def test_le_bulletin_donne_l_indice_du_jour_et_du_lendemain(self):
        bulletin = avalanche.analyser_bulletin(_bulletin())

        assert (bulletin["risque"], bulletin["risque_demain"]) == (3, 4)
        assert bulletin["commentaire"] == "Indice de risque marqué."
        assert bulletin["resume"] == "Départs spontanés : possibles\nDéclenchements skieurs : plaques à vent"
        # Les bulletins datent en heure de Paris, sans le dire : 18 h, c'est 17 h TU en novembre.
        assert bulletin["valide_jusqu_a"] == datetime.datetime(2026, 11, 15, 17, 0, tzinfo=UTC)

    @pytest.mark.parametrize("xml", [b"pas du xml", b"<BULLETINS_NEIGE_AVALANCHE/>", _bulletin(risque="", demain="")])
    def test_un_bulletin_sans_indice_lisible_vaut_pas_de_bulletin(self, xml):
        assert avalanche.analyser_bulletin(xml) is None

    def test_un_indice_hors_de_l_echelle_n_est_pas_pris(self):
        assert avalanche.analyser_bulletin(_bulletin(risque="3", demain="9"))["risque_demain"] is None

    def test_les_massifs_gardent_leur_contour_et_leurs_departements(self):
        massifs = avalanche.analyser_massifs(_massifs(1, 2))

        assert massifs[2]["nom"] == "Massif 2" and massifs[2]["departement_nom"] == "Savoie, Isère"
        assert massifs[1]["geometrie"].geom_type == "MultiPolygon"

    @pytest.mark.django_db
    def test_le_releve_ecrit_les_indices_et_compte_les_bulletins(self, massifs_de_test):
        service = _service({1: _bulletin("3", "4"), 2: _bulletin("1", "2"), 3: 404})

        with mock.patch("core.avalanche.requests.get", side_effect=service):
            assert avalanche.relever(MAINTENANT) == 2

        assert dict(RisqueAvalanche.objects.values_list("massif_code", "risque")) == {1: 3, 2: 1, 3: None}

    @pytest.mark.django_db
    def test_une_lecture_en_panne_garde_l_indice_precedent(self, massifs_de_test):
        """Constaté le 15/11/2026 : trois bulletins sur trente-cinq ont expiré. Un massif à
        risque fort ne doit pas redevenir « sans indice » pour une requête perdue."""
        with mock.patch("core.avalanche.requests.get", side_effect=_service({1: _bulletin("4", "4"), 2: _bulletin("2", "2")})):
            avalanche.relever(MAINTENANT)

        panne = requests.ReadTimeout("délai dépassé")
        with mock.patch("core.avalanche.requests.get", side_effect=_service({1: panne, 2: _bulletin("3", "3")})):
            assert avalanche.relever(MAINTENANT + datetime.timedelta(hours=6)) == 2

        assert dict(RisqueAvalanche.objects.values_list("massif_code", "risque")) == {1: 4, 2: 3}

    @pytest.mark.django_db
    def test_apres_plusieurs_pannes_de_suite_le_service_n_est_plus_appele(self, massifs_de_test, monkeypatch):
        """Un service manifestement indisponible ne doit pas recevoir trente-cinq appels de plus."""
        monkeypatch.setattr(avalanche, "PANNES_AVANT_ABANDON", 2)
        codes = {code: _bulletin("3", "3") for code in range(1, 7)}
        with mock.patch("core.avalanche.requests.get", side_effect=_service(codes)):
            avalanche.relever(MAINTENANT)

        panne = requests.ReadTimeout("délai dépassé")
        with mock.patch("core.avalanche.requests.get", side_effect=_service({code: panne for code in range(1, 7)})) as appel:
            avalanche.relever(MAINTENANT + datetime.timedelta(hours=6))

        # La liste des massifs, puis deux bulletins en panne : les quatre autres ne sont pas demandés.
        assert appel.call_count == 3
        assert set(RisqueAvalanche.objects.values_list("risque", flat=True)) == {3}      # indices gardés

    @pytest.mark.django_db
    def test_hors_saison_les_indices_s_effacent_et_le_releve_reussit(self, massifs_de_test):
        with mock.patch("core.avalanche.requests.get", side_effect=_service({1: _bulletin(), 2: _bulletin()})):
            avalanche.relever(MAINTENANT)

        with mock.patch("core.avalanche.requests.get", side_effect=_service({1: 404, 2: 404})):
            assert sources_ouvertes.relever_source("AVALANCHE", forcer=True) == "réussi"

        assert set(RisqueAvalanche.objects.values_list("risque", flat=True)) == {None}
        assert RisqueAvalanche.objects.count() == 2          # les contours restent

    @pytest.mark.django_db
    def test_une_liste_de_massifs_tronquee_ne_remplace_pas_la_copie(self, massifs_de_test, monkeypatch):
        monkeypatch.setattr(avalanche, "MINIMUM_MASSIFS", 20)

        with mock.patch("core.avalanche.requests.get", side_effect=_service({1: _bulletin()})):
            with pytest.raises(ValueError):
                avalanche.relever(MAINTENANT)

        assert RisqueAvalanche.objects.count() == 0

    @pytest.mark.django_db
    def test_la_lecture_ne_rend_que_les_massifs_de_l_emprise_le_plus_risque_d_abord(self, api_client, massifs_de_test):
        with mock.patch("core.avalanche.requests.get", side_effect=_service({1: _bulletin("2", "2"), 2: _bulletin("4", "3"), 9: _bulletin("5", "5")})):
            avalanche.relever(MAINTENANT)

        montagne = api_client.get(reverse("risque_avalanche"), {"bbox": "6.9,44.9,8.6,45.6"}).json()
        plaine = api_client.get(reverse("risque_avalanche"), {"lat": "48.85", "lon": "2.35"}).json()
        carte = api_client.get(reverse("risque_avalanche"), {"bbox": "6.9,44.9,8.6,45.6", "trace": "1"}).json()

        assert [(m["nom"], m["risque"]) for m in montagne["resultats"]] == [("Massif 2", 4), ("Massif 1", 2)]
        assert montagne["libelles"]["4"] == "fort" and "trace" not in montagne["resultats"][0]
        assert carte["resultats"][0]["trace"]["type"] == "MultiPolygon"
        # En plaine, liste vide : c'est ce qui dit à l'écran de ne pas afficher ce bloc.
        assert plaine["resultats"] == [] and plaine["emprise_connue"] is True


# ── Arrêtés de circulation des collectivités ────────────────────────────────────────────────

from core import arretes_circulation  # noqa: E402
from core.models import ArreteCirculation  # noqa: E402

_ENTETE_DATEX = ('<?xml version="1.0" encoding="UTF-8"?>'
                 '<d2:payload xmlns:d2="http://datex2.eu/schema/3/d2Payload" '
                 'xmlns:com="http://datex2.eu/schema/3/common" '
                 'xmlns:tro="http://datex2.eu/schema/3/trafficRegulation" '
                 'xmlns:loc="http://datex2.eu/schema/3/locationReferencing" '
                 'xmlns:dia="https://raw.githubusercontent.com/MTES-MCT/dialog/main/docs/spec/datex2" '
                 'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">')


def _mesure(genre="AccessRestriction", corps="<tro:accessRestrictionType>noEntry</tro:accessRestrictionType>",
            vehicules="", voie="Rue Henri Gandais", trace='{"type":"LineString","coordinates":[[4.38,45.43],[4.39,45.44]]}'):
    return f"""<tro:trafficRegulation><tro:status>active</tro:status>
      <tro:typeOfRegulation xsi:type="{genre}">{corps}</tro:typeOfRegulation>
      <tro:condition xsi:type="ConditionSet">{vehicules}
        <tro:conditions xsi:type="LocationCondition"><tro:locationByOrder xsi:type="loc:LinearLocation">
          <loc:supplementaryPositionalDescription><loc:roadInformation><loc:roadName>{voie}</loc:roadName></loc:roadInformation></loc:supplementaryPositionalDescription>
          <loc:_linearLocationExtension><loc:linearLocationExtended><dia:geoJsonGeometry>{trace}</dia:geoJsonGeometry></loc:linearLocationExtended></loc:_linearLocationExtension>
        </tro:locationByOrder></tro:conditions>
      </tro:condition></tro:trafficRegulation>"""


def _vehicules(poids=None, type_vehicule="heavyGoodsVehicle", inverse=False):
    tonnage = (f"<tro:grossWeightCharacteristic><com:comparisonOperator>greaterThan</com:comparisonOperator>"
               f"<com:grossVehicleWeight>{poids}</com:grossVehicleWeight></tro:grossWeightCharacteristic>") if poids else ""
    return (f'<tro:conditions xsi:type="VehicleCondition"><tro:negate>{"true" if inverse else "false"}</tro:negate>'
            f"<tro:vehicleCharacteristics><com:vehicleType>{type_vehicule}</com:vehicleType>{tonnage}"
            f"</tro:vehicleCharacteristics></tro:conditions>")


def _arrete(reference, *mesures, fin="2026-12-31T17:00:00+00:00"):
    fin_xml = f"<com:overallEndTime>{fin}</com:overallEndTime>" if fin else ""
    return f"""<tro:trafficRegulationOrder id="{reference}" version="1">
      <tro:description><com:values><com:value>Travaux de voirie</com:value></com:values></tro:description>
      <tro:issuingAuthority><com:values><com:value>Ville de Saint-Étienne</com:value></com:values></tro:issuingAuthority>
      <tro:status>madeAndImplemented</tro:status>
      <tro:validityByOrder><com:validityTimeSpecification>
        <com:overallStartTime>2026-01-01T07:00:00+00:00</com:overallStartTime>{fin_xml}
      </com:validityTimeSpecification></tro:validityByOrder>
      {"".join(mesures)}
      <tro:_trafficRegulationOrderExtension><tro:trafficRegulationOrderExtended>
        <dia:publicUrl>https://dialog.beta.gouv.fr/regulations/{reference}</dia:publicUrl>
      </tro:trafficRegulationOrderExtended></tro:_trafficRegulationOrderExtension>
    </tro:trafficRegulationOrder>"""


def _lire_arretes(tmp_path, *arretes):
    fichier = tmp_path / "dialog.xml"
    fichier.write_text(_ENTETE_DATEX + "".join(arretes) + "</d2:payload>", encoding="utf-8")
    return arretes_circulation.lire(str(fichier), MAINTENANT)


class TestArretesDeCirculation:

    def test_une_interdiction_sans_condition_est_une_fermeture(self, tmp_path):
        (arrete,) = _lire_arretes(tmp_path, _arrete("a1", _mesure()))

        assert arrete["categorie"] == "FERMETURE" and arrete["tonnage_max"] is None
        assert arrete["voies"] == "Rue Henri Gandais" and arrete["autorite"] == "Ville de Saint-Étienne"
        assert arrete["url"] == "https://dialog.beta.gouv.fr/regulations/a1"
        assert arrete["fin"] == datetime.datetime(2026, 12, 31, 17, 0, tzinfo=UTC)
        assert arrete["geometrie"].geom_type == "GeometryCollection" and arrete["location"].srid == 4326

    def test_une_interdiction_aux_poids_lourds_garde_son_tonnage(self, tmp_path):
        (arrete,) = _lire_arretes(tmp_path, _arrete("a1", _mesure(vehicules=_vehicules(poids="7.5"))))

        assert arrete["categorie"] == "POIDS_LOURDS" and arrete["tonnage_max"] == 7.5

    def test_une_exception_ne_restreint_pas_le_champ_de_l_interdiction(self, tmp_path):
        """« Sauf bus » ne fait pas de l'arrêté une interdiction limitée aux bus : la route
        reste fermée à tous les autres."""
        (arrete,) = _lire_arretes(tmp_path, _arrete("a1", _mesure(vehicules=_vehicules(type_vehicule="bus", inverse=True))))

        assert arrete["categorie"] == "FERMETURE"

    def test_vitesse_et_stationnement_ne_sont_pas_copies(self, tmp_path):
        vitesse = _mesure(genre="SpeedLimit", corps="")
        stationnement = _mesure(genre="StandingOrParkingRestriction", corps="")

        arretes = _lire_arretes(tmp_path, _arrete("v", vitesse), _arrete("s", stationnement), _arrete("f", _mesure()))

        assert [a["reference"] for a in arretes] == ["f"]

    def test_un_arrete_termine_n_est_pas_copie_un_permanent_l_est(self, tmp_path):
        arretes = _lire_arretes(
            tmp_path,
            _arrete("fini", _mesure(), fin="2026-11-01T00:00:00+00:00"),
            _arrete("permanent", _mesure(), fin=None))

        assert [(a["reference"], a["fin"]) for a in arretes] == [("permanent", None)]

    def test_la_mesure_la_plus_contraignante_donne_la_categorie(self, tmp_path):
        alternat = _mesure(genre="RoadOrCarriagewayOrLaneManagement", corps="", voie="Route de la Mailleraye")

        (arrete,) = _lire_arretes(tmp_path, _arrete("a1", alternat, _mesure(vehicules=_vehicules(poids="3.5")), _mesure()))

        assert arrete["categorie"] == "FERMETURE" and arrete["tonnage_max"] == 3.5
        assert arrete["voies"] == "Route de la Mailleraye, Rue Henri Gandais"

    def test_un_trace_imbrique_ou_abime_ne_fait_rien_planter(self, tmp_path):
        """Constaté sur le vrai fichier : certains tracés sont eux-mêmes des assemblages."""
        imbrique = ('{"type":"GeometryCollection","geometries":[{"type":"Point","coordinates":[4.38,45.43]},'
                    '{"type":"LineString","coordinates":[[4.38,45.43],[4.39,45.44]]}]}')

        arretes = _lire_arretes(tmp_path, _arrete("imb", _mesure(trace=imbrique)), _arrete("casse", _mesure(trace="pas du json")))

        assert [a["reference"] for a in arretes] == ["imb"]
        assert len(arretes[0]["geometrie"]) == 2

    @pytest.mark.django_db
    def test_un_fichier_tronque_ne_remplace_pas_la_copie(self, tmp_path):
        with pytest.raises(ValueError):
            arretes_circulation.enregistrer(_lire_arretes(tmp_path, _arrete("a1", _mesure())))

        assert ArreteCirculation.objects.count() == 0

    @pytest.mark.django_db
    def test_la_lecture_classe_les_fermetures_d_abord_et_les_temporaires_avant_les_permanentes(
            self, api_client, tmp_path, monkeypatch):
        monkeypatch.setattr(arretes_circulation, "MINIMUM_PLAUSIBLE", 1)
        loin = '{"type":"LineString","coordinates":[[2.34,48.85],[2.35,48.86]]}'
        arretes_circulation.enregistrer(_lire_arretes(
            tmp_path,
            _arrete("pl", _mesure(vehicules=_vehicules(poids="3.5"))),
            _arrete("permanente", _mesure(), fin=None),
            _arrete("temporaire", _mesure()),
            _arrete("paris", _mesure(trace=loin)),
        ))

        parametres = {"lat": "45.44", "lon": "4.39", "rayon_km": "10"}
        liste = api_client.get(reverse("arretes_circulation"), parametres).json()
        carte = api_client.get(reverse("arretes_circulation"), {**parametres, "trace": "1"}).json()

        assert [a["reference"] for a in liste["resultats"]] == ["temporaire", "permanente", "pl"]
        assert liste["bilan"] == {"FERMETURE": 2, "POIDS_LOURDS": 1, "ALTERNAT": 0}
        assert liste["resultats"][2]["categorie_libelle"] == "Interdite aux poids lourds"
        assert "trace" not in liste["resultats"][0]
        assert carte["resultats"][0]["trace"]["type"] == "GeometryCollection"
        assert liste["source"].startswith("DiaLog")


# ── Recours aux urgences ────────────────────────────────────────────────────────────────────

from core import sante_urgences  # noqa: E402
from core.models import IndicateurSante  # noqa: E402


def _semaine(departement, debut, semaine, taux, sos=None, champ="grippe"):
    return {"dep": departement, "semaine": semaine, "date_complet": debut,
            f"taux_passages_{champ}_sau": taux, f"taux_actes_{champ}_sos": sos}


class TestRecoursAuxUrgences:

    def test_la_derniere_semaine_et_la_precedente_sont_retenues(self):
        indicateurs = sante_urgences.analyser("GRIPPE", [
            _semaine("42", "2026-10-19", "2026-S43", 100.0),
            _semaine("42", "2026-11-02", "2026-S45", 241.196, 1136.4),
            _semaine("42", "2026-10-26", "2026-S44", 180.04),
        ])

        loire = indicateurs["42"]
        assert loire["semaine"] == "2026-S45" and loire["debut_semaine"] == datetime.date(2026, 11, 2)
        assert (loire["taux_urgences"], loire["taux_urgences_precedent"], loire["taux_sos"]) == (241.2, 180.0, 1136.4)

    def test_une_valeur_absente_reste_absente(self):
        (indicateur,) = sante_urgences.analyser("GRIPPE", [_semaine("42", "2026-11-02", "2026-S45", None)]).values()

        assert indicateur["taux_urgences"] is None and indicateur["taux_urgences_precedent"] is None

    @pytest.mark.parametrize("actuel, precedent, attendu", [
        (241.2, 180.0, "hausse"), (100.0, 180.0, "baisse"), (190.0, 180.0, "stable"),
        (5.0, 0.0, "hausse"), (0.0, 0.0, "stable"), (None, 180.0, ""), (241.2, None, ""),
    ])
    def test_la_tendance_ignore_le_bruit_d_une_semaine_a_l_autre(self, actuel, precedent, attendu):
        assert sante_urgences.tendance(actuel, precedent) == attendu

    def test_la_bronchiolite_est_demandee_pour_les_moins_d_un_an(self):
        with mock.patch("core.sante_urgences.requests.get") as appel:
            appel.return_value.json.return_value = []
            sante_urgences.telecharger("BRONCHIOLITE", MAINTENANT)

        (adresse,), options = appel.call_args
        assert adresse.endswith("/bronchiolite-passages-aux-urgences-et-actes-sos-medecins-departement/exports/json")
        assert options["params"]["where"] == "sursaud_cl_age_gene=\"0 an\" and date_complet >= date'2026-10-04'"
        assert "taux_passages_bronchio_sau" in options["params"]["select"]

    @pytest.mark.django_db
    def test_une_pathologie_en_panne_n_empeche_pas_les_autres(self, monkeypatch):
        monkeypatch.setattr(sante_urgences, "MINIMUM_PLAUSIBLE", 1)

        def service(code, _maintenant):
            if code == "COVID":
                raise requests.ConnectionError("coupé")
            champ = sante_urgences.PATHOLOGIES[code][2]
            return [_semaine("42", "2026-11-02", "2026-S45", 50.0, champ=champ)]

        with mock.patch("core.sante_urgences.telecharger", side_effect=service):
            assert sante_urgences.relever(MAINTENANT) == 3

        assert set(IndicateurSante.objects.values_list("pathologie", flat=True)) == {"GRIPPE", "GASTRO", "BRONCHIOLITE"}

    @pytest.mark.django_db
    def test_si_rien_ne_repond_le_releve_echoue_et_la_copie_reste(self, monkeypatch):
        IndicateurSante.objects.create(pathologie="GRIPPE", departement_code="42", semaine="2026-S44",
                                       debut_semaine=datetime.date(2026, 10, 26), taux_urgences=10, releve_le=MAINTENANT)

        with mock.patch("core.sante_urgences.telecharger", side_effect=requests.ConnectionError("coupé")):
            assert sources_ouvertes.relever_source("SANTE_URGENCES", forcer=True) == "échec"

        assert IndicateurSante.objects.count() == 1

    @pytest.mark.django_db
    def test_la_lecture_donne_les_quatre_pathologies_du_departement_avec_leur_tendance(self, api_client):
        def indicateur(pathologie, departement, taux, precedent):
            IndicateurSante.objects.create(
                pathologie=pathologie, departement_code=departement, semaine="2026-S45",
                debut_semaine=datetime.date(2026, 11, 2), taux_urgences=taux,
                taux_urgences_precedent=precedent, releve_le=timezone.now())
        indicateur("GRIPPE", "42", 241.2, 180.0)
        indicateur("COVID", "42", 30.0, 60.0)
        indicateur("GRIPPE", "69", 999.0, 999.0)

        corps = api_client.get(reverse("sante_urgences"), {"departement": "42"}).json()

        assert corps["departement_nom"] == "Loire"
        assert [(i["libelle"], i["tendance"]) for i in corps["indicateurs"]] == [("Grippe", "hausse"), ("Covid-19", "baisse")]
        assert "Santé publique France" in corps["source"]
        assert api_client.get(reverse("sante_urgences")).json()["indicateurs"] == []      # sans département
