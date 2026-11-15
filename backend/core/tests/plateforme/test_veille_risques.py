"""Veille du territoire, troisième lot (15/11/2026) : radioactivité ambiante (Téléray),
séismes et sismicité des volcans (BCSF-Rénass), carte nationale des défibrillateurs (Géo'DAE).

Aucun test n'appelle l'extérieur : les réponses sont des extraits réels réduits."""
import datetime
import io
from unittest import mock

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone

from core import defibrillateurs, radioactivite, seismes, sources_ouvertes
from core.models import Defibrillateur, MesureRadioactivite, ReleveSourceOuverte, Seisme

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 16, 0, tzinfo=UTC)


# ── Radioactivité ambiante ──────────────────────────────────────────────────────────────────

def _mesure(identifiant, instant, debit=99, fond=105.2, strategie="NATIONAL", validation="valide",
            nom="ST-ETIENNE", position=(4.387, 45.443)):
    return {"type": "Feature", "time": instant,
            "geometry": {"type": "Point", "coordinates": list(position)},
            "properties": {"irsnId": identifiant, "publicName": nom, "strategie": strategie,
                           "doseRateRaw": debit, "bruitdefond": fond, "validation": validation}}


def _reponse(*mesures):
    return {"type": "FeatureCollection", "total": len(mesures), "features": list(mesures)}


