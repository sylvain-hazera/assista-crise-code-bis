"""Veille du territoire, troisième lot (15/11/2026) : radioactivité ambiante (Téléray),
séismes et sismicité des volcans (BCSF-Rénass), carte nationale des défibrillateurs (Géo'DAE).

Aucun test n'appelle l'extérieur : les réponses sont des extraits réels réduits."""
import datetime
import io
from unittest import mock

import pytest
import requests
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


# ── Foyers d'incendie actifs ────────────────────────────────────────────────────────────────

from core import foyers_actifs  # noqa: E402
from core.models import (  # noqa: E402
    CanalMeshCore, Commune, ConfigurationAlerteFeu, ContactInstitution, FoyerActif, FoyerSignale,
    Institution, InstitutionType, MessageCanalMeshCore,
)

ENTETE_VIIRS = "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,version,bright_ti5,frp,daynight"
ENTETE_MODIS = "latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,confidence,version,bright_t31,frp,daynight"


def _viirs(lat, lon, jour, heure="1230", confiance="nominal", frp="10.12"):
    return f"{lat},{lon},339.59,0.57,0.52,{jour},{heure},N20,{confiance},2.0NRT,278.43,{frp},D"


def _fichier_viirs(*lignes):
    return "\n".join((ENTETE_VIIRS,) + lignes)


