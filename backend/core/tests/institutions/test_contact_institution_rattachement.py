"""Ajouter un contact à une institution DOIT rattacher réellement la personne.

« Dans quelle institution est cet utilisateur » a deux réponses en base :
`ContactInstitution`, la relation faisant autorité, et le raccourci `User.institution`, que
lisent les vues territoriales (`zone_scoping._institution_commune_or_400`). Le chemin
« ajouter un contact » de l'administration — le plus utilisé — créait la ligne de contact sans
poser le raccourci. La personne utilisait donc normalement l'application SAUF les sept vues
`*-vue-mairie` / `*-vue-secteur`, qui lui répondaient « Aucune commune associée à votre
institution : contactez un administrateur » — alors que l'administrateur venait précisément de
la rattacher, et que son geste ne pouvait rien y changer.

Mesuré en production le 27/10/2026 : 4 comptes actifs dans cet état, dont un agent qui a
accumulé 75 échecs sur quatre sessions avant de cesser de revenir.

Le commentaire de `grant_institution_and_demo_access` affirmait déjà être appelée par tous les
chemins de rattachement. C'était faux, et c'est ce qui a rendu le trou invisible : d'où ces
tests, qui vérifient la chose au lieu de l'affirmer.
"""
import pytest
from django.core.management import call_command
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType, Team, User


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(
        nom="Mairie de Plougastel (rattachement)", type=itype,
        commune_code="29189", commune_nom="Plougastel-Daoulas")


@pytest.fixture
def autre_mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(
        nom="Mairie de Crozon (rattachement)", type=itype,
        commune_code="29042", commune_nom="Crozon")


