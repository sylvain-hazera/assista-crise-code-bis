"""API du recrutement et des qualifications d'une association.

Ce que ces tests tiennent, et c'est de la sécurité :

1. **Les étapes ne se franchissent QUE par les actions dédiées.** `etape` est en lecture seule
   dans le serializer, sans quoi un PATCH poserait une candidature « acceptée » sans rattacher
   personne — exactement l'état incohérent qu'on a déjà payé (voir § 5.11, « deux réponses en
   base »).
2. **Le bureau instruit, les membres non**, et personne ne voit les candidatures d'une autre
   association.
3. **Un candidat suit son propre dossier.** Ne rien lui montrer après qu'il a demandé à
   rejoindre est la meilleure façon de le perdre.
4. **Les qualifications d'autrui ne sont pas publiques** : un titre dit quelque chose du
   parcours de quelqu'un.
"""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    CandidatureAssociation, ContactInstitution, Institution, InstitutionType,
    InvitationAssociation, Qualification, QualificationMembre, UserRole,
)
from core.recrutement_association import demander_a_rejoindre

Etape = CandidatureAssociation.Etape


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.fixture
def aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    institution, _ = Institution.objects.get_or_create(
        nom="AASC API Test", defaults={"type": itype, "actif": True})
    return institution


@pytest.fixture
def autre_aasc(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "AASC"})
    institution, _ = Institution.objects.get_or_create(
        nom="AASC API Voisine", defaults={"type": itype, "actif": True})
    return institution


@pytest.fixture
def bureau(create_user, aasc):
    user = create_user(username="bureau-api@test.fr", email="bureau-api@test.fr",
                       type=UserRole.LOCAL_AUTHORITY, last_name="BUREAU")
    ContactInstitution.objects.create(
        institution=aasc, utilisateur=user, fonction="Président",
        membre_bureau=True, actif=True)
    return user


@pytest.fixture
def membre_simple(create_user, aasc):
    user = create_user(username="simple-api@test.fr", email="simple-api@test.fr",
                       type=UserRole.ORGANIZED_RESCUE, last_name="EQUIPIER")
    ContactInstitution.objects.create(
        institution=aasc, utilisateur=user, fonction="Équipier", actif=True)
    return user


@pytest.fixture
def candidat(create_user):
    return create_user(username="candidat-api@test.fr", email="candidat-api@test.fr",
                       type=UserRole.ORGANIZED_RESCUE, last_name="CANDIDAT",
                       enabled=False, is_active=False)


@pytest.fixture
def candidature(aasc, candidat):
    return demander_a_rejoindre(aasc, candidat)[0]


