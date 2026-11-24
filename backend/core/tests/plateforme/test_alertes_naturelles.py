"""Alertes automatiques réglables : une collectivité règle ses phénomènes, le moteur prévient une
fois par événement (application toujours, courriel selon la case, radio si exceptionnel), et
l'alerte mène à une crise ou à une demande de disponibilités, sans rien envoyer d'office."""
import datetime
from unittest import mock

import pytest
from django.contrib.gis.geos import Point
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from core import alertes_naturelles, notifications_application
from core.models import (
    AlerteNaturelle, CampagneDisponibilite, CanalMeshCore, Commune, ContactInstitution, Institution, InstitutionType,
    MessageCanalMeshCore, NotificationApplication, RegleAlerte, ReleveSourceOuverte, StationHydrometrique,
)

URL = "/api/alertes-automatiques/"
MIDI = timezone.make_aware(datetime.datetime(2026, 11, 24, 12, 0))
MINUIT = timezone.make_aware(datetime.datetime(2026, 11, 24, 23, 30))


def _seisme(identifiant, magnitude, lat=45.50, lon=4.40):
    return {"event_id": identifiant, "magnitude": magnitude, "latitude": lat, "longitude": lon, "lieu": "France"}


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    Commune.objects.update_or_create(code="42218", defaults={"nom": "Saint-Étienne", "centre_latitude": 45.43,
                                                              "centre_longitude": 4.39, "departement_code": "42"})
    return Institution.objects.create(nom="Mairie des alertes", type=itype, commune_code="42218", email="mairie@test.fr")


@pytest.fixture
def agent(create_user, mairie):
    personne = create_user(username="agent-alertes@test.fr", email="agent-alertes@test.fr", type="AUT_LOCALE")
    personne.institution = mairie
    personne.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=personne, actif=True, contact_principal=True)
    notifications_application.enregistrer_appareil(personne, "installation-alertes")
    return personne


@pytest.fixture
def client_agent(agent):
    client = APIClient()
    client.force_authenticate(user=agent)
    return client


def _regle(mairie, phenomene="SEISME", **champs):
    return RegleAlerte.objects.create(institution=mairie, phenomene=phenomene, actif=True, **champs)


def _evaluer(seismes, maintenant=MIDI, phenomenes=("SEISME",)):
    return alertes_naturelles.evaluer(phenomenes, maintenant=maintenant, contexte={"seismes": seismes})