class TestRadioactivite:

    def test_la_mesure_la_plus_recente_de_chaque_balise_est_gardee(self):
        mesures = radioactivite.analyser(_reponse(
            _mesure(1039, "2026-11-15T15:40:12.000Z", debit=99),
            _mesure(1039, "2026-11-15T15:50:12.000Z", debit=101),
            _mesure(1039, "2026-11-15T15:30:12.000Z", debit=97),
        ))

        assert list(mesures) == [1039]
        balise = mesures[1039]
        assert balise["debit_nsv_h"] == 101.0 and balise["bruit_de_fond_nsv_h"] == 105.2
        assert balise["mesure_le"] == datetime.datetime(2026, 11, 15, 15, 50, 12, tzinfo=UTC)
        assert balise["nom"] == "ST-ETIENNE" and balise["valide"] is True

    def test_les_balises_des_ambassades_ne_sont_pas_copiees(self):
        mesures = radioactivite.analyser(_reponse(
            _mesure(1000, "2026-11-15T15:50:00.000Z", strategie="AMBASSADE", nom="TOKYO-JAPON"),
            _mesure(1039, "2026-11-15T15:50:00.000Z"),
            _mesure(2001, "2026-11-15T15:50:00.000Z", strategie="INB", nom="TRICASTIN"),
        ))

        assert set(mesures) == {1039, 2001}
        assert mesures[2001]["proche_installation"] is True and mesures[1039]["proche_installation"] is False

    def test_une_mesure_non_validee_est_gardee_et_signalee(self):
        (balise,) = radioactivite.analyser(_reponse(
            _mesure(1039, "2026-11-15T15:50:00.000Z", validation="non valide"))).values()

        assert balise["valide"] is False

    @pytest.mark.parametrize("abimee", [
        {"properties": {"irsnId": 1, "doseRateRaw": 90}, "time": "2026-11-15T15:50:00.000Z"},          # sans position
        {**_mesure(1, "pas une date")},
        {**_mesure(1, "2026-11-15T15:50:00.000Z", debit=None)},
    ])
    def test_une_mesure_abimee_est_ignoree_sans_faire_perdre_les_autres(self, abimee):
        mesures = radioactivite.analyser(_reponse(abimee, _mesure(1039, "2026-11-15T15:50:00.000Z")))

        assert list(mesures) == [1039]

    def test_la_demande_couvre_la_derniere_heure_triee_de_la_plus_recente(self):
        """Constaté le 15/11/2026 : le service reçoit les mesures par paquets, avec du retard ;
        vingt-cinq minutes ne rendaient que cinq balises. Et sans tri, le plafond coupait les
        mesures les plus récentes."""
        with mock.patch("core.radioactivite.requests.get") as appel:
            appel.return_value.json.return_value = _reponse()
            radioactivite.telecharger(MAINTENANT)

        (adresse,), options = appel.call_args
        assert adresse == "https://teleray.asnr.fr/api/measures"
        assert options["params"] == {"$limit": 4000, "$sort[time]": -1, "time[$gte]": "2026-11-15T14:45:00.000Z"}
        assert "headers" not in options            # aucun jeton : le service se lit sans

    def test_une_reponse_a_la_forme_inattendue_fait_echouer_le_releve_proprement(self):
        """Ce service n'est pas une API publiée : il peut changer sans prévenir."""
        with mock.patch("core.radioactivite.requests.get") as appel:
            appel.return_value.json.return_value = {"data": []}
            with pytest.raises(ValueError):
                radioactivite.telecharger(MAINTENANT)

    @pytest.mark.django_db
    def test_un_releve_presque_vide_ne_remplace_pas_la_copie(self):
        with pytest.raises(ValueError):
            radioactivite.enregistrer(radioactivite.analyser(_reponse(_mesure(1039, "2026-11-15T15:50:00.000Z"))))

        assert MesureRadioactivite.objects.count() == 0

    @pytest.mark.django_db
    def test_une_balise_muette_depuis_une_semaine_est_retiree(self, monkeypatch):
        monkeypatch.setattr(radioactivite, "MINIMUM_PLAUSIBLE", 1)
        MesureRadioactivite.objects.create(
            station=7, nom="MUETTE", location=Point(2.0, 48.0, srid=4326), debit_nsv_h=80,
            mesure_le=MAINTENANT - datetime.timedelta(days=8), releve_le=MAINTENANT)

        radioactivite.enregistrer(radioactivite.analyser(_reponse(_mesure(1039, "2026-11-15T15:50:00.000Z"))), MAINTENANT)

        assert set(MesureRadioactivite.objects.values_list("station", flat=True)) == {1039}

    @pytest.mark.django_db
    def test_la_lecture_donne_l_ecart_au_bruit_de_fond_de_la_plus_proche_a_la_plus_lointaine(self, api_client):
        def balise(station, nom, lon, lat, debit, fond):
            MesureRadioactivite.objects.create(
                station=station, nom=nom, location=Point(lon, lat, srid=4326), debit_nsv_h=debit,
                bruit_de_fond_nsv_h=fond, mesure_le=timezone.now(), releve_le=timezone.now())
        balise(1, "FIRMINY", 4.29, 45.39, 120, 100)
        balise(2, "ST-ETIENNE", 4.387, 45.443, 99, 105.2)
        balise(3, "SANS-FOND", 4.40, 45.45, 90, None)
        balise(4, "PARIS", 2.35, 48.85, 80, 80)

        corps = api_client.get(reverse("radioactivite"), {"lat": "45.44", "lon": "4.39", "rayon_km": "30"}).json()

        assert [b["nom"] for b in corps["resultats"]] == ["ST-ETIENNE", "SANS-FOND", "FIRMINY"]
        assert corps["resultats"][0]["ecart_nsv_h"] == -6.2 and corps["resultats"][2]["ecart_nsv_h"] == 20.0
        assert corps["resultats"][1]["ecart_nsv_h"] is None          # pas de bruit de fond connu : pas d'écart inventé
        assert "Téléray" in corps["source"]


# ── Séismes ─────────────────────────────────────────────────────────────────────────────────

ENTETE = "# EventID | Time | Latitude | Longitude | Depth/km | Author | Catalog | Contributor | ContributorID | MagnitudeType | Magnitude | MagnitudeAuthor | EventLocationName | EventType"