@pytest.fixture
def admin_client(create_user):
    admin = create_user(username="admin-ratt@test.fr", email="admin-ratt@test.fr",
                        type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


@pytest.fixture
def agent(create_user):
    return create_user(username="agent-ratt@test.fr", email="agent-ratt@test.fr",
                       type="AUT_LOCALE", last_name="LARVOR")


def _ajouter(client, institution, utilisateur, **extra):
    return client.post(reverse("contactinstitution-list"), {
        "institution": str(institution.id),
        "utilisateur": str(utilisateur.id),
        "fonction": "Rcsc",
        "actif": True,
        **extra,
    }, format="json")


class TestAjoutDunContact:
    def test_le_raccourci_user_institution_est_pose(self, admin_client, mairie, agent):
        """LE test. Sans ça, la personne reste aveugle à sa propre commune sur les vues
        territoriales, et aucun message ne lui dit pourquoi."""
        assert agent.institution_id is None

        reponse = _ajouter(admin_client, mairie, agent)

        assert reponse.status_code == status.HTTP_201_CREATED
        agent.refresh_from_db()
        assert agent.institution_id == mairie.pk

    def test_la_commune_devient_resolvable(self, admin_client, mairie, agent):
        """La conséquence concrète : c'est `institution.commune_code` que cherchent les vues
        `*-vue-mairie` / `*-vue-secteur`."""
        _ajouter(admin_client, mairie, agent)

        agent.refresh_from_db()
        assert agent.institution.commune_code == "29189"

    def test_la_personne_entre_dans_lequipe_de_linstitution(self, admin_client, mairie, agent):
        _ajouter(admin_client, mairie, agent)

        assert Team.objects.filter(institution=mairie, members=agent).exists()

    def test_lacces_a_la_demonstration_est_ouvert(self, admin_client, mairie, agent):
        """Un compte institutionnel réel doit pouvoir essayer la démo sans un octroi manuel
        séparé — c'est la raison d'être de grant_institution_and_demo_access, et ce chemin en
        était privé."""
        assert not agent.demo_role

        _ajouter(admin_client, mairie, agent)

        agent.refresh_from_db()
        assert agent.demo_role == agent.type

    def test_la_ligne_de_contact_est_bien_creee(self, admin_client, mairie, agent):
        """Garde-fou : la correction ne doit rien retirer au comportement d'origine."""
        _ajouter(admin_client, mairie, agent)

        contact = ContactInstitution.objects.get(institution=mairie, utilisateur=agent)
        assert contact.actif is True
        assert contact.fonction == "Rcsc"


class TestCeQuiNeDoitPasChanger:
    def test_un_profil_deja_rattache_nest_jamais_detourne(
            self, admin_client, mairie, autre_mairie, agent):
        """Quelqu'un peut être membre de plusieurs institutions ; son contexte « Vue Ma
        Collectivité » lui appartient et ne doit pas basculer parce qu'on l'ajoute ailleurs."""
        agent.institution = autre_mairie
        agent.save(update_fields=["institution"])

        _ajouter(admin_client, mairie, agent)

        agent.refresh_from_db()
        assert agent.institution_id == autre_mairie.pk
        # Mais le rattachement, lui, existe bien.
        assert ContactInstitution.objects.filter(
            institution=mairie, utilisateur=agent, actif=True).exists()

    def test_un_contact_inactif_nouvre_aucun_droit(self, admin_client, mairie, agent):
        """Une ligne créée inactive est une intention, pas un rattachement."""
        _ajouter(admin_client, mairie, agent, actif=False)

        agent.refresh_from_db()
        assert agent.institution_id is None
        assert not Team.objects.filter(institution=mairie, members=agent).exists()


class TestReactivation:
    def test_reactiver_un_contact_ouvre_les_droits(self, admin_client, mairie, agent):
        """Réactiver est un rattachement comme un autre : le même trou s'y trouvait."""
        contact = ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=False)
        assert agent.institution_id is None

        reponse = admin_client.patch(
            reverse("contactinstitution-detail", args=[contact.id]),
            {"actif": True}, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        agent.refresh_from_db()
        assert agent.institution_id == mairie.pk

    def test_desactiver_ne_retire_rien(self, admin_client, mairie, agent):
        """Désactiver un contact ne doit surtout pas appeler l'ouverture des droits — mais ne
        retire rien non plus : retirer `User.institution` d'un compte en service est une
        décision qui appartient à la collectivité, pas à un effet de bord."""
        _ajouter(admin_client, mairie, agent)
        contact = ContactInstitution.objects.get(institution=mairie, utilisateur=agent)

        admin_client.patch(reverse("contactinstitution-detail", args=[contact.id]),
                           {"actif": False}, format="json")

        agent.refresh_from_db()
        assert agent.institution_id == mairie.pk


class TestAucunCompteOublie:
    """L'invariant que le commentaire de grant_institution_and_demo_access affirmait sans le
    vérifier : un ContactInstitution actif implique un User.institution renseigné."""

    def test_aucun_contact_actif_sans_raccourci(self, admin_client, mairie, autre_mairie,
                                                create_user):
        comptes = [
            create_user(username=f"agent-{i}@test.fr", email=f"agent-{i}@test.fr",
                        type="AUT_LOCALE")
            for i in range(3)
        ]
        for i, compte in enumerate(comptes):
            _ajouter(admin_client, mairie if i % 2 == 0 else autre_mairie, compte)

        orphelins = [
            c.utilisateur_id
            for c in ContactInstitution.objects.filter(actif=True).select_related("utilisateur")
            if c.utilisateur.institution_id is None
        ]
        assert orphelins == []


def _simuler_etat_davant(agent):
    """Remet un compte dans l'état d'avant la correction : rattaché, mais sans raccourci.

    Par `update()` et non `save()`, précisément parce que `ContactInstitution.save()` tient
    désormais l'invariant — on ne peut plus produire cet état par les voies normales, ce qui
    est le but. Le rattrapage reste nécessaire pour les lignes créées AVANT, elles."""
    User.objects.filter(pk=agent.pk).update(institution=None)
    agent.refresh_from_db()


class TestRattrapageDesComptesDejaCasses:
    """`backfill_rattachement_institution` : les comptes rattachés avant la correction
    ci-dessus restent aveugles aux vues territoriales tant qu'on ne les reprend pas."""

    def test_le_raccourci_est_pose_pour_un_compte_oublie(self, mairie, agent):
        ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=True)
        _simuler_etat_davant(agent)

        call_command("backfill_rattachement_institution")

        agent.refresh_from_db()
        assert agent.institution_id == mairie.pk
        # Le rattrapage, lui, passe par grant_institution_and_demo_access : il fait l'accueil
        # complet, contrairement au filet posé dans le modèle.
        assert Team.objects.filter(institution=mairie, members=agent).exists()

    def test_le_dry_run_necrit_rien(self, mairie, agent):
        ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=True)
        _simuler_etat_davant(agent)

        call_command("backfill_rattachement_institution", dry_run=True)

        agent.refresh_from_db()
        assert agent.institution_id is None

    def test_un_contact_inactif_nest_pas_rattrape(self, mairie, agent):
        ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=False)

        call_command("backfill_rattachement_institution")

        agent.refresh_from_db()
        assert agent.institution_id is None

    def test_une_institution_desactivee_nest_pas_preferee(self, mairie, autre_mairie, agent):
        """Quelqu'un contact de deux institutions dont l'une a été retirée du service : c'est
        l'institution vivante qui doit devenir son contexte, pas le vestige."""
        autre_mairie.actif = False
        autre_mairie.save(update_fields=["actif"])
        ContactInstitution.objects.create(
            institution=autre_mairie, utilisateur=agent, fonction="Ancien", actif=True)
        ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=True)
        _simuler_etat_davant(agent)

        call_command("backfill_rattachement_institution")

        agent.refresh_from_db()
        assert agent.institution_id == mairie.pk

    def test_relancer_ne_detourne_pas_un_compte_deja_rattache(self, mairie, autre_mairie, agent):
        agent.institution = autre_mairie
        agent.save(update_fields=["institution"])
        ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=True)

        call_command("backfill_rattachement_institution")

        agent.refresh_from_db()
        assert agent.institution_id == autre_mairie.pk