@pytest.mark.django_db
class TestLeMoteur:
    def test_au_dessus_du_seuil_une_alerte_une_seule_fois(self, mairie, agent):
        _regle(mairie)
        (alerte,) = _evaluer([_seisme("a", 3.8)])
        assert alerte.niveau == "ALERTE" and alerte.institution == mairie
        assert NotificationApplication.objects.get(utilisateur=agent).titre.startswith("Séisme de magnitude 3.8")
        assert _evaluer([_seisme("a", 3.8)]) == []                     # déjà dit
        assert _evaluer([_seisme("b", 3.0)]) == []                     # sous le seuil

    def test_hors_du_rayon_rien(self, mairie, agent):
        _regle(mairie, seuils={"rayon_km": 20})
        assert _evaluer([_seisme("loin", 5.0, lat=46.5, lon=4.4)]) == []

    def test_le_courriel_selon_la_case_et_la_radio_directe_seulement_si_exceptionnel(self, mairie, agent):
        from core.models import CompagnonMeshCore, MessageMeshLog, NoeudMeshUtilisateur

        canal = CanalMeshCore.objects.create(nom="Fr_EMCOM", institution=mairie, actif=True, cle_partagee_hex="00" * 16)
        radio = CompagnonMeshCore.objects.create(nom="Radio mairie", connexion_type="TCP", institution=mairie, actif=True)
        NoeudMeshUtilisateur.objects.create(utilisateur=agent, pubkey_hex="ab" * 32)
        _regle(mairie)
        _evaluer([_seisme("modere", 3.9, lat=46.0)])
        assert len(mail.outbox) == 1 and not MessageMeshLog.objects.exists()

        (fort,) = _evaluer([_seisme("fort", 5.1)])
        assert fort.niveau == "EXCEPTIONNEL" and fort.bilan["radio"] == 1
        direct = MessageMeshLog.objects.get()
        assert direct.compagnon == radio and direct.contact_pubkey_hex == "ab" * 32 and direct.direction == "SORTANT"
        assert direct.contenu.startswith("ALERTE Seisme") and direct.contenu.isascii()
        # Jamais sur un canal partagé.
        assert not MessageCanalMeshCore.objects.filter(canal=canal).exists()
        assert NotificationApplication.objects.filter(utilisateur=agent, urgent=True).count() == 1

        RegleAlerte.objects.filter(institution=mairie).update(email=False, radio_si_exceptionnel=False)
        mail.outbox.clear()
        _evaluer([_seisme("encore", 5.3)])
        assert mail.outbox == [] and MessageMeshLog.objects.count() == 1

    def test_un_evenement_qui_devient_exceptionnel_est_redit(self, mairie, agent):
        _regle(mairie)
        _evaluer([_seisme("x", 3.6, lat=46.0)])
        (redit,) = _evaluer([_seisme("x", 4.9, lat=46.0)])
        assert redit.niveau == "EXCEPTIONNEL"

    def test_la_nuit_seul_l_exceptionnel_reveille(self, mairie, agent):
        _regle(mairie)
        assert _evaluer([_seisme("nuit", 3.8, lat=46.0)], maintenant=MINUIT) == []
        assert len(_evaluer([_seisme("nuit-fort", 5.0)], maintenant=MINUIT)) == 1
        RegleAlerte.objects.filter(institution=mairie).update(silence_nuit=False)
        assert len(_evaluer([_seisme("nuit", 3.8, lat=46.0)], maintenant=MINUIT)) == 1

    def test_une_source_perimee_n_alerte_pas(self, mairie, agent):
        _regle(mairie, phenomene="MONTEE_EAU")
        StationHydrometrique.objects.create(code="V1", nom="Saint-Étienne", cours_eau="Furan",
                                            location=Point(4.40, 45.44, srid=4326), referentiel_le=MIDI,
                                            hauteur_m=1.8, hauteur_le=MIDI, variation_3h_cm=65)
        ReleveSourceOuverte.objects.update_or_create(pk="HAUTEURS_EAU", defaults={"dernier_succes": MIDI - datetime.timedelta(days=2)})
        assert alertes_naturelles.evaluer(["MONTEE_EAU"], maintenant=MIDI) == []

        ReleveSourceOuverte.objects.filter(pk="HAUTEURS_EAU").update(dernier_succes=MIDI)
        (alerte,) = alertes_naturelles.evaluer(["MONTEE_EAU"], maintenant=MIDI)
        assert "Furan" in alerte.titre and alerte.niveau == "ALERTE"

    def test_un_detecteur_en_panne_ne_bloque_pas_les_autres(self, mairie, agent):
        _regle(mairie)
        _regle(mairie, phenomene="MONTEE_EAU")
        ReleveSourceOuverte.objects.update_or_create(pk="HAUTEURS_EAU", defaults={"dernier_succes": MIDI})
        en_panne = alertes_naturelles.PAR_CODE["MONTEE_EAU"]._replace(detecter=mock.Mock(side_effect=RuntimeError("panne")))
        with mock.patch.dict(alertes_naturelles.PAR_CODE, {"MONTEE_EAU": en_panne}):
            assert len(_evaluer([_seisme("ok", 4.0)], phenomenes=("MONTEE_EAU", "SEISME"))) == 1
        en_panne.detecter.assert_called_once()

    def test_le_titre_et_le_detail_ne_sont_pas_stockes_en_clair(self, mairie, agent):
        from django.db import connection

        _regle(mairie)
        (alerte,) = _evaluer([_seisme("secret", 4.0)])
        with connection.cursor() as curseur:
            curseur.execute("SELECT titre FROM core_alertenaturelle WHERE id = %s", [alerte.id])
            assert "Séisme" not in curseur.fetchone()[0]

    def test_le_perimetre_d_un_departement(self, mairie):
        Commune.objects.update_or_create(code="42100", defaults={"nom": "Montbrison", "centre_latitude": 45.61,
                                                                  "centre_longitude": 4.07, "departement_code": "42"})
        mairie.secteur_niveau_effectif, mairie.departement_code = "departement", "42"
        perimetre = alertes_naturelles.perimetre_de(mairie)
        assert perimetre.niveau == "departement" and {"42218", "42100"} <= perimetre.codes