def _evenement(reference, instant, lat, lon, magnitude, lieu, zone, nature="earthquake", profondeur="5.2"):
    mot = "Earthquake" if nature == "earthquake" else "Event"
    return (f"{reference}|{instant}|{lat}|{lon}|{profondeur}|auto|Namazu|EOST|EOST|MLv|{magnitude}|auto|"
            f"{mot} of magnitude {magnitude}, near {lieu} ({zone})|{nature}")


class TestSeismes:

    def test_un_evenement_garde_son_lieu_sa_zone_et_sa_nature(self):
        (seisme,) = seismes.analyser("\n".join([ENTETE, _evenement(
            "fr2026vbavhl", "2026-11-13T08:39:02.147759Z", 45.5337, 4.1032, 2.449, "Montbrison", "France hexagonale")]))

        assert seisme["reference"] == "fr2026vbavhl" and seisme["magnitude"] == 2.4
        assert seisme["lieu"] == "Montbrison" and seisme["zone"] == "France hexagonale"
        assert seisme["nature"] == "earthquake" and seisme["profondeur_km"] == 5.2
        assert (seisme["location"].x, seisme["location"].y) == (4.1032, 45.5337)

    def test_les_tirs_de_carriere_sont_gardes_avec_leur_nature(self):
        """Un événement sur cinq : les masquer ferait croire à une carte plus calme, les mêler
        aux séismes à une sismicité qu'il n'y a pas."""
        (tir,) = seismes.analyser(_evenement("t1", "2026-11-13T08:39:02Z", 45.5, 4.1, 1.6, "Montbrison",
                                             "France hexagonale", nature="quarry blast"))

        assert tir["nature"] == "quarry blast" and seismes.NATURES[tir["nature"]] == "Tir de carrière"

    def test_les_grands_seismes_lointains_ne_sont_pas_copies(self):
        evenements = seismes.analyser("\n".join([
            _evenement("monde", "2026-11-15T15:41:15Z", 1.74, 122.17, 5.1, "Zamboanga", "Monde"),
            _evenement("reunion", "2026-11-15T10:00:00Z", -21.24, 55.71, 1.2, "Sainte-Rose", "La Réunion"),
        ]))

        assert [e["reference"] for e in evenements] == ["reunion"]

    @pytest.mark.parametrize("ligne", ["", "trop|court", "x|pas une date|45|4|5|a|b|c|d|ML|2.0|a|near X (France hexagonale)|earthquake",
                                       "x|2026-11-15T10:00:00Z|45|4|5|a|b|c|d|ML||a|near X (France hexagonale)|earthquake"])
    def test_une_ligne_mal_formee_est_ignoree(self, ligne):
        assert seismes.analyser(ligne) == []

    @pytest.mark.django_db
    def test_le_releve_remplace_la_copie_des_trente_jours(self, monkeypatch):
        monkeypatch.setattr(seismes, "MINIMUM_PLAUSIBLE", 1)
        seismes.enregistrer(seismes.analyser("\n".join([
            _evenement("a", "2026-10-20T10:00:00Z", 45.5, 4.1, 2.0, "Montbrison", "France hexagonale"),
            _evenement("b", "2026-11-13T10:00:00Z", 45.5, 4.1, 2.5, "Montbrison", "France hexagonale")])))

        seismes.enregistrer(seismes.analyser(_evenement(
            "b", "2026-11-13T10:00:00Z", 45.5, 4.1, 2.7, "Montbrison", "France hexagonale")))

        assert dict(Seisme.objects.values_list("reference", "magnitude")) == {"b": 2.7}    # magnitude révisée

    @pytest.mark.django_db
    def test_un_catalogue_presque_vide_ne_remplace_pas_la_copie(self):
        with pytest.raises(ValueError):
            seismes.enregistrer([])
        assert sources_ouvertes.SOURCES["SEISMES"].relever is seismes.relever

    def _seisme(self, reference, lon, lat, magnitude, jours=1, nature="earthquake"):
        Seisme.objects.create(reference=reference, date=timezone.now() - datetime.timedelta(days=jours),
                              location=Point(lon, lat, srid=4326), magnitude=magnitude, lieu="Lieu",
                              zone="France hexagonale", nature=nature, releve_le=timezone.now())

    @pytest.mark.django_db
    def test_la_lecture_filtre_par_emprise_magnitude_et_periode(self, api_client):
        self._seisme("recent", 4.40, 45.45, 2.4, jours=1)
        self._seisme("petit", 4.41, 45.45, 0.8, jours=2)
        self._seisme("ancien", 4.42, 45.45, 3.1, jours=20)
        self._seisme("tir", 4.43, 45.45, 1.9, jours=3, nature="quarry blast")
        self._seisme("loin", 2.35, 48.85, 4.0, jours=1)

        parametres = {"lat": "45.44", "lon": "4.39", "rayon_km": "30"}
        tous = api_client.get(reverse("seismes"), parametres).json()
        forts = api_client.get(reverse("seismes"), {**parametres, "magnitude_min": "1.5"}).json()
        semaine = api_client.get(reverse("seismes"), {**parametres, "jours": "7"}).json()

        assert [s["reference"] for s in tous["resultats"]] == ["recent", "petit", "tir", "ancien"]   # du plus récent
        assert {s["reference"] for s in forts["resultats"]} == {"recent", "tir", "ancien"}
        assert {s["reference"] for s in semaine["resultats"]} == {"recent", "petit", "tir"}
        assert tous["resultats"][2]["nature_libelle"] == "Tir de carrière"
        assert "Rénass" in tous["source"]

    @pytest.mark.django_db
    def test_la_sismicite_d_un_volcan_compare_cette_semaine_a_la_precedente(self, api_client):
        # Sous le Piton de la Fournaise : trois séismes cette semaine, un la semaine d'avant.
        self._seisme("f1", 55.71, -21.24, 1.2, jours=1)
        self._seisme("f2", 55.70, -21.25, 2.3, jours=3)
        self._seisme("f3", 55.72, -21.23, 0.9, jours=6)
        self._seisme("f4", 55.71, -21.24, 1.0, jours=10)
        self._seisme("vieux", 55.71, -21.24, 3.0, jours=20)                 # hors des quinze jours
        self._seisme("loin", 55.30, -20.90, 2.9, jours=1)                   # à 55 km : pas sous le volcan
        self._seisme("tir", 55.71, -21.24, 1.5, jours=1, nature="quarry blast")   # pas un séisme

        fournaise = next(v for v in seismes.activite_volcans() if v["code"] == "FOURNAISE")
        reunion = api_client.get(reverse("volcans"), {"lat": "-21.11", "lon": "55.53"}).json()
        metropole = api_client.get(reverse("volcans"), {"lat": "45.44", "lon": "4.39"}).json()

        assert (fournaise["seismes_7_jours"], fournaise["seismes_7_jours_precedents"]) == (3, 1)
        assert fournaise["magnitude_max"] == 2.3
        a_portee = [v["nom"] for v in reunion["volcans"] if v["a_portee"]]
        assert a_portee == ["Piton de la Fournaise"]
        # En métropole, aucun volcan n'est à portée : le bloc ne s'affichera pas.
        assert not any(v["a_portee"] for v in metropole["volcans"])
        assert len(metropole["volcans"]) == 4 and metropole["rayon_km"] == 15


