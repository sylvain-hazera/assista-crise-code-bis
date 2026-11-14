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
    MeshCoreConnexionType, NoeudMeshUtilisateur, SessionRelaisNavigateur, UserRole,
)
from core.relais_navigateur import (
    SECONDES_AVANT_SESSION_MORTE, compagnon_pour_noeud, fermer_sessions_mortes, ouvrir,
    peut_relayer, radios_relayables, session_active,
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


@pytest.fixture
def administrateur(create_user):
    return create_user(username="admin-relais@test.fr", email="admin-relais@test.fr",
                       type=UserRole.ADMINISTRATOR)


@pytest.fixture
def porteur_de_noeud(create_user):
    """Le cas CENTRAL du relais : quelqu'un qui a déclaré SA radio, et rien d'autre.

    Pas de companion institutionnel, pas de satellite — c'est précisément la personne que la
    première version excluait, alors qu'elle est la seule visée par le besoin."""
    user = create_user(username="porteur-relais@test.fr", email="porteur-relais@test.fr",
                       type=UserRole.SIMPLE_USER)
    NoeudMeshUtilisateur.objects.create(
        utilisateur=user, pubkey_hex="aa" * 32, nom_noeud="T-Deck de Sylvain",
        environment="PROD")
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

    def test_un_administrateur_peut(self, administrateur, compagnon):
        """Régression du 14/11/2026. La règle l'acceptait déjà, mais la liste servie à l'écran
        pré-filtrait sur l'appartenance : un administrateur lisait « aucune radio accessible ».
        Le droit et la liste doivent se décider au même endroit."""
        assert peut_relayer(administrateur, compagnon) is True

        compagnons, _ = radios_relayables(administrateur)
        assert compagnon in compagnons

    def test_un_role_prete_en_demonstration_ne_donne_pas_la_main(self, membre, compagnon,
                                                                 mairie):
        """Même raisonnement que EstComptePont : un rôle effectif ne vaut pas un rôle réel."""
        ContactInstitution.objects.filter(utilisateur=membre, institution=mairie).update(
            actif=False)
        membre.demo_role = UserRole.ADMINISTRATOR
        membre.save(update_fields=["demo_role"])

        assert peut_relayer(membre, compagnon) is False

    def test_le_proprietaire_de_la_radio_peut_la_relayer(self, porteur_de_noeud):
        """Sans appartenance, sans companion déclaré : la clé publique suffit à le reconnaître."""
        compagnon = CompagnonMeshCore.objects.create(
            nom="T-Deck", environment="PROD", connexion_type=MeshCoreConnexionType.SERIE,
            pubkey_hex="aa" * 32)

        assert peut_relayer(porteur_de_noeud, compagnon) is True

    def test_la_radio_d_un_autre_reste_interdite(self, porteur_de_noeud, create_user):
        """Déclarer SA radio ne donne pas la main sur celle du voisin."""
        autre = CompagnonMeshCore.objects.create(
            nom="T-Deck du voisin", environment="PROD",
            connexion_type=MeshCoreConnexionType.SERIE, pubkey_hex="bb" * 32)

        assert peut_relayer(porteur_de_noeud, autre) is False


class TestLeNoeudPersonnelDevientPasserelle:
    """La correction de cadrage du 14/11/2026.

    La première version exigeait un companion institutionnel **déjà déclaré**. Le besoin est
    l'inverse : « quelqu'un sans satellite branche son nœud en USB ». On lui demandait donc
    d'avoir déjà ce que le relais est censé fournir."""

    def test_son_noeud_apparait_sans_rien_avoir_declare(self, porteur_de_noeud):
        compagnons, noeuds = radios_relayables(porteur_de_noeud)

        assert compagnons == []
        assert len(noeuds) == 1
        assert noeuds[0].pubkey_hex == "aa" * 32

    def test_le_demarrage_le_promeut_en_companion(self, porteur_de_noeud):
        noeud = NoeudMeshUtilisateur.objects.get(utilisateur=porteur_de_noeud)

        compagnon, erreur = compagnon_pour_noeud(porteur_de_noeud, noeud, "PROD")

        assert erreur is None
        assert compagnon.pubkey_hex == "aa" * 32
        assert compagnon.connexion_type == MeshCoreConnexionType.SERIE
        # La radio est sur le poste de la personne, pas sur le serveur : aucun pont Python ne
        # doit essayer d'ouvrir ce périphérique.
        assert compagnon.serie_device == "navigateur"
        assert compagnon.nom == "T-Deck de Sylvain"

    def test_la_promotion_est_idempotente(self, porteur_de_noeud):
        """Rebrancher la radio demain ne doit pas créer un second companion."""
        noeud = NoeudMeshUtilisateur.objects.get(utilisateur=porteur_de_noeud)

        premier, _ = compagnon_pour_noeud(porteur_de_noeud, noeud, "PROD")
        second, _ = compagnon_pour_noeud(porteur_de_noeud, noeud, "PROD")

        assert premier.id == second.id
        assert CompagnonMeshCore.objects.filter(pubkey_hex="aa" * 32).count() == 1

    def test_une_fois_promu_il_n_apparait_qu_une_fois(self, porteur_de_noeud):
        """Sinon la même radio serait proposée deux fois dans la liste."""
        noeud = NoeudMeshUtilisateur.objects.get(utilisateur=porteur_de_noeud)
        compagnon_pour_noeud(porteur_de_noeud, noeud, "PROD")

        compagnons, noeuds = radios_relayables(porteur_de_noeud)

        assert len(compagnons) == 1
        assert noeuds == []

    def test_on_ne_promeut_pas_le_noeud_d_un_autre(self, porteur_de_noeud, membre):
        noeud = NoeudMeshUtilisateur.objects.get(utilisateur=porteur_de_noeud)

        compagnon, erreur = compagnon_pour_noeud(membre, noeud, "PROD")

        assert compagnon is None
        assert erreur

    def test_l_api_ouvre_le_relais_sur_un_noeud_personnel(self, porteur_de_noeud):
        """Le bout en bout : on branche, on démarre, le serveur rend le companion à utiliser."""
        noeud = NoeudMeshUtilisateur.objects.get(utilisateur=porteur_de_noeud)
        url = reverse("relais_serie")

        reponse = _client(porteur_de_noeud).post(url, {"noeud": str(noeud.id)}, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["compagnon"]
        assert SessionRelaisNavigateur.objects.filter(utilisateur=porteur_de_noeud).count() == 1

    def test_une_radio_sans_institution_le_dit(self, porteur_de_noeud):
        """« Passerelle DE L'INSTITUTION » suppose qu'on sache laquelle.

        Sans institution déterminable, le relais fonctionne quand même — le propriétaire est
        reconnu par la clé publique — mais aucun collègue ne pourra reprendre la radio. On le
        dit plutôt que de laisser croire au contraire."""
        noeud = NoeudMeshUtilisateur.objects.get(utilisateur=porteur_de_noeud)

        reponse = _client(porteur_de_noeud).post(
            reverse("relais_serie"), {"noeud": str(noeud.id)}, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        assert "institution" in reponse.data["avertissement"]

    def test_une_radio_rattachee_ne_previent_de_rien(self, membre, compagnon):
        reponse = _client(membre).post(
            reverse("relais_serie"), {"compagnon": str(compagnon.id)}, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        assert "avertissement" not in reponse.data

    def test_fermer_un_noeud_jamais_demarre_ne_cree_rien(self, porteur_de_noeud):
        """Fermer n'est pas une écriture : sinon un `ngOnDestroy` suffirait à créer la radio."""
        noeud = NoeudMeshUtilisateur.objects.get(utilisateur=porteur_de_noeud)
        url = reverse("relais_serie")

        reponse = _client(porteur_de_noeud).post(
            url, {"noeud": str(noeud.id), "fermer": True}, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        assert CompagnonMeshCore.objects.filter(pubkey_hex="aa" * 32).count() == 0


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
