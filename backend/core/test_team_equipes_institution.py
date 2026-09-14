import pytest
from django.urls import reverse
from rest_framework import status

from core.models import Institution, InstitutionType, Team, User


def _make_institution(nom, commune_code="38185"):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_EQINST", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom=nom, type=itype, commune_code=commune_code, commune_nom="Grenoble")


def _make_user(email, institution):
    return User.objects.create_user(
        username=email, email=email, password="Test1234!", type="AUT_LOCALE", institution=institution,
    )


@pytest.mark.django_db
class TestEquipesInstitution:
    """GET /api/teams/equipes-institution/ — contrairement à vue_mairie (toute la commune,
    toutes institutions), ne doit renvoyer QUE les équipes de la SEULE institution de
    l'appelant (voir demande utilisateur du 2026-09-15 : le wizard de démarrage de crise ne
    doit proposer que "mes équipes", pas celles d'institutions tierces de la même commune)."""

    def test_only_own_institution_teams(self, api_client):
        mairie = _make_institution("Mairie de Testville")
        autre = _make_institution("Association locale", commune_code="38185")
        user = _make_user("agent@testville.fr", mairie)
        Team.objects.create(name="Équipe mairie", institution=mairie)
        Team.objects.create(name="Équipe association", institution=autre)

        api_client.force_authenticate(user=user)
        response = api_client.get(reverse('team-equipes-institution'))

        assert response.status_code == status.HTTP_200_OK
        noms = [t['name'] for t in response.data]
        assert noms == ["Équipe mairie"]

    def test_vue_mairie_still_returns_whole_commune(self, api_client):
        """Non-régression : vue_mairie doit rester inchangée (toutes les institutions de la
        commune), seule equipes_institution restreint à une seule institution."""
        mairie = _make_institution("Mairie de Vieuxville", commune_code="38111")
        autre = _make_institution("Association Vieuxville", commune_code="38111")
        user = _make_user("agent@vieuxville.fr", mairie)
        Team.objects.create(name="Équipe mairie V", institution=mairie)
        Team.objects.create(name="Équipe association V", institution=autre)

        api_client.force_authenticate(user=user)
        response = api_client.get(reverse('team-vue-mairie'))

        assert response.status_code == status.HTTP_200_OK
        noms = {t['name'] for t in response.data}
        assert noms == {"Équipe mairie V", "Équipe association V"}

    def test_requires_institution(self, authenticated_client):
        client, user = authenticated_client
        user.type = 'SECOURS'
        user.institution = None
        user.save()

        response = client.get(reverse('team-equipes-institution'))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_requires_institutional_actor(self, api_client):
        institution = _make_institution("Mairie Simple")
        user = User.objects.create_user(
            username="simple@testville.fr", email="simple@testville.fr", password="Test1234!",
            type="UTIL_SIMPLE", institution=institution,
        )
        api_client.force_authenticate(user=user)

        response = api_client.get(reverse('team-equipes-institution'))

        assert response.status_code == status.HTTP_403_FORBIDDEN
