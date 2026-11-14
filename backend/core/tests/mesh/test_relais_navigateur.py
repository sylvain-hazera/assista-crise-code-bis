"""Relais série par le navigateur, et la faille qu'il a obligé à fermer.

Demande de Sylvain du 13/11/2026 : une urgence sur un poste verrouillé où l'on ne peut rien
installer, mais dont l'USB fonctionne.

Ce qui est tenu ici tient en deux idées :

1. **Qui tient la radio a le droit d'agir pour elle, et personne d'autre.** Jusqu'au
   13/11/2026, `/messages-meshcore/a-envoyer/` sans paramètre rendait la file sortante de TOUS
   les companions de la plateforme à tout compte inscrit, et n'importe qui pouvait déposer un
   faux message entrant. Le relais a forcé à définir cette règle ; elle manquait déjà.
2. **Une page web n'annonce pas sa fermeture.** Onglet tué, portable en veille, Wi-Fi coupé :
   sans battement ni ménage, une radio resterait marquée relayée indéfiniment.
"""
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshCore, ContactInstitution, Institution, InstitutionType,
    MeshCoreConnexionType, SessionRelaisNavigateur, UserRole,
)
from core.relais_navigateur import (
    SECONDES_AVANT_SESSION_MORTE, fermer_sessions_mortes, ouvrir, peut_relayer, session_active,
)


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie du Relais", type=itype)


@pytest.fixture
def autre_mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie d'à côté", type=itype)


@pytest.fixture
def compagnon(mairie):
    return CompagnonMeshCore.objects.create(
        institution=mairie, nom="Nœud du PC d'accueil", environment="PROD",
        connexion_type=MeshCoreConnexionType.SERIE)


@pytest.fixture
def membre(create_user, mairie):
    user = create_user(username="membre-relais@test.fr", email="membre-relais@test.fr",
                       type=UserRole.LOCAL_AUTHORITY)
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    return user


@pytest.fixture
def etranger(create_user, autre_mairie):
    user = create_user(username="etranger-relais@test.fr", email="etranger-relais@test.fr",
                       type=UserRole.LOCAL_AUTHORITY)
    ContactInstitution.objects.create(institution=autre_mairie, utilisateur=user, actif=True)
    return user


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class TestQuiPeutRelayer:
    def test_un_membre_de_l_institution_peut(self, membre, compagnon):
        assert peut_relayer(membre, compagnon) is True

    def test_un_membre_d_une_autre_institution_ne_peut_pas(self, etranger, compagnon):
        """L'appartenance ET la possession physique : ni l'une ni l'autre ne suffit seule."""
        assert peut_relayer(etranger, compagnon) is False

    def test_un_rattachement_desactive_retire_le_droit(self, membre, compagnon, mairie):
        ContactInstitution.objects.filter(utilisateur=membre, institution=mairie).update(
            actif=False)

        assert peut_relayer(membre, compagnon) is False

    def test_une_radio_sans_institution_n_est_relayee_par_personne(self, membre, compagnon):
        """On ne devine pas à qui confier une radio qui n'appartient à personne."""
        compagnon.institution = None
        compagnon.save()

        assert peut_relayer(membre, compagnon) is False


