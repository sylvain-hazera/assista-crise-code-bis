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
    CanalMeshtastic, CompagnonMeshCore, CompagnonMeshtastic, ContactInstitution,
    DirectionMessageMesh,
    Institution, InstitutionType, MeshCoreConnexionType, MessageMeshLog, MessageMeshtasticLog,
    NoeudMeshUtilisateur, NoeudUtilisateurMeshtastic, SessionRelaisNavigateur,
    StatutMessageMesh, UserRole,
)
from core.relais_navigateur import (
    SECONDES_AVANT_SESSION_MORTE, RelaisRefuse, fermer_sessions_mortes, identifier, ouvrir,
    peut_relayer, radios_relayables, session_active, verifier_identite,
)

CLE_T_DECK = "aa" * 32
IDENTITE_T_DECK = {"pubkey_hex": CLE_T_DECK, "nom": "T-Deck de Sylvain"}


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

    def test_brancher_son_noeud_le_declare_comme_passerelle(self, porteur_de_noeud):
        """Le navigateur rapporte l'identité lue sur la radio ; le serveur reconnaît le nœud."""
        compagnon, cree = identifier(porteur_de_noeud, "MESHCORE", IDENTITE_T_DECK, "PROD")

        assert cree is True
        assert compagnon.pubkey_hex == CLE_T_DECK
        # Sur le poste de la personne, pas sur le serveur : aucun pont ne doit l'ouvrir.
        assert compagnon.connexion_type == MeshCoreConnexionType.NAVIGATEUR
        assert compagnon.nom == "T-Deck de Sylvain"

    def test_l_identification_est_idempotente(self, porteur_de_noeud):
        """Rebrancher la radio demain ne doit pas créer un second companion."""
        premier, _ = identifier(porteur_de_noeud, "MESHCORE", IDENTITE_T_DECK, "PROD")
        second, cree = identifier(porteur_de_noeud, "MESHCORE", IDENTITE_T_DECK, "PROD")

        assert premier.id == second.id
        assert cree is False
        assert CompagnonMeshCore.objects.filter(pubkey_hex=CLE_T_DECK).count() == 1

    def test_une_fois_promu_il_n_apparait_qu_une_fois(self, porteur_de_noeud):
        """Sinon la même radio serait proposée deux fois dans la liste."""
        identifier(porteur_de_noeud, "MESHCORE", IDENTITE_T_DECK, "PROD")

        compagnons, noeuds = radios_relayables(porteur_de_noeud)

        assert len(compagnons) == 1
        assert noeuds == []

    def test_on_ne_prend_pas_la_radio_d_un_autre(self, porteur_de_noeud, membre):
        """La radio du porteur, branchée chez quelqu'un d'autre, n'est pas à lui."""
        identifier(porteur_de_noeud, "MESHCORE", IDENTITE_T_DECK, "PROD")

        with pytest.raises(RelaisRefuse):
            identifier(membre, "MESHCORE", IDENTITE_T_DECK, "PROD")

    def test_un_benevole_ne_declare_pas_une_radio_inconnue(self, porteur_de_noeud):
        """Sinon n'importe quel compte inscrit enregistrerait des passerelles."""
        inconnue = {"pubkey_hex": "cc" * 32, "nom": "?"}

        with pytest.raises(RelaisRefuse, match="Déclarez-la"):
            identifier(porteur_de_noeud, "MESHCORE", inconnue, "PROD")

    def test_un_responsable_declare_une_radio_inconnue_pour_son_institution(self, membre,
                                                                             mairie):
        """« Un simple bouton connecter, et hop, ça me rajoute comme passerelle de l'institution »."""
        compagnon, cree = identifier(membre, "MESHCORE", {"pubkey_hex": "cc" * 32,
                                                          "nom": "Heltec mairie"}, "PROD")

        assert cree is True
        assert compagnon.institution == mairie
        assert compagnon.nom == "Heltec mairie"

    def test_une_identite_mal_formee_est_refusee(self, administrateur):
        with pytest.raises(RelaisRefuse):
            identifier(administrateur, "MESHCORE", {"pubkey_hex": "zz"}, "PROD")

    def test_la_mauvaise_radio_est_detectee(self, compagnon):
        """Choisir « radio A » puis brancher la radio B attribuerait le trafic de B à A."""
        compagnon.pubkey_hex = "dd" * 32
        compagnon.save()

        with pytest.raises(RelaisRefuse, match="n'est pas"):
            verifier_identite(compagnon, IDENTITE_T_DECK)

    def test_une_cle_inconnue_est_apprise_au_premier_branchement(self, compagnon):
        """Comme le pont Python à sa première connexion réussie."""
        verifier_identite(compagnon, IDENTITE_T_DECK)

        compagnon.refresh_from_db()
        assert compagnon.pubkey_hex == CLE_T_DECK

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
        assert reponse.data["sessions"] == []

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