class TestInvariantTenuALaSource:
    """`ContactInstitution.save()` tient l'invariant quel que soit le chemin.

    Corriger `ContactInstitutionViewSet` ne suffisait pas : le prochain chemin de rattachement
    pourrait l'oublier à son tour, et le symptôme est silencieux — la personne utilise
    l'application et découvre seule que certaines pages lui sont fermées. L'invariant est donc
    tenu au seul endroit par lequel toute création passe forcément."""

    def test_une_creation_directe_en_base_pose_le_raccourci(self, mairie, agent):
        """Le cas qui a mordu : du code qui crée la ligne sans passer par la vue."""
        assert agent.institution_id is None

        ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=True)

        agent.refresh_from_db()
        assert agent.institution_id == mairie.pk

    def test_un_rattachement_inactif_ne_pose_rien(self, mairie, agent):
        ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=False)

        agent.refresh_from_db()
        assert agent.institution_id is None

    def test_un_contexte_deja_choisi_nest_jamais_ecrase(self, mairie, autre_mairie, agent):
        """Un profil membre de plusieurs collectivités garde la vue qu'il a choisie."""
        agent.institution = autre_mairie
        agent.save(update_fields=["institution"])

        ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=True)

        agent.refresh_from_db()
        assert agent.institution_id == autre_mairie.pk

    def test_activer_un_rattachement_existant_pose_le_raccourci(self, mairie, agent):
        contact = ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=False)
        assert agent.institution_id is None

        contact.actif = True
        contact.save()

        agent.refresh_from_db()
        assert agent.institution_id == mairie.pk

    def test_le_filet_nenvoie_ni_email_ni_requete_reseau(self, mairie, agent, mailoutbox):
        """Volontairement minimal : l'accueil complet (équipe, démo, messagerie) reste dans
        grant_institution_and_demo_access, qui a besoin d'une requête HTTP. Ce filet ne doit
        pas se mettre à envoyer des emails depuis un script ou une migration."""
        ContactInstitution.objects.create(
            institution=mairie, utilisateur=agent, fonction="Rcsc", actif=True)

        agent.refresh_from_db()
        assert agent.institution_id == mairie.pk
        assert mailoutbox == []
        assert not Team.objects.filter(institution=mairie, members=agent).exists()


class TestMessagesDErreurTerritoriaux:
    """Le message unique « contactez un administrateur » a coûté un utilisateur : il envoyait
    chercher la solution auprès de quelqu'un qui ne pouvait rien y faire."""

    def test_un_compte_sans_rattachement_recoit_un_message_qui_dit_quoi_faire(
            self, create_user):
        from django.test import RequestFactory

        from core.zone_scoping import _institution_commune_or_400

        orphelin = create_user(username="orphelin@test.fr", email="orphelin@test.fr",
                               type="AUT_LOCALE")
        requete = RequestFactory().get("/")
        requete.user = orphelin

        reponse = _institution_commune_or_400(requete)

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "anomalie de rattachement" in reponse.data["error"]

    def test_une_institution_sans_commune_le_dit_et_nomme_la_collectivite(
            self, create_user, db):
        from django.test import RequestFactory

        from core.zone_scoping import _institution_commune_or_400

        itype, _ = InstitutionType.objects.get_or_create(
            code="ASSOCIATION_SANS_COMMUNE", defaults={"libelle": "Association"})
        sans_commune = Institution.objects.create(nom="Croix-Rouge locale", type=itype)
        membre = create_user(username="assoc@test.fr", email="assoc@test.fr",
                             type="AUT_LOCALE")
        membre.institution = sans_commune
        membre.save(update_fields=["institution"])
        requete = RequestFactory().get("/")
        requete.user = membre

        reponse = _institution_commune_or_400(requete)

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "Croix-Rouge locale" in reponse.data["error"]