@pytest.mark.django_db
class TestLaMatrice:
    def test_le_catalogue_et_les_regles(self, client_agent, mairie):
        donnees = client_agent.get(URL, {"institution": str(mairie.id)}).data
        codes = [p["code"] for p in donnees["phenomenes"]]
        assert {"SEISME", "VIGILANCE_METEO", "CRUES", "FOYERS", "AVALANCHE", "RADIOACTIVITE"} <= set(codes)
        assert all(p["regle"] is None for p in donnees["phenomenes"])
        assert donnees["perimetre"]["niveau"] == "commune"
        # Sans collectivité précisée : la sienne.
        sans = client_agent.get(URL).data
        assert sans["institution"]["id"] == str(mairie.id) and sans["choix"] == [{"id": str(mairie.id), "nom": mairie.nom}]

    def test_regler_une_ligne_dans_les_bornes(self, client_agent, mairie):
        corps = {"institution": str(mairie.id), "phenomene": "RAFALES", "actif": True,
                 "seuils": {"alerte": 100, "exceptionnel": 140}, "email": False}
        reponse = client_agent.post(URL + "regle/", corps, format="json")
        assert reponse.status_code == 200, reponse.data
        assert reponse.data["seuils"]["alerte"] == 100 and reponse.data["email"] is False

        hors = client_agent.post(URL + "regle/", {**corps, "seuils": {"alerte": 10}}, format="json")
        assert hors.status_code == 400
        inverse = client_agent.post(URL + "regle/", {**corps, "seuils": {"alerte": 120, "exceptionnel": 80}}, format="json")
        assert inverse.status_code == 400

    def test_tout_activer_avec_les_valeurs_conseillees_puis_tout_couper(self, client_agent, mairie):
        donnees = client_agent.post(URL + "toutes/", {"institution": str(mairie.id), "actif": True}, format="json").data
        assert all(p["regle"]["actif"] for p in donnees["phenomenes"])
        assert RegleAlerte.objects.filter(institution=mairie, actif=True).count() == len(alertes_naturelles.CATALOGUE)
        client_agent.post(URL + "toutes/", {"institution": str(mairie.id), "actif": False}, format="json")
        assert not RegleAlerte.objects.filter(institution=mairie, actif=True).exists()

    def test_une_autre_collectivite_est_refusee(self, create_user, mairie):
        autre = create_user(username="autre-alertes@test.fr", email="autre-alertes@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=autre)
        assert client.get(URL, {"institution": str(mairie.id)}).status_code == 403
        assert client.post(URL + "toutes/", {"institution": str(mairie.id), "actif": True}, format="json").status_code == 403


@pytest.mark.django_db
class TestLesGestes:
    def _alerte(self, mairie):
        _regle(mairie)
        (alerte,) = _evaluer([_seisme("geste", 4.2)])
        return alerte

    def test_ouvrir_une_crise_preremplie_puis_relier(self, client_agent, mairie, agent):
        from core.models import Crisis

        alerte = self._alerte(mairie)
        prerempli = client_agent.get(f"{URL}{alerte.id}/crise/").data
        assert prerempli["type"] == "CATASTROPHE_NATURELLE" and prerempli["titre"].startswith("Séisme")
        assert prerempli["latitude"] == pytest.approx(45.5)
        crise = Crisis.objects.create(name=prerempli["titre"], type=prerempli["type"], location=Point(4.4, 45.5, srid=4326))
        relie = client_agent.post(f"{URL}{alerte.id}/crise/", {"crise": str(crise.id)}, format="json").data
        assert relie["crise"] == str(crise.id)

    def test_demander_les_disponibilites_prepare_un_brouillon_sans_rien_envoyer(self, client_agent, mairie, agent):
        alerte = self._alerte(mairie)
        mail.outbox.clear()
        reponse = client_agent.post(f"{URL}{alerte.id}/disponibilites/")
        assert reponse.status_code == 201, reponse.data
        campagne = CampagneDisponibilite.objects.get(pk=reponse.data["campagne"])
        assert campagne.statut == "BROUILLON" and campagne.motif == "CRISE_A_VENIR"
        assert campagne.echelon == "COMMUNE" and campagne.territoire_code == "42218"
        assert mail.outbox == []
        # Une seconde demande rend la même campagne.
        assert client_agent.post(f"{URL}{alerte.id}/disponibilites/").data["campagne"] == str(campagne.id)


@pytest.mark.django_db
class TestLesDetecteurs:
    """Chaque détecteur, sur base vide (aucun ne lève) puis sur des données de la forme réelle."""

    def _perimetre(self, mairie):
        return alertes_naturelles.perimetre_de(mairie)

    def test_aucun_detecteur_ne_leve_sur_une_base_vide(self, mairie):
        perimetre = self._perimetre(mairie)
        for phenomene in alertes_naturelles.CATALOGUE:
            regle = RegleAlerte(institution=mairie, phenomene=phenomene.code)
            assert phenomene.detecter(perimetre, regle, MIDI, {}) == [], phenomene.code

    def test_vigilance_meteo(self, mairie):
        from core import meteo_france
        from core.tests.plateforme.test_veille import MAINTENANT, ORANGE_VENT_42, _enregistrer

        _enregistrer(ORANGE_VENT_42)
        regle = RegleAlerte(institution=mairie, phenomene="VIGILANCE_METEO")
        (vent,) = [e for e in alertes_naturelles._vigilance_meteo(self._perimetre(mairie), regle, MAINTENANT, {})
                   if e.valeur == 3]
        assert vent.titre.startswith("Vigilance ORANGE") and "Loire" in vent.detail or "42" in vent.detail
        assert meteo_france.PHENOMENES[1] in vent.titre

    def test_orage_sur_la_commune_avec_grele(self, mairie):
        from core.models import CelluleOrage
        from django.contrib.gis.geos import Polygon

        contour = Polygon.from_bbox((4.3, 45.4, 4.5, 45.5))
        CelluleOrage.objects.create(
            identifiant="c1", heure_image=MIDI, centre=Point(4.4, 45.45, srid=4326), contour=contour, couloir=contour,
            ligne=0, colonne=0, max_mmh=42, moyenne_mmh=20, surface_km2=30, grele_prevue=True, releve_le=MIDI,
            communes_touchees=[{"code": "42218", "nom": "Saint-Étienne"}])
        (orage,) = alertes_naturelles._orages(self._perimetre(mairie), RegleAlerte(institution=mairie, phenomene="ORAGES"), MIDI, {})
        assert orage.valeur == 42 and orage.au_moins == "EXCEPTIONNEL" and "Saint-Étienne" in orage.titre

    def test_foyers_satellite_proches_et_sources_fixes_ignorees(self, mairie):
        from core.models import FoyerActif

        for n, (lat, fixe) in enumerate(((45.45, False), (45.46, False), (45.44, True))):
            FoyerActif.objects.create(reference=f"f{n}", date=MIDI - datetime.timedelta(hours=1), location=Point(4.41, lat, srid=4326),
                                      confiance="nominale", source_fixe=fixe, releve_le=MIDI)
        (feu,) = alertes_naturelles._foyers(self._perimetre(mairie), RegleAlerte(institution=mairie, phenomene="FOYERS"), MIDI, {})
        assert feu.valeur == 2

    def test_vigilance_crues_sur_un_troncon_qui_traverse(self, mairie):
        from core.models import TronconVigilanceCrues
        from django.contrib.gis.geos import LineString, MultiLineString

        TronconVigilanceCrues.objects.create(code="LO1", nom="Furan", niveau=3, publie_le=MIDI, releve_le=MIDI,
                                             geometrie=MultiLineString(LineString((4.3, 45.40), (4.5, 45.47), srid=4326)))
        (crue,) = alertes_naturelles._crues(self._perimetre(mairie), RegleAlerte(institution=mairie, phenomene="CRUES"), MIDI, {})
        assert crue.valeur == 3 and "orange" in crue.titre