class TestUnPontTientDejaLaRadio:
    def test_on_ne_relaie_pas_une_radio_qu_un_pont_tient(self, membre, compagnon):
        """Deux relais dépileraient la même file : chaque message partirait deux fois."""
        compagnon.dernier_etat = "CONNECTE"
        compagnon.derniere_connexion = timezone.now()
        compagnon.save()

        session, erreur = ouvrir(membre, compagnon, "PROD")

        assert session is None
        assert "pont" in erreur

    def test_un_pont_silencieux_ne_bloque_plus(self, membre, compagnon):
        compagnon.dernier_etat = "CONNECTE"
        compagnon.derniere_connexion = timezone.now() - timezone.timedelta(minutes=10)
        compagnon.save()

        session, erreur = ouvrir(membre, compagnon, "PROD")

        assert erreur is None


class TestMarquerUnEnvoi:
    """Régression du 14/11/2026, trouvée en relisant la permission.

    Un relais marque un envoi par `PATCH /messages-meshcore/<id>/ {statut}` — sans répéter son
    companion. La permission le refusait toujours : en situation, le navigateur aurait renvoyé
    le même message à chaque cycle, indéfiniment."""

    def test_un_relais_vivant_marque_SON_message_envoye(self, membre, compagnon):
        ouvrir(membre, compagnon, "PROD")
        message = MessageMeshLog.objects.create(
            compagnon=compagnon, direction=DirectionMessageMesh.SORTANT,
            contact_pubkey_hex="ee" * 32, contenu="Rentrez à la base", environment="PROD")

        reponse = _client(membre).patch(f"/api/messages-meshcore/{message.id}/",
                                        {"statut": "ENVOYE"}, format="json")

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        message.refresh_from_db()
        assert message.statut == StatutMessageMesh.ENVOYE

    def test_on_ne_marque_pas_le_message_d_une_autre_radio(self, membre, compagnon, mairie):
        ouvrir(membre, compagnon, "PROD")
        autre = CompagnonMeshCore.objects.create(
            institution=mairie, nom="Autre radio", environment="PROD",
            connexion_type=MeshCoreConnexionType.SERIE)
        message = MessageMeshLog.objects.create(
            compagnon=autre, direction=DirectionMessageMesh.SORTANT,
            contact_pubkey_hex="ee" * 32, contenu="x", environment="PROD")

        reponse = _client(membre).patch(f"/api/messages-meshcore/{message.id}/",
                                        {"statut": "ENVOYE"}, format="json")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN


# ══ Meshtastic ════════════════════════════════════════════════════════════════

@pytest.fixture
def radio_meshtastic(mairie):
    return CompagnonMeshtastic.objects.create(
        institution=mairie, nom="T-Beam de la mairie", environment="PROD",
        connexion_type=MeshCoreConnexionType.NAVIGATEUR, node_num=0x1234ABCD)


