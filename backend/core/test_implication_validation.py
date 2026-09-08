"""Workflow d'acceptation d'une déclaration ACTEUR par une institution non-AUT_LOCALE
(association/AASC...) : ImplicationInstitution.statut passe par EN_ATTENTE jusqu'à validation
par un régulateur AUT_LOCALE de la crise (ImplicationInstitutionViewSet.valider/refuser). Les
déclarations IMPLIQUE et les déclarations ACTEUR d'une institution AUT_LOCALE (mairie/EPCI)
restent auto-validées comme avant ce chantier."""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution,
    Crisis,
    ImplicationInstitution,
    Institution,
    InstitutionType,
    Notification,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise validation implication", type="INCENDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie validation test", type=itype)


@pytest.fixture
def association(db):
    itype, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="Association validation test", type=itype)


@pytest.fixture
def regulateur_mairie(create_user, mairie, crisis):
    """Régulateur AUT_LOCALE dont l'institution (mairie) est déjà validée/active sur la crise —
    seul profil autorisé à valider/refuser une déclaration ACTEUR en attente."""
    user = create_user(username="regul-mairie@test.fr", email="regul-mairie@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    ImplicationInstitution.objects.create(
        crise=crisis, institution=mairie, type_implication="IMPLIQUE", utilisateur=user, actif=True,
    )
    return user


@pytest.fixture
def membre_association(create_user, association):
    user = create_user(username="membre-asso@test.fr", email="membre-asso@test.fr", type="SECOURS")
    ContactInstitution.objects.create(institution=association, utilisateur=user, actif=True)
    return user


@pytest.mark.django_db
class TestDeclarationActeurNonAutLocale:

    def test_association_declarant_acteur_reste_en_attente(self, membre_association, association, crisis, regulateur_mairie):
        client = APIClient()
        client.force_authenticate(user=membre_association)

        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(association.id), "type_implication": "ACTEUR"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["statut"] == "EN_ATTENTE"
        implication = ImplicationInstitution.objects.get(id=response.data["id"])
        assert implication.statut == "EN_ATTENTE"
        assert Notification.objects.filter(utilisateur=regulateur_mairie, titre__icontains=association.nom).exists()

    def test_association_declarant_implique_est_validee_immediatement(self, membre_association, association, crisis):
        client = APIClient()
        client.force_authenticate(user=membre_association)

        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(association.id), "type_implication": "IMPLIQUE"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["statut"] == "VALIDEE"

    def test_mairie_declarant_acteur_est_validee_immediatement(self, create_user, mairie, crisis):
        user = create_user(username="regul-mairie2@test.fr", email="regul-mairie2@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(mairie.id), "type_implication": "ACTEUR"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["statut"] == "VALIDEE"

    def test_client_ne_peut_pas_forcer_le_statut_a_la_creation(self, membre_association, association, crisis):
        client = APIClient()
        client.force_authenticate(user=membre_association)

        response = client.post(
            reverse('implicationinstitution-list'),
            {
                "crise": str(crisis.id), "institution": str(association.id),
                "type_implication": "ACTEUR", "statut": "VALIDEE",
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["statut"] == "EN_ATTENTE"


@pytest.mark.django_db
class TestValiderRefuserImplication:

    @pytest.fixture
    def implication_en_attente(self, association, crisis, membre_association):
        return ImplicationInstitution.objects.create(
            crise=crisis, institution=association, type_implication="ACTEUR",
            utilisateur=membre_association, actif=True, statut="EN_ATTENTE",
        )

    def test_regulateur_mairie_peut_valider(self, regulateur_mairie, implication_en_attente):
        client = APIClient()
        client.force_authenticate(user=regulateur_mairie)

        response = client.post(
            reverse('implicationinstitution-valider', args=[implication_en_attente.id])
        )

        assert response.status_code == status.HTTP_200_OK
        implication_en_attente.refresh_from_db()
        assert implication_en_attente.statut == "VALIDEE"

    def test_regulateur_mairie_peut_refuser(self, regulateur_mairie, implication_en_attente):
        client = APIClient()
        client.force_authenticate(user=regulateur_mairie)

        response = client.post(
            reverse('implicationinstitution-refuser', args=[implication_en_attente.id])
        )

        assert response.status_code == status.HTTP_200_OK
        implication_en_attente.refresh_from_db()
        assert implication_en_attente.statut == "REFUSEE"

    def test_declarant_lui_meme_ne_peut_pas_valider(self, membre_association, implication_en_attente):
        client = APIClient()
        client.force_authenticate(user=membre_association)

        response = client.post(
            reverse('implicationinstitution-valider', args=[implication_en_attente.id])
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        implication_en_attente.refresh_from_db()
        assert implication_en_attente.statut == "EN_ATTENTE"

    def test_aut_locale_non_impliquee_sur_la_crise_ne_peut_pas_valider(self, create_user, implication_en_attente):
        itype = InstitutionType.objects.create(code="MAIRIE_TIERCE", libelle="Mairie")
        autre_mairie = Institution.objects.create(nom="Mairie tierce validation test", type=itype)
        user = create_user(username="regul-tiers@test.fr", email="regul-tiers@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=autre_mairie, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.post(
            reverse('implicationinstitution-valider', args=[implication_en_attente.id])
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_ne_peut_pas_revalider_une_implication_deja_traitee(self, regulateur_mairie, implication_en_attente):
        client = APIClient()
        client.force_authenticate(user=regulateur_mairie)
        client.post(reverse('implicationinstitution-valider', args=[implication_en_attente.id]))

        response = client.post(reverse('implicationinstitution-valider', args=[implication_en_attente.id]))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_peut_valider_visible_uniquement_pour_le_regulateur_habilite(self, regulateur_mairie, membre_association, implication_en_attente):
        client = APIClient()

        client.force_authenticate(user=regulateur_mairie)
        response = client.get(reverse('implicationinstitution-detail', args=[implication_en_attente.id]))
        assert response.data["peut_valider"] is True

        client.force_authenticate(user=membre_association)
        response = client.get(reverse('implicationinstitution-detail', args=[implication_en_attente.id]))
        assert response.data["peut_valider"] is False
