import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Besoin,
    ContactInstitution,
    Crisis,
    ImplicationInstitution,
    Institution,
    InstitutionType,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise implication update", type="INCEDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE_IMPL_UPDATE_TEST", libelle="Mairie")
    return Institution.objects.create(nom="Mairie implication update test", type=itype)


@pytest.fixture
def declarant(create_user, institution):
    user = create_user(username="declarant-impl-update@test.fr", email="declarant-impl-update@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    return user


@pytest.fixture
def implication(crisis, institution, declarant):
    return ImplicationInstitution.objects.create(
        crise=crisis, institution=institution, type_implication="IMPLIQUE",
        utilisateur=declarant, actif=True,
    )


@pytest.mark.django_db
class TestImplicationUpdatePermission:

    def test_declarant_can_update_themes(self, declarant, implication):
        besoin = Besoin.objects.create(nom="Besoin implication update test")
        client = APIClient()
        client.force_authenticate(user=declarant)

        response = client.patch(
            reverse('implicationinstitution-detail', args=[implication.id]),
            {"themes": [str(besoin.id)]},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        implication.refresh_from_db()
        assert list(implication.themes.values_list('id', flat=True)) == [besoin.id]

    def test_institution_contact_can_update(self, institution, implication, create_user):
        contact = create_user(username="contact-impl-update@test.fr", email="contact-impl-update@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=institution, utilisateur=contact, actif=True)
        client = APIClient()
        client.force_authenticate(user=contact)

        response = client.patch(
            reverse('implicationinstitution-detail', args=[implication.id]),
            {"commentaire": "maj"},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK

    def test_admin_can_update(self, create_user, implication):
        admin = create_user(username="admin-impl-update@test.fr", email="admin-impl-update@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.patch(
            reverse('implicationinstitution-detail', args=[implication.id]),
            {"commentaire": "maj admin"},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK

    def test_unrelated_user_cannot_update(self, create_user, implication):
        autre = create_user(username="tiers-impl-update@test.fr", email="tiers-impl-update@test.fr", type="AUT_LOCALE")
        client = APIClient()
        client.force_authenticate(user=autre)

        response = client.patch(
            reverse('implicationinstitution-detail', args=[implication.id]),
            {"commentaire": "hack"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        implication.refresh_from_db()
        assert implication.commentaire != "hack"