class TestMeshtastic:
    def test_brancher_son_noeud_meshtastic_le_declare(self, create_user):
        porteur = create_user(username="porteur-mt@test.fr", email="porteur-mt@test.fr",
                              type=UserRole.SIMPLE_USER)
        NoeudUtilisateurMeshtastic.objects.create(
            utilisateur=porteur, node_num=0x0BADCAFE, environment="PROD")

        compagnon, cree = identifier(porteur, "MESHTASTIC",
                                     {"node_num": 0x0BADCAFE, "nom": "Rak de Fred"}, "PROD")

        assert cree is True
        assert isinstance(compagnon, CompagnonMeshtastic)
        assert compagnon.node_num == 0x0BADCAFE
        assert compagnon.connexion_type == MeshCoreConnexionType.NAVIGATEUR

    def test_le_numero_de_diffusion_n_est_pas_un_noeud(self, administrateur):
        with pytest.raises(RelaisRefuse):
            identifier(administrateur, "MESHTASTIC", {"node_num": 0xFFFFFFFF}, "PROD")

    def test_la_mauvaise_radio_meshtastic_est_detectee(self, radio_meshtastic):
        with pytest.raises(RelaisRefuse, match="n'est pas"):
            verifier_identite(radio_meshtastic, {"node_num": 0x11111111})

    def test_l_api_ouvre_un_relais_meshtastic_par_l_identite(self, membre, radio_meshtastic):
        reponse = _client(membre).post(reverse("relais_serie"), {
            "protocole": "MESHTASTIC", "identite": {"node_num": 0x1234ABCD},
            "transport": "WIFI",
        }, format="json")

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert reponse.data["compagnon"] == str(radio_meshtastic.id)
        session = SessionRelaisNavigateur.objects.get(utilisateur=membre)
        assert session.compagnon_meshtastic == radio_meshtastic
        assert session.transport == "WIFI"

    def test_un_relais_vivant_lit_SA_file_meshtastic(self, membre, radio_meshtastic):
        ouvrir(membre, radio_meshtastic, "PROD")

        reponse = _client(membre).get("/api/messages-meshtastic/a-envoyer/",
                                      {"compagnon": str(radio_meshtastic.id)})

        assert reponse.status_code == status.HTTP_200_OK

    def test_une_session_meshcore_ne_donne_pas_la_file_meshtastic(self, membre, compagnon,
                                                                  radio_meshtastic):
        ouvrir(membre, compagnon, "PROD")

        reponse = _client(membre).get("/api/messages-meshtastic/a-envoyer/",
                                      {"compagnon": str(compagnon.id)})

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_un_relais_depose_un_dm_entrant_et_le_marque(self, membre, radio_meshtastic):
        ouvrir(membre, radio_meshtastic, "PROD")
        client = _client(membre)

        depot = client.post("/api/messages-meshtastic/", {
            "compagnon": str(radio_meshtastic.id), "direction": "ENTRANT",
            "contact_node_num": 0x0BADCAFE, "contenu": "Arrivés sur zone",
        }, format="json")
        assert depot.status_code == status.HTTP_201_CREATED, depot.data

        sortant = MessageMeshtasticLog.objects.create(
            compagnon=radio_meshtastic, direction=DirectionMessageMesh.SORTANT,
            contact_node_num=0x0BADCAFE, contenu="Reçu", environment="PROD")
        marque = client.patch(f"/api/messages-meshtastic/{sortant.id}/", {"statut": "ENVOYE"},
                              format="json")
        assert marque.status_code == status.HTTP_200_OK, marque.data

    def test_un_relais_depose_un_message_de_canal_entrant(self, membre, radio_meshtastic,
                                                         mairie):
        """Le compagnon est nommé dans l'URL : dans le corps, il ciblerait le message.

        Le canal est obligatoire et non nul : le navigateur le retrouve par son NOM, lu dans la
        configuration de la radio, parmi les canaux déclarés (`/canaux-meshtastic/`, sans PSK).
        """
        canal = CanalMeshtastic.objects.create(nom="Fr_EMCOM", institution=mairie,
                                               environment="PROD")
        ouvrir(membre, radio_meshtastic, "PROD")

        depot = _client(membre).post(
            f"/api/messages-canal-meshtastic/?compagnon={radio_meshtastic.id}",
            {"direction": "ENTRANT", "contact_node_num": 0x0BADCAFE, "contenu": "Route coupée",
             "canal": str(canal.id)},
            format="json")

        assert depot.status_code == status.HTTP_201_CREATED, depot.data

    def test_le_pont_meshtastic_n_ouvre_pas_une_radio_de_navigateur(self, create_user,
                                                                   radio_meshtastic):
        """Il traite tout type inconnu comme du MQTT : il se connecterait au broker avec
        l'identité de cette radio."""
        pont = create_user(username="pont-mt@test.fr", email="pont-mt@test.fr",
                           type=UserRole.SIMPLE_USER)
        pont.compte_service_pont = True
        pont.save()

        reponse = _client(pont).get("/api/compagnons-meshtastic/actifs-avec-identifiants/")

        assert str(radio_meshtastic.id) not in [c["id"] for c in reponse.json()]