class TestFranchirLesEtapes:
    def test_le_bureau_prend_en_charge_puis_accepte(self, bureau, candidature, candidat, aasc):
        client = _client(bureau)

        r1 = client.post(reverse("candidatureassociation-prendre-en-charge",
                                 args=[candidature.id]))
        assert r1.status_code == status.HTTP_200_OK, r1.data
        assert r1.data["etape"] == Etape.PRISE_EN_CHARGE

        r2 = client.post(reverse("candidatureassociation-verifier", args=[candidature.id]))
        assert r2.data["etape"] == Etape.VERIFICATION

        r3 = client.post(reverse("candidatureassociation-accepter", args=[candidature.id]))
        assert r3.data["etape"] == Etape.ACCEPTE

        candidat.refresh_from_db()
        assert candidat.is_active is True
        assert candidat.institution_id == aasc.pk

    def test_letape_ne_se_change_pas_par_un_patch(self, bureau, candidature, candidat):
        """LE test de sécurité. `etape` est read_only : un PATCH accepté poserait une
        candidature « acceptée » sans activer le compte ni rattacher personne."""
        reponse = _client(bureau).patch(
            reverse("candidatureassociation-detail", args=[candidature.id]),
            {"etape": Etape.ACCEPTE}, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        candidature.refresh_from_db()
        assert candidature.etape == Etape.DEMANDE
        candidat.refresh_from_db()
        assert candidat.institution_id is None

    def test_reculer_est_refuse_avec_un_message_lisible(self, bureau, candidature):
        client = _client(bureau)
        client.post(reverse("candidatureassociation-verifier", args=[candidature.id]))

        reponse = client.post(reverse("candidatureassociation-prendre-en-charge",
                                      args=[candidature.id]))

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "ne recule pas" in reponse.data["error"]

    def test_un_refus_sans_motif_est_refuse(self, bureau, candidature):
        reponse = _client(bureau).post(
            reverse("candidatureassociation-refuser", args=[candidature.id]), {}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        candidature.refresh_from_db()
        assert candidature.etape == Etape.DEMANDE

    def test_un_refus_motive_passe(self, bureau, candidature):
        reponse = _client(bureau).post(
            reverse("candidatureassociation-refuser", args=[candidature.id]),
            {"motif": "Hors zone d'intervention."}, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["etape"] == Etape.REFUSE


class TestQuiInstruit:
    def test_un_membre_simple_ne_voit_meme_pas_le_dossier(self, membre_simple, candidature):
        """404 et non 403 : le dossier est hors de son queryset, donc il n'apprend même pas
        qu'il existe. Meilleur que ce que j'attendais en écrivant ce test — dire « interdit »
        confirmerait qu'une candidature est en cours dans son association."""
        reponse = _client(membre_simple).post(
            reverse("candidatureassociation-prendre-en-charge", args=[candidature.id]))

        assert reponse.status_code == status.HTTP_404_NOT_FOUND

    def test_le_candidat_ne_sauto_accepte_pas(self, candidat, candidature):
        """Lui VOIT son dossier (il doit pouvoir le suivre) : c'est donc ici que la garde de
        droits se fait vraiment valoir, en 403."""
        reponse = _client(candidat).post(
            reverse("candidatureassociation-accepter", args=[candidature.id]))

        assert reponse.status_code == status.HTTP_403_FORBIDDEN
        candidature.refresh_from_db()
        assert candidature.etape == Etape.DEMANDE
        candidat.refresh_from_db()
        assert candidat.institution_id is None

    def test_le_bureau_dune_autre_association_ne_voit_pas_le_dossier(
            self, create_user, autre_aasc, candidature):
        """404 et non 403 : lui dire « interdit » confirmerait l'existence du dossier."""
        intrus = create_user(username="intrus-api@test.fr", email="intrus-api@test.fr",
                             type=UserRole.LOCAL_AUTHORITY, last_name="INTRUS")
        ContactInstitution.objects.create(
            institution=autre_aasc, utilisateur=intrus, fonction="Président",
            membre_bureau=True, actif=True)

        reponse = _client(intrus).post(
            reverse("candidatureassociation-prendre-en-charge", args=[candidature.id]))

        assert reponse.status_code == status.HTTP_404_NOT_FOUND


class TestCeQueChacunVoit:
    def test_le_bureau_voit_les_candidatures_de_son_association(self, bureau, candidature):
        reponse = _client(bureau).get(reverse("candidatureassociation-list"))

        assert reponse.status_code == status.HTTP_200_OK
        assert str(candidature.id) in [c["id"] for c in reponse.data]

    def test_le_candidat_suit_son_propre_dossier(self, candidat, candidature):
        """Ne rien lui montrer après qu'il a demandé à rejoindre est la meilleure façon de le
        perdre."""
        reponse = _client(candidat).get(reverse("candidatureassociation-list"))

        assert [c["id"] for c in reponse.data] == [str(candidature.id)]
        assert reponse.data[0]["etape_libelle"] == "Demande reçue"

    def test_un_membre_simple_ne_voit_aucune_candidature(self, membre_simple, candidature):
        reponse = _client(membre_simple).get(reverse("candidatureassociation-list"))

        assert reponse.data == []

    def test_un_anonyme_na_pas_acces(self, candidature):
        reponse = APIClient().get(reverse("candidatureassociation-list"))

        assert reponse.status_code in (status.HTTP_401_UNAUTHORIZED,
                                       status.HTTP_403_FORBIDDEN)


class TestRejoindreParLien:
    @pytest.fixture
    def invitation(self, aasc, bureau):
        return InvitationAssociation.objects.create(
            institution=aasc, cree_par=bureau, libelle="Forum 2026")

    def test_le_lien_depose_une_candidature_sans_rien_accorder(
            self, invitation, candidat, aasc):
        reponse = _client(candidat).post(
            reverse("candidatureassociation-rejoindre"),
            {"jeton": invitation.jeton, "message": "Disponible le week-end."}, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        assert reponse.data["etape"] == Etape.DEMANDE
        candidat.refresh_from_db()
        assert candidat.institution_id is None
        assert candidat.is_active is False

    def test_un_jeton_invalide_ne_dit_pas_pourquoi(self, candidat):
        """Distinguer « inconnu » de « expiré » aiderait à deviner un jeton."""
        reponse = _client(candidat).post(
            reverse("candidatureassociation-rejoindre"),
            {"jeton": "pas-un-vrai-jeton"}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "n'est pas (ou plus) valide" in reponse.data["error"]

    def test_deposer_deux_fois_ne_cree_pas_deux_dossiers(self, invitation, candidat):
        client = _client(candidat)
        url = reverse("candidatureassociation-rejoindre")

        premier = client.post(url, {"jeton": invitation.jeton}, format="json")
        second = client.post(url, {"jeton": invitation.jeton}, format="json")

        assert premier.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_200_OK
        assert CandidatureAssociation.objects.filter(utilisateur=candidat).count() == 1


class TestLiensDInvitation:
    def test_le_bureau_cree_un_lien_et_le_serveur_fabrique_le_jeton(self, bureau, aasc):
        reponse = _client(bureau).post(
            reverse("invitationassociation-list"),
            {"institution": str(aasc.id), "libelle": "Forum 2026"}, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        assert len(reponse.data["jeton"]) >= 32
        assert reponse.data["utilisable"] is True

    def test_un_jeton_choisi_par_lappelant_est_ignore(self, bureau, aasc):
        """Un lien devinable serait la porte du circuit de recrutement."""
        reponse = _client(bureau).post(
            reverse("invitationassociation-list"),
            {"institution": str(aasc.id), "jeton": "jeton-facile"}, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED
        assert reponse.data["jeton"] != "jeton-facile"

    def test_un_membre_simple_ne_cree_pas_de_lien(self, membre_simple, aasc):
        reponse = _client(membre_simple).post(
            reverse("invitationassociation-list"),
            {"institution": str(aasc.id)}, format="json")

        assert reponse.status_code == status.HTTP_403_FORBIDDEN

    def test_le_bureau_ne_voit_que_les_liens_de_son_association(
            self, bureau, aasc, autre_aasc):
        InvitationAssociation.objects.create(institution=aasc, cree_par=bureau)
        InvitationAssociation.objects.create(institution=autre_aasc)

        reponse = _client(bureau).get(reverse("invitationassociation-list"))

        assert {str(c["institution"]) for c in reponse.data} == {str(aasc.id)}


class TestQualifications:
    @pytest.fixture
    def pse1(self, db):
        return Qualification.objects.create(nom="PSE1 API Test", validite_mois=12)

    def test_le_bureau_voit_les_titres_de_ses_membres(
            self, bureau, membre_simple, pse1):
        QualificationMembre.objects.create(
            utilisateur=membre_simple, qualification=pse1, environment="PROD")

        reponse = _client(bureau).get(reverse("qualificationmembre-list"))

        assert reponse.status_code == status.HTTP_200_OK
        assert [q["utilisateur_nom"] for q in reponse.data] == ["Test EQUIPIER"]

    def test_un_membre_ne_voit_pas_les_titres_dun_autre(
            self, membre_simple, bureau, pse1):
        """Un titre dit quelque chose du parcours de quelqu'un."""
        QualificationMembre.objects.create(
            utilisateur=bureau, qualification=pse1, environment="PROD")

        reponse = _client(membre_simple).get(reverse("qualificationmembre-list"))

        assert reponse.data == []

    def test_chacun_voit_les_siens(self, membre_simple, pse1):
        QualificationMembre.objects.create(
            utilisateur=membre_simple, qualification=pse1, environment="PROD")

        reponse = _client(membre_simple).get(reverse("qualificationmembre-list"))

        assert len(reponse.data) == 1

    def test_lecheance_est_calculee_par_le_serveur(self, bureau, pse1):
        """Et non dans le navigateur : l'horloge d'un poste client est réglable, et une
        qualification qu'on croit valide parce que la date est fausse est l'erreur qu'on
        découvre le jour de la mobilisation."""
        import datetime

        from django.utils import timezone

        reponse = _client(bureau).post(
            reverse("qualificationmembre-list"),
            {"utilisateur": str(bureau.id), "qualification": str(pse1.id),
             "date_expiration": str(timezone.localdate() + datetime.timedelta(days=30))},
            format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        assert reponse.data["jours_avant_expiration"] == 30
        assert reponse.data["expiree"] is False

    def test_qui_a_saisi_est_enregistre(self, bureau, membre_simple, pse1):
        """Une qualification affirmée par le bureau n'a pas le même poids qu'une ligne
        déclarée par l'intéressé."""
        reponse = _client(bureau).post(
            reverse("qualificationmembre-list"),
            {"utilisateur": str(membre_simple.id), "qualification": str(pse1.id)},
            format="json")

        assert reponse.status_code == status.HTTP_201_CREATED
        assert str(reponse.data["saisie_par"]) == str(bureau.id)