class TestLaSession:
    def test_ouvrir_puis_rouvrir_ne_cree_qu_une_session(self, membre, compagnon):
        """Recharger la page ne doit ni consommer le plafond, ni laisser une session
        fantôme."""
        premiere, _ = ouvrir(membre, compagnon, "PROD")
        seconde, erreur = ouvrir(membre, compagnon, "PROD")

        assert erreur is None
        assert premiere.id == seconde.id
        assert SessionRelaisNavigateur.objects.filter(compagnon=compagnon).count() == 1

    def test_deux_postes_ne_relaient_pas_la_meme_radio(self, create_user, membre, compagnon,
                                                       mairie):
        """Deux relais dépileraient la même file et enverraient chaque message en double."""
        autre = create_user(username="autre-relais@test.fr", email="autre-relais@test.fr",
                            type=UserRole.LOCAL_AUTHORITY)
        ContactInstitution.objects.create(institution=mairie, utilisateur=autre, actif=True)
        ouvrir(membre, compagnon, "PROD")

        session, erreur = ouvrir(autre, compagnon, "PROD")

        assert session is None
        assert "déjà relayée" in erreur

    def test_une_session_silencieuse_libere_la_radio(self, create_user, membre, compagnon,
                                                     mairie):
        """Onglet tué, portable en veille : sans ménage, la radio resterait bloquée."""
        session, _ = ouvrir(membre, compagnon, "PROD")
        SessionRelaisNavigateur.objects.filter(pk=session.pk).update(
            dernier_contact=timezone.now()
            - timezone.timedelta(seconds=SECONDES_AVANT_SESSION_MORTE + 10))

        assert session_active(membre, compagnon.id) is None
        autre = create_user(username="apres@test.fr", email="apres@test.fr",
                            type=UserRole.LOCAL_AUTHORITY)
        ContactInstitution.objects.create(institution=mairie, utilisateur=autre, actif=True)
        reprise, erreur = ouvrir(autre, compagnon, "PROD")
        assert erreur is None and reprise is not None

    def test_le_menage_ferme_les_sessions_mortes(self, membre, compagnon):
        session, _ = ouvrir(membre, compagnon, "PROD")
        SessionRelaisNavigateur.objects.filter(pk=session.pk).update(
            dernier_contact=timezone.now() - timezone.timedelta(hours=2))

        assert fermer_sessions_mortes() == 1
        session.refresh_from_db()
        assert session.fermee_le is not None

    def test_le_droit_est_recalcule_a_chaque_appel(self, membre, compagnon, mairie):
        """La session ne PORTE pas le droit : un membre sorti perd la main immédiatement, sans
        attendre l'expiration."""
        ouvrir(membre, compagnon, "PROD")
        ContactInstitution.objects.filter(utilisateur=membre, institution=mairie).update(
            actif=False)

        reponse = _client(membre).post(reverse("relais_serie"),
                                       {"compagnon": str(compagnon.id)}, format="json")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN


class TestLApi:
    def test_la_page_liste_les_radios_relayables(self, membre, compagnon):
        reponse = _client(membre).get(reverse("relais_serie"))

        assert reponse.status_code == status.HTTP_200_OK
        assert [c["id"] for c in reponse.data["compagnons"]] == [str(compagnon.id)]
        assert reponse.data["session"] is None

    def test_elle_ne_liste_pas_les_radios_des_autres(self, etranger, compagnon):
        reponse = _client(etranger).get(reverse("relais_serie"))

        assert reponse.data["compagnons"] == []

    def test_ouvrir_puis_fermer(self, membre, compagnon):
        client = _client(membre)

        ouverture = client.post(reverse("relais_serie"),
                                {"compagnon": str(compagnon.id)}, format="json")
        assert ouverture.status_code == status.HTTP_200_OK
        assert ouverture.data["session"]

        fermeture = client.post(reverse("relais_serie"),
                                {"compagnon": str(compagnon.id), "fermer": True},
                                format="json")
        assert fermeture.data["session"] is None
        assert session_active(membre, compagnon.id) is None


class TestLaFailleFermee:
    """Jusqu'au 13/11/2026, ces trois tests auraient tous échoué."""

    def test_sans_relais_on_ne_lit_pas_la_file_d_une_radio(self, etranger, compagnon):
        reponse = _client(etranger).get(reverse("messagemeshlog-a-envoyer"),
                                        {"compagnon": str(compagnon.id)})

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_sans_compagnon_la_file_globale_n_est_plus_servie(self, membre, compagnon):
        """C'est la forme qui faisait fuiter la file sortante de TOUTE la plateforme."""
        ouvrir(membre, compagnon, "PROD")

        reponse = _client(membre).get(reverse("messagemeshlog-a-envoyer"))

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_on_ne_depose_pas_un_faux_message_entrant(self, etranger, compagnon):
        reponse = _client(etranger).post(reverse("messagemeshlog-list"), {
            "compagnon": str(compagnon.id), "direction": "ENTRANT",
            "contact_pubkey_hex": "ab" * 32, "contenu": "faux message",
        }, format="json")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_un_relais_vivant_lit_SA_file(self, membre, compagnon):
        ouvrir(membre, compagnon, "PROD")

        reponse = _client(membre).get(reverse("messagemeshlog-a-envoyer"),
                                      {"compagnon": str(compagnon.id)})

        assert reponse.status_code == status.HTTP_200_OK