class TestLaFailleMeshtasticFermee:
    """Mêmes trous que MeshCore la veille, constatés le 14/11/2026."""

    def test_sans_relais_on_ne_lit_pas_la_file_meshtastic(self, etranger, radio_meshtastic):
        reponse = _client(etranger).get("/api/messages-meshtastic/a-envoyer/",
                                        {"compagnon": str(radio_meshtastic.id)})
        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_sans_compagnon_la_file_globale_meshtastic_n_est_plus_servie(self, membre,
                                                                        radio_meshtastic):
        ouvrir(membre, radio_meshtastic, "PROD")
        reponse = _client(membre).get("/api/messages-meshtastic/a-envoyer/")
        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_on_ne_depose_pas_un_faux_dm_entrant(self, etranger, radio_meshtastic):
        reponse = _client(etranger).post("/api/messages-meshtastic/", {
            "compagnon": str(radio_meshtastic.id), "direction": "ENTRANT",
            "contact_node_num": 1, "contenu": "faux",
        }, format="json")
        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_on_ne_depose_pas_un_faux_message_de_canal(self, etranger, radio_meshtastic):
        reponse = _client(etranger).post("/api/messages-canal-meshtastic/", {
            "direction": "ENTRANT", "contact_node_num": 1, "contenu": "faux",
        }, format="json")
        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_le_chat_de_canal_sortant_reste_ouvert(self, etranger):
        """Le durcissement ne touche que l'entrant : le sortant garde la règle historique."""
        reponse = _client(etranger).post("/api/messages-canal-meshtastic/", {
            "direction": "SORTANT", "contenu": "test",
        }, format="json")
        assert reponse.status_code != status.HTTP_403_FORBIDDEN