# ── Carte nationale des défibrillateurs ─────────────────────────────────────────────────────

ENTETE_DAE = ("gid;c_gid;c_etat_valid;c_nom;c_lat_coor1;c_long_coor1;c_adr_num;c_adr_voie;c_com_cp;"
              "c_com_insee;c_com_nom;c_acc;c_acc_lib;c_acc_etg;c_acc_complt;c_disp_complt;"
              "c_etat_fonct;c_dermnt;c_maj_don;c_expt_rais;c_etat;c_doublon;c_dispo_horaires")


def _dae(gid, lat="45.44", lon="4.39", etat="Actif", fonction="En fonctionnement", libre="t"):
    return (f"{gid};{gid};validées;DAE G5;{lat};{lon};1;place de l'Hôtel de Ville;42000;42218;"
            f"Saint-Étienne;Extérieur;{libre};0;Sous le porche;;{fonction};2026-03-01;2026-06-01;"
            f"COMMUNE DE SAINT-ETIENNE;{etat};f;24/7")


def _lire_dae(*lignes):
    return defibrillateurs.lire(io.StringIO("\n".join((ENTETE_DAE,) + lignes)))


class TestCarteDesDefibrillateurs:

    def test_un_appareil_en_service_garde_ce_qui_sert_a_le_trouver(self):
        (appareil,) = _lire_dae(_dae(101))

        assert appareil["reference"] == "101" and appareil["commune_code"] == "42218"
        assert appareil["adresse"] == "1 place de l'Hôtel de Ville, 42000 Saint-Étienne"
        assert appareil["acces"] == "Extérieur" and appareil["acces_libre"] is True
        assert appareil["emplacement"] == "Sous le porche" and appareil["disponibilite"] == "24/7"
        assert (appareil["location"].x, appareil["location"].y) == (4.39, 45.44)

    def test_les_appareils_retires_ou_sans_position_ne_vont_pas_sur_la_carte(self):
        appareils = _lire_dae(_dae(1), _dae(2, etat="Supprimé définitivement"), _dae(3, fonction="Hors service"),
                              _dae(4, lat="", lon=""), _dae(5, lat="145", lon="4"))

        assert [a["reference"] for a in appareils] == ["1"]

    @pytest.mark.django_db
    def test_un_fichier_tronque_ne_remplace_pas_la_copie(self):
        with pytest.raises(ValueError):
            defibrillateurs.enregistrer(_lire_dae(_dae(1)))

        assert Defibrillateur.objects.count() == 0

    @pytest.mark.django_db
    def test_un_appareil_retire_du_fichier_quitte_la_carte(self, monkeypatch):
        monkeypatch.setattr(defibrillateurs, "MINIMUM_PLAUSIBLE", 1)
        defibrillateurs.enregistrer(_lire_dae(_dae(1), _dae(2), _dae(3)), MAINTENANT)

        defibrillateurs.enregistrer(_lire_dae(_dae(1), _dae(3)), MAINTENANT + datetime.timedelta(days=1))

        assert set(Defibrillateur.objects.values_list("reference", flat=True)) == {"1", "3"}

    @pytest.mark.django_db
    def test_la_lecture_rend_les_plus_proches_d_abord_et_le_vrai_total(self, api_client, monkeypatch):
        from core import views_veille

        monkeypatch.setattr(defibrillateurs, "MINIMUM_PLAUSIBLE", 1)
        monkeypatch.setattr(views_veille, "RESULTATS_MAX", 2)
        defibrillateurs.enregistrer(_lire_dae(
            _dae(1, lat="45.4500", lon="4.3900"), _dae(2, lat="45.4401", lon="4.3901"),
            _dae(3, lat="45.4450", lon="4.3900"), _dae(4, lat="48.85", lon="2.35")))

        corps = api_client.get(reverse("defibrillateurs"), {"lat": "45.44", "lon": "4.39", "rayon_km": "5"}).json()

        assert corps["total"] == 3 and corps["tronque"] is True and len(corps["resultats"]) == 2
        assert corps["resultats"][0]["distance_km"] <= corps["resultats"][1]["distance_km"]
        assert "Géo'DAE" in corps["source"]

    @pytest.mark.django_db
    def test_les_trois_sources_sont_au_releve_planifie(self):
        for code in ("RADIOACTIVITE", "SEISMES", "DEFIBRILLATEURS"):
            assert code in sources_ouvertes.SOURCES
        assert not ReleveSourceOuverte.objects.exists()