class TestFoyersActifs:

    def test_une_detection_recente_devient_un_foyer(self):
        (foyer,) = foyers_actifs.analyser([_fichier_viirs(_viirs(45.50, 4.50, "2026-11-15", "1230"))], MAINTENANT)

        assert foyer["date"] == datetime.datetime(2026, 11, 15, 12, 30, tzinfo=UTC)
        assert (foyer["location"].x, foyer["location"].y) == (4.5, 45.5)
        assert foyer["confiance"] == "nominale" and foyer["puissance_mw"] == 10.1
        assert foyer["satellite"] == "N20" and foyer["source_fixe"] is False and foyer["de_jour"] is True

    def test_hors_emprise_trop_ancien_ou_peu_fiable_n_est_pas_garde(self):
        foyers = foyers_actifs.analyser([_fichier_viirs(
            _viirs(45.50, 4.50, "2026-11-15"),
            _viirs(38.00, 23.70, "2026-11-15"),                 # Grèce
            _viirs(45.60, 4.60, "2026-11-12"),                 # plus de deux jours
            _viirs(45.70, 4.70, "2026-11-15", confiance="low"),
        )], MAINTENANT)

        assert [round(f["location"].y, 2) for f in foyers] == [45.5]

    def test_la_reunion_est_gardee_maurice_non(self):
        # La Réunion arrive par le fichier « Afrique australe », qui contient aussi Maurice.
        assert any("Southern_Africa" in f for f in foyers_actifs.FICHIERS)
        foyers = foyers_actifs.analyser([_fichier_viirs(
            _viirs(-21.07, 55.45, "2026-11-15"),                # Maïdo
            _viirs(-20.30, 57.55, "2026-11-15"),                # Maurice
        )], MAINTENANT)

        assert [(round(f["location"].y, 2), round(f["location"].x, 2)) for f in foyers] == [(-21.07, 55.45)]

    def test_l_outre_mer_est_garde_les_pays_voisins_non(self):
        for region in ("Southern_Africa", "Central_America", "South_America", "Australia_NewZealand"):
            assert sum(region in f for f in foyers_actifs.FICHIERS) == 4, region
        foyers = foyers_actifs.analyser([_fichier_viirs(
            _viirs(4.90, -52.60, "2026-11-15"),                 # Guyane
            _viirs(4.90, -55.50, "2026-11-15"),                 # Suriname
            _viirs(14.65, -61.00, "2026-11-15"),                # Martinique
            _viirs(15.40, -61.35, "2026-11-15"),                # la Dominique
            _viirs(-12.80, 45.15, "2026-11-15"),                # Mayotte
            _viirs(-21.50, 165.50, "2026-11-15"),               # Nouvelle-Calédonie
        )], MAINTENANT)

        assert sorted(round(f["location"].x, 2) for f in foyers) == [-61.0, -52.6, 45.15, 165.5]

    def test_modis_donne_sa_confiance_en_pourcentage(self):
        modis = "\n".join([ENTETE_MODIS,
                           "45.5,4.5,300.46,1.17,1.07,2026-11-15,1014,A,85,6.1NRT,274.22,11.62,D",
                           "45.6,4.6,300.46,1.17,1.07,2026-11-15,1014,A,45,6.1NRT,274.22,11.62,D",
                           "45.7,4.7,300.46,1.17,1.07,2026-11-15,1014,A,12,6.1NRT,274.22,11.62,D"])

        foyers = foyers_actifs.analyser([modis], MAINTENANT)

        assert [f["confiance"] for f in foyers] == ["élevée", "nominale"]

    def test_un_point_chaud_qui_revient_quatre_jours_sur_sept_est_une_source_fixe(self):
        """Constaté le 15/11/2026 : sur 109 détections en 24 h, presque toutes étaient des
        hauts-fourneaux et des torchères. Un feu avance ou s'éteint ; une usine reste."""
        usine = [_viirs(51.031, 2.301, f"2026-11-{jour}") for jour in (10, 11, 13, 14, 15)]
        feu = [_viirs(44.201, 5.101, "2026-11-15"), _viirs(44.202, 5.102, "2026-11-15", "1330")]

        foyers = foyers_actifs.analyser([_fichier_viirs(*usine, *feu)], MAINTENANT)

        fixes = {round(f["location"].y, 1) for f in foyers if f["source_fixe"]}
        libres = {round(f["location"].y, 1) for f in foyers if not f["source_fixe"]}
        assert fixes == {51.0} and libres == {44.2}

    def test_un_grand_site_qui_deborde_d_une_maille_reste_une_source_fixe(self):
        """Une aciérie couvre plusieurs mailles de 2 km : chacune n'est vue que certains jours."""
        site = [_viirs(51.031, 2.301, "2026-11-10"), _viirs(51.031, 2.301, "2026-11-11"),
                _viirs(51.031, 2.325, "2026-11-13"), _viirs(51.031, 2.325, "2026-11-14"),
                _viirs(51.045, 2.310, "2026-11-15")]

        foyers = foyers_actifs.analyser([_fichier_viirs(*site)], MAINTENANT)

        assert foyers and all(f["source_fixe"] for f in foyers)

    def test_la_meme_detection_lue_deux_fois_n_est_comptee_qu_une(self):
        fichier = _fichier_viirs(_viirs(45.50, 4.50, "2026-11-15"))

        assert len(foyers_actifs.analyser([fichier, fichier], MAINTENANT)) == 1

    def test_un_capteur_en_panne_n_empeche_pas_les_autres(self):
        bon = mock.Mock(text=_fichier_viirs(_viirs(45.5, 4.5, "2026-11-15")), raise_for_status=lambda: None)

        with mock.patch("core.foyers_actifs.requests.get",
                        side_effect=[requests.ConnectionError("coupé"), bon, bon, requests.ReadTimeout("lent")]
                        * (len(foyers_actifs.FICHIERS) // 4)):
            # Quatre capteurs par région : deux sur quatre répondent dans chacune.
            assert len(foyers_actifs.telecharger()) == len(foyers_actifs.FICHIERS) // 2

        with mock.patch("core.foyers_actifs.requests.get", side_effect=requests.ConnectionError("coupé")):
            with pytest.raises(requests.ConnectionError):
                foyers_actifs.telecharger()

    @pytest.mark.django_db
    def test_quand_plus_rien_ne_brule_la_table_se_vide(self):
        foyers_actifs.enregistrer(foyers_actifs.analyser([_fichier_viirs(_viirs(45.5, 4.5, "2026-11-15"))], MAINTENANT))

        assert foyers_actifs.enregistrer([]) == 0 and FoyerActif.objects.count() == 0

    @pytest.mark.django_db
    def test_la_lecture_met_les_sources_fixes_a_part(self, api_client):
        def foyer(reference, lon, lat, fixe):
            FoyerActif.objects.create(reference=reference, date=timezone.now(), location=Point(lon, lat, srid=4326),
                                      source_fixe=fixe, releve_le=timezone.now())
        foyer("feu", 4.40, 45.45, False)
        foyer("usine", 4.41, 45.46, True)

        parametres = {"lat": "45.44", "lon": "4.39", "rayon_km": "10"}
        sans = api_client.get(reverse("foyers_actifs"), parametres).json()
        avec = api_client.get(reverse("foyers_actifs"), {**parametres, "fixes": "1"}).json()

        assert [f["reference"] for f in sans["resultats"]] == ["feu"] and sans["sources_fixes"] == 1
        assert {f["reference"]: f["source_fixe"] for f in avec["resultats"]} == {"feu": False, "usine": True}
        assert sans["source"] == "NASA FIRMS"


@pytest.fixture
def mairie_feu(db):
    Commune.objects.create(code="42218", nom="Saint-Étienne", departement_code="42", region_code="84",
                           epci_code="244200770", centre_latitude=45.44, centre_longitude=4.39)
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    institution = Institution.objects.create(
        nom="Mairie de Saint-Étienne (feux)", type=itype, commune_code="42218",
        commune_nom="Saint-Étienne", departement_code="42")
    ConfigurationAlerteFeu.objects.create(institution=institution, actif=True, rayon_km=15)
    return institution


def _foyer_en_base(reference, lat, lon, heures=1, fixe=False, confiance="nominale"):
    FoyerActif.objects.create(
        reference=reference, date=MAINTENANT - datetime.timedelta(hours=heures),
        location=Point(lon, lat, srid=4326), confiance=confiance, source_fixe=fixe, releve_le=MAINTENANT)


@pytest.mark.django_db
class TestAnnonceDesFoyers:

    @pytest.fixture(autouse=True)
    def sans_messagerie(self):
        with mock.patch("core.matrix.envoyer_dm") as envoi:
            self.envoi = envoi
            yield

    def test_deux_detections_proches_sont_annoncees_sur_la_radio_et_par_message(self, mairie_feu, create_user):
        agent = create_user(username="agent-feu@test.fr", email="agent-feu@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie_feu, utilisateur=agent, actif=True)
        canal = CanalMeshCore.objects.create(nom="Mairie", institution=mairie_feu, actif=True, cle_partagee_hex="00" * 16)
        _foyer_en_base("a", 45.512, 4.412)
        _foyer_en_base("b", 45.514, 4.415, heures=2)

        (annonce,) = foyers_actifs.diffuser_alertes(MAINTENANT)

        message = MessageCanalMeshCore.objects.get(canal=canal).contenu
        assert message.isascii()            # il part tel quel sur la radio
        assert "a ~8 km au nord de Saint-Etienne (2 detection(s), 16h00)" in message
        assert "A VERIFIER" in message and "NASA FIRMS" in message
        assert self.envoi.call_args_list[0].args[0] == agent and annonce.endswith(message)

    def test_le_meme_feu_n_est_pas_annonce_deux_fois(self, mairie_feu):
        _foyer_en_base("a", 45.512, 4.412)
        _foyer_en_base("b", 45.514, 4.415)
        foyers_actifs.diffuser_alertes(MAINTENANT)
        _foyer_en_base("c", 45.513, 4.413)

        assert foyers_actifs.diffuser_alertes(MAINTENANT + datetime.timedelta(hours=1)) == []

    def test_apres_trois_jours_un_nouveau_feu_au_meme_endroit_est_annonce(self, mairie_feu):
        _foyer_en_base("a", 45.512, 4.412)
        _foyer_en_base("b", 45.514, 4.415)
        foyers_actifs.diffuser_alertes(MAINTENANT)
        FoyerSignale.objects.update(date_signalement=MAINTENANT - datetime.timedelta(days=4))

        assert len(foyers_actifs.diffuser_alertes(MAINTENANT)) == 1

    def test_une_detection_isolee_ordinaire_ne_suffit_pas_une_de_confiance_elevee_si(self, mairie_feu):
        _foyer_en_base("seule", 45.512, 4.412)
        assert foyers_actifs.diffuser_alertes(MAINTENANT) == []

        _foyer_en_base("sure", 45.40, 4.30, confiance="élevée")
        assert len(foyers_actifs.diffuser_alertes(MAINTENANT)) == 1

    def test_une_source_fixe_n_est_jamais_annoncee(self, mairie_feu):
        _foyer_en_base("u1", 45.512, 4.412, fixe=True)
        _foyer_en_base("u2", 45.514, 4.415, fixe=True)

        assert foyers_actifs.diffuser_alertes(MAINTENANT) == []

    def test_hors_du_rayon_ou_trop_ancien_rien_n_est_annonce(self, mairie_feu):
        _foyer_en_base("loin1", 45.80, 4.40)
        _foyer_en_base("loin2", 45.80, 4.41)
        _foyer_en_base("vieux1", 45.512, 4.412, heures=20)
        _foyer_en_base("vieux2", 45.514, 4.415, heures=21)

        assert foyers_actifs.diffuser_alertes(MAINTENANT) == []

    def test_rien_ne_part_sans_abonnement_actif(self, mairie_feu):
        ConfigurationAlerteFeu.objects.update(actif=False)
        _foyer_en_base("a", 45.512, 4.412)
        _foyer_en_base("b", 45.514, 4.415)

        assert foyers_actifs.diffuser_alertes(MAINTENANT) == []
        self.envoi.assert_not_called()

    def test_seul_un_acteur_institutionnel_regle_l_annonce_et_le_rayon_est_borne(self, mairie_feu, create_user):
        from rest_framework.test import APIClient

        ConfigurationAlerteFeu.objects.all().delete()
        adresse = reverse("configurationalertefeu-list")
        citoyen = create_user(username="citoyen-feu@test.fr", email="citoyen-feu@test.fr")
        client = APIClient()
        client.force_authenticate(user=citoyen)
        assert client.post(adresse, {"institution": str(mairie_feu.id), "actif": True}, format="json").status_code == 403

        agent = create_user(username="agent-feu2@test.fr", email="agent-feu2@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie_feu, utilisateur=agent, actif=True)
        client.force_authenticate(user=agent)
        assert client.post(adresse, {"institution": str(mairie_feu.id), "actif": True, "rayon_km": 500}, format="json").status_code == 400
        reponse = client.post(adresse, {"institution": str(mairie_feu.id), "actif": True, "rayon_km": 20}, format="json")
        assert reponse.status_code == 201 and reponse.json()["rayon_km"] == 20