class TestUneRadioDeNavigateurNeCaptePasLesMessages:
    """Correction du 14/11/2026.

    Le serveur choisit seul la radio qui enverra une clé de canal d'équipe ou un message direct.
    Une radio branchée une seule fois depuis un navigateur restait déclarée et active, donc
    éligible : les messages lui étaient confiés et attendaient qu'on la rebranche, sans que
    personne ne le voie."""

    @pytest.fixture
    def radio_navigateur(self, mairie):
        return CompagnonMeshCore.objects.create(
            institution=mairie, nom="Radio d'un bénévole", environment="PROD",
            connexion_type=MeshCoreConnexionType.NAVIGATEUR, pubkey_hex="ab" * 32)

    def test_eteinte_elle_n_est_pas_choisie_pour_l_equipe(self, radio_navigateur, compagnon, mairie):
        from core.models import Team
        from core.views import _compagnon_pour_equipe
        equipe = Team.objects.create(name="Équipe test", institution=mairie)

        assert _compagnon_pour_equipe(CompagnonMeshCore, equipe) == compagnon

    def test_eteinte_et_seule_elle_n_est_toujours_pas_choisie(self, radio_navigateur, compagnon, mairie):
        """Mieux vaut « aucune radio » — visible — qu'une file qui attend en silence."""
        from core.models import Team
        from core.views import _compagnon_pour_equipe
        compagnon.delete()
        equipe = Team.objects.create(name="Équipe seule", institution=mairie)

        assert _compagnon_pour_equipe(CompagnonMeshCore, equipe) is None

    def test_relayee_elle_redevient_un_emetteur(self, radio_navigateur, membre, mairie, compagnon):
        from core.models import Team
        from core.views import _compagnon_pour_equipe
        compagnon.delete()
        ouvrir(membre, radio_navigateur, "PROD")
        equipe = Team.objects.create(name="Équipe relayée", institution=mairie)

        assert _compagnon_pour_equipe(CompagnonMeshCore, equipe) == radio_navigateur

    def test_le_routage_des_messages_directs_l_ignore_eteinte(self, radio_navigateur, compagnon, mairie):
        from core.models import ContactMeshCore
        from core.routage_mesh import meilleur_compagnon_pour_contact
        # Même si elle a entendu le destinataire, au plus court :
        ContactMeshCore.objects.create(compagnon=radio_navigateur, pubkey_hex="cd" * 32,
                                       nombre_sauts=0, environment="PROD")

        resultat = meilleur_compagnon_pour_contact(pubkey_hex="cd" * 32, institution=mairie)

        assert resultat.compagnon == compagnon

    def test_la_liste_d_envoi_de_l_interface_l_omet(self, radio_navigateur, compagnon, membre):
        reponse = _client(membre).get("/api/compagnons-meshcore/envoyables/")

        ids = [c["id"] for c in reponse.json()]
        assert str(compagnon.id) in ids
        assert str(radio_navigateur.id) not in ids

    def test_un_envoi_explicite_vers_elle_est_refuse(self, radio_navigateur, create_user):
        regulateur = create_user(username="regul-relais@test.fr", email="regul-relais@test.fr",
                                 type=UserRole.LOCAL_AUTHORITY)

        reponse = _client(regulateur).post("/api/messages-meshcore/", {
            "compagnon": str(radio_navigateur.id), "direction": "SORTANT",
            "contact_pubkey_hex": "cd" * 32, "contenu": "Rentrez",
        }, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "plus relayée" in str(reponse.data)

    def test_debrancher_rend_ses_messages_en_attente(self, radio_navigateur, compagnon, membre):
        """Ce qui n'était pas parti au moment où l'on débranche ne reste pas en otage."""
        session, _ = ouvrir(membre, radio_navigateur, "PROD")
        message = MessageMeshLog.objects.create(
            compagnon=radio_navigateur, direction=DirectionMessageMesh.SORTANT,
            contact_pubkey_hex="cd" * 32, contenu="x", environment="PROD")

        from core.relais_navigateur import fermer
        fermer(session, "test")

        message.refresh_from_db()
        assert message.compagnon == compagnon

    def test_un_relais_mort_rend_aussi_ses_messages(self, radio_navigateur, compagnon, membre):
        session, _ = ouvrir(membre, radio_navigateur, "PROD")
        message = MessageMeshLog.objects.create(
            compagnon=radio_navigateur, direction=DirectionMessageMesh.SORTANT,
            contact_pubkey_hex="cd" * 32, contenu="x", environment="PROD")
        SessionRelaisNavigateur.objects.filter(pk=session.pk).update(
            dernier_contact=timezone.now() - timezone.timedelta(seconds=SECONDES_AVANT_SESSION_MORTE + 5))

        fermer_sessions_mortes()

        message.refresh_from_db()
        assert message.compagnon == compagnon

    def test_sans_autre_radio_dans_l_institution_les_messages_restent(self, radio_navigateur,
                                                                     compagnon, membre):
        """Jamais vers une radio d'une autre institution."""
        compagnon.delete()
        session, _ = ouvrir(membre, radio_navigateur, "PROD")
        message = MessageMeshLog.objects.create(
            compagnon=radio_navigateur, direction=DirectionMessageMesh.SORTANT,
            contact_pubkey_hex="cd" * 32, contenu="x", environment="PROD")

        from core.relais_navigateur import fermer
        fermer(session, "test")

        message.refresh_from_db()
        assert message.compagnon == radio_navigateur
