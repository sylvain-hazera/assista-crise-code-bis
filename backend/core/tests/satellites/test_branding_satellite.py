"""La charte de l'institution sur un satellite, figée à l'enrôlement.

Demande de Sylvain du 13/11/2026 : *« Si les casques jaunes déploient un satellite, aura-t-il
leur charte graphique ? »* — non, et pour trois raisons indépendantes :

1. le branding se résout par le **nom d'hôte HTTP** (`InstitutionWebDomaine`), or on arrive sur
   un satellite par son IP locale : aucun domaine ne correspond ;
2. la fiche `Institution` n'est pas dans le périmètre de synchronisation d'un satellite ;
3. le logo est un fichier média, qui ne descend pas non plus.

D'où le choix : la charte est **recopiée à l'enrôlement** et **figée** jusqu'à la prochaine
mise à jour, pour une **seule** institution — celle à qui le satellite appartient.

Ce que ces tests tiennent : le central sait la donner, le satellite sait la servir, et le
central ne se prend jamais pour un satellite.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.branding import DEFAULT_NOM_AFFICHAGE, branding_satellite
from core.models import Institution, InstitutionType


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "Association"})
    return Institution.objects.create(
        nom="Les Casques Jaunes", nom_affichage="Casques Jaunes",
        couleur_primaire="#f59e0b", couleur_secondaire="#b45309", type=itype)


class TestLeCentralDonneLaCharte:
    def test_l_enrolement_renvoie_la_charte(self, institution):
        """L'enrôlement est le seul moment où le satellite apprend à qui il appartient :
        c'est donc là qu'on la lui donne."""
        from core.models import JetonEnrolementSatellite
        from django.utils import timezone
        import datetime

        jeton = JetonEnrolementSatellite.objects.create(
            institution=institution, profil="FULL", environment="PROD",
            jeton="jeton-test-charte",
            expiration=timezone.now() + datetime.timedelta(days=1))

        reponse = APIClient().post(
            reverse("satellite-enroler"),
            {"jeton": str(jeton.jeton), "nom": "satellite-reunion"}, format="json")

        assert reponse.status_code == 201, reponse.data
        charte = reponse.data["branding"]
        assert charte["nom_affichage"] == "Casques Jaunes"
        assert charte["couleur_primaire"] == "#f59e0b"

    def test_un_logo_illisible_ne_casse_pas_l_enrolement(self, institution):
        """Un satellite qui ne s'enrôle pas est un satellite inutilisable : la charte est
        secondaire, elle ne doit jamais faire échouer l'opération."""
        from core.views import _branding_pour_satellite

        class RequeteFactice:
            def build_absolute_uri(self, url):
                raise ValueError("logo cassé")

        charte = _branding_pour_satellite(RequeteFactice(), institution)

        assert charte["logo_url"] is None
        assert charte["nom_affichage"] == "Casques Jaunes"


class TestLeSatelliteServLaCharte:
    def test_le_central_ne_se_prend_jamais_pour_un_satellite(self, db, settings):
        """INSTANCE_SATELLITE_LOCALE est faux ici : la résolution par domaine reste la seule
        source, et un central mal configuré ne doit pas afficher une charte d'emprunt."""
        settings.INSTANCE_SATELLITE_LOCALE = False
        settings.SATELLITE_BRANDING_NOM = "Casques Jaunes"

        assert branding_satellite() is None

    def test_le_satellite_sert_la_charte_de_son_institution(self, db, settings):
        settings.INSTANCE_SATELLITE_LOCALE = True
        settings.SATELLITE_BRANDING_NOM = "Casques Jaunes"
        settings.SATELLITE_BRANDING_COULEUR_PRIMAIRE = "#f59e0b"
        settings.SATELLITE_BRANDING_LOGO = "/media/branding-satellite/logo.png"

        charte = branding_satellite()

        assert charte.nom_affichage == "Casques Jaunes"
        assert charte.couleur_primaire == "#f59e0b"
        assert charte.logo_url == "/media/branding-satellite/logo.png"

    def test_sans_charte_enregistree_on_ne_l_invente_pas(self, db, settings):
        """Satellite enrôlé avant cette fonctionnalité, ou institution sans charte : on
        retombe sur Assista-Crise plutôt que de fabriquer une identité à partir de rien."""
        settings.INSTANCE_SATELLITE_LOCALE = True
        settings.SATELLITE_BRANDING_NOM = ""

        assert branding_satellite() is None

    def test_l_api_branding_rend_la_charte_du_satellite(self, db, settings):
        """Le test qui compte pour l'utilisateur : ce que l'application affiche vraiment."""
        settings.INSTANCE_SATELLITE_LOCALE = True
        settings.SATELLITE_BRANDING_NOM = "Casques Jaunes"
        settings.SATELLITE_BRANDING_COULEUR_PRIMAIRE = "#f59e0b"

        reponse = APIClient().get(reverse("branding"))

        assert reponse.data["nom_affichage"] == "Casques Jaunes"
        assert reponse.data["couleur_primaire"] == "#f59e0b"

    def test_sur_le_central_l_api_rend_le_defaut(self, db, settings):
        settings.INSTANCE_SATELLITE_LOCALE = False

        reponse = APIClient().get(reverse("branding"))

        assert reponse.data["nom_affichage"] == DEFAULT_NOM_AFFICHAGE
