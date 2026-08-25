import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    Besoin,
    Crisis,
    ContactInstitution,
    ImplicationInstitution,
    Institution,
    InstitutionType,
    PointOperationnel,
    PointType,
    TypeImplication,
    User,
    UserRole,
)

CRISIS_PAYLOAD = {
    "name": "Incendie de test",
    "type": "INCEDIE",
    "location": "POINT (5.7245 45.1885)",
    "radius": 5,
}


@pytest.fixture
def institution(db):
    itype = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
    return Institution.objects.create(nom="Mairie de Test", type=itype)


@pytest.fixture
def local_authority_client(create_user, institution):
    """Un utilisateur AUT_LOCALE, authentifié et rattaché à `institution` via ContactInstitution.

    Utilise son propre APIClient (pas le fixture `api_client` partagé) pour pouvoir coexister
    dans un même test avec un autre client authentifié (ex: `authenticated_client`, `admin_client`)
    sans que les `force_authenticate` successifs ne s'écrasent l'un l'autre."""
    user = create_user(
        username="autorite-locale@test.fr",
        email="autorite-locale@test.fr",
        type="AUT_LOCALE",
    )
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def admin_client(create_user):
    user = create_user(username="admin-test@test.fr", email="admin-test@test.fr", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestCrisisCreationRestriction:

    def test_anonymous_cannot_create_crisis(self, api_client):
        response = api_client.post(reverse('crisis-list'), CRISIS_PAYLOAD, format='json')
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
        assert not Crisis.objects.exists()

    def test_simple_user_cannot_create_crisis(self, authenticated_client):
        client, user = authenticated_client
        response = client.post(reverse('crisis-list'), CRISIS_PAYLOAD, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not Crisis.objects.exists()

    def test_local_authority_can_create_crisis(self, local_authority_client):
        client, user = local_authority_client
        response = client.post(reverse('crisis-list'), CRISIS_PAYLOAD, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        crisis = Crisis.objects.get(id=response.data["id"])
        assert crisis.author == user

    def test_crisis_zone_polygon_round_trips_as_geojson(self, local_authority_client):
        """zone (WKT en écriture) doit ressortir en zone_geojson (GeoJSON natif) en lecture,
        sans dépendance de parsing WKT côté frontend."""
        client, _ = local_authority_client
        payload = {
            **CRISIS_PAYLOAD,
            "zone": "POLYGON ((5.70 45.18, 5.75 45.18, 5.75 45.20, 5.70 45.20, 5.70 45.18))",
        }
        response = client.post(reverse('crisis-list'), payload, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["zone_geojson"]["type"] == "Polygon"
        assert response.data["zone_geojson"]["coordinates"][0][0] == [5.70, 45.18]

    def test_crisis_without_zone_returns_null_geojson(self, local_authority_client):
        client, _ = local_authority_client
        response = client.post(reverse('crisis-list'), CRISIS_PAYLOAD, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["zone_geojson"] is None

    def test_anonymous_can_still_list_crises(self, api_client, local_authority_client):
        client, _ = local_authority_client
        client.post(reverse('crisis-list'), CRISIS_PAYLOAD, format='json')

        response = api_client.get(reverse('crisis-list'))
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1

    def test_simple_user_cannot_update_crisis(self, local_authority_client, authenticated_client):
        loc_client, _ = local_authority_client
        create_response = loc_client.post(reverse('crisis-list'), CRISIS_PAYLOAD, format='json')
        crisis_id = create_response.data["id"]

        simple_client, _ = authenticated_client
        response = simple_client.patch(
            reverse('crisis-detail', args=[crisis_id]), {"name": "Renommée"}, format='json'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_local_authority_cannot_delete_crisis(self, local_authority_client):
        client, _ = local_authority_client
        create_response = client.post(reverse('crisis-list'), CRISIS_PAYLOAD, format='json')
        crisis_id = create_response.data["id"]

        response = client.delete(reverse('crisis-detail', args=[crisis_id]))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert Crisis.objects.filter(id=crisis_id).exists()

    def test_admin_can_delete_crisis(self, local_authority_client, admin_client):
        loc_client, _ = local_authority_client
        create_response = loc_client.post(reverse('crisis-list'), CRISIS_PAYLOAD, format='json')
        crisis_id = create_response.data["id"]

        admin, _ = admin_client
        response = admin.delete(reverse('crisis-detail', args=[crisis_id]))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not Crisis.objects.filter(id=crisis_id).exists()


@pytest.mark.django_db
class TestImplicationInstitution:

    def test_declare_implique(self, local_authority_client, institution):
        client, user = local_authority_client
        crisis = Crisis.objects.create(**{**CRISIS_PAYLOAD, "location": "POINT (5.7245 45.1885)"})

        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(institution.id), "type_implication": "IMPLIQUE"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        implication = ImplicationInstitution.objects.get(id=response.data["id"])
        assert implication.utilisateur == user
        assert implication.type_implication == TypeImplication.IMPLIQUE

    def test_cannot_declare_for_a_foreign_institution(self, local_authority_client):
        client, _ = local_authority_client
        other_type = InstitutionType.objects.create(code="SDIS", libelle="SDIS")
        other_institution = Institution.objects.create(nom="SDIS Autre", type=other_type)
        crisis = Crisis.objects.create(**CRISIS_PAYLOAD)

        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(other_institution.id), "type_implication": "IMPLIQUE"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not ImplicationInstitution.objects.exists()

    def test_implique_and_acteur_can_coexist(self, local_authority_client, institution):
        client, user = local_authority_client
        crisis = Crisis.objects.create(**CRISIS_PAYLOAD)

        client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(institution.id), "type_implication": "IMPLIQUE"},
            format='json',
        )
        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(institution.id), "type_implication": "ACTEUR"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert ImplicationInstitution.objects.filter(crise=crisis, institution=institution).count() == 2

    def test_only_declarant_or_admin_can_retract(self, local_authority_client, institution, admin_client):
        client, user = local_authority_client
        crisis = Crisis.objects.create(**CRISIS_PAYLOAD)
        implication = ImplicationInstitution.objects.create(
            crise=crisis, institution=institution, utilisateur=user, type_implication=TypeImplication.IMPLIQUE
        )

        admin, _ = admin_client
        response = admin.delete(reverse('implicationinstitution-detail', args=[implication.id]))
        assert response.status_code == status.HTTP_204_NO_CONTENT


@pytest.mark.django_db
class TestImplicationThemesEtResponsable:

    def test_declare_acteur_with_existing_responsable_promotes_type(self, local_authority_client, institution, create_user):
        client, _ = local_authority_client
        crisis = Crisis.objects.create(**CRISIS_PAYLOAD)
        besoin = Besoin.objects.create(nom="Hébergement (test)")
        responsable = create_user(
            username="future-regulateur@test.fr", email="future-regulateur@test.fr", type="UTIL_SIMPLE"
        )
        ContactInstitution.objects.create(institution=institution, utilisateur=responsable, actif=True)

        response = client.post(
            reverse('implicationinstitution-list'),
            {
                "crise": str(crisis.id),
                "institution": str(institution.id),
                "type_implication": "ACTEUR",
                "themes": [str(besoin.id)],
                "responsable": str(responsable.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        implication = ImplicationInstitution.objects.get(id=response.data["id"])
        assert implication.responsable == responsable
        assert list(implication.themes.all()) == [besoin]
        assert response.data["themes_libelles"] == ["Hébergement (test)"]

        responsable.refresh_from_db()
        assert responsable.type == UserRole.REGULATEUR

    def test_declare_acteur_with_responsable_email_invites_new_user(self, local_authority_client, institution):
        client, _ = local_authority_client
        crisis = Crisis.objects.create(**CRISIS_PAYLOAD)

        response = client.post(
            reverse('implicationinstitution-list'),
            {
                "crise": str(crisis.id),
                "institution": str(institution.id),
                "type_implication": "ACTEUR",
                "responsable_email": "nouveau-regulateur@test.fr",
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        invited = User.objects.get(email="nouveau-regulateur@test.fr")
        assert invited.type == UserRole.REGULATEUR
        assert invited.is_active is False
        assert invited.enabled is False
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=invited, actif=True).exists()

        implication = ImplicationInstitution.objects.get(id=response.data["id"])
        assert implication.responsable == invited

        assert len(mail.outbox) == 1
        assert invited.email in mail.outbox[0].to

    def test_designating_a_non_contact_as_responsable_attaches_and_promotes_them(
        self, local_authority_client, institution, create_user
    ):
        """Désigner un utilisateur existant comme responsable en fait de facto un contact de
        l'institution, même s'il n'en était pas encore membre (ex: admin désignant quelqu'un
        pour une institution à laquelle il n'appartient pas lui-même)."""
        client, _ = local_authority_client
        crisis = Crisis.objects.create(**CRISIS_PAYLOAD)
        outsider = create_user(username="outsider@test.fr", email="outsider@test.fr", type="UTIL_SIMPLE")

        response = client.post(
            reverse('implicationinstitution-list'),
            {
                "crise": str(crisis.id),
                "institution": str(institution.id),
                "type_implication": "ACTEUR",
                "responsable": str(outsider.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        implication = ImplicationInstitution.objects.get(id=response.data["id"])
        assert implication.responsable == outsider
        assert ContactInstitution.objects.filter(institution=institution, utilisateur=outsider, actif=True).exists()
        outsider.refresh_from_db()
        assert outsider.type == UserRole.REGULATEUR

    def test_admin_can_declare_implication_for_a_foreign_institution(self, admin_client, institution):
        """Un ADMIN (contrairement à un acteur institutionnel classique) peut déclarer
        l'implication de n'importe quelle institution, pas seulement la sienne."""
        client, _ = admin_client
        crisis = Crisis.objects.create(**CRISIS_PAYLOAD)

        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(institution.id), "type_implication": "ACTEUR"},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestPointOperationnelActeur:

    def test_creating_point_sets_responsable_and_declares_acteur(self, local_authority_client, institution):
        client, user = local_authority_client
        crisis = Crisis.objects.create(**CRISIS_PAYLOAD)
        point_type = PointType.objects.create(code="COLLECTE_TEST", libelle="Point de collecte (test)")

        response = client.post(
            reverse('pointoperationnel-list'),
            {
                "nom": "Collecte gymnase municipal",
                "type": str(point_type.id),
                "crise": str(crisis.id),
                "adresse": "1 rue de la Mairie",
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        point = PointOperationnel.objects.get(id=response.data["id"])
        assert point.responsable == user

        assert ImplicationInstitution.objects.filter(
            crise=crisis, institution=institution, type_implication=TypeImplication.ACTEUR
        ).exists()

    def test_admin_can_declare_point_for_a_chosen_institution(self, admin_client, institution):
        """Un admin n'a pas de rattachement personnel à une institution : l'institution doit être
        prise depuis le champ explicite du payload, pas devinée depuis ses propres contacts."""
        client, admin = admin_client
        crisis = Crisis.objects.create(**CRISIS_PAYLOAD)
        point_type = PointType.objects.create(code="COLLECTE_TEST2", libelle="Point de collecte (test 2)")

        response = client.post(
            reverse('pointoperationnel-list'),
            {
                "nom": "Collecte gymnase municipal",
                "type": str(point_type.id),
                "crise": str(crisis.id),
                "institution": str(institution.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert ImplicationInstitution.objects.filter(
            crise=crisis, institution=institution, type_implication=TypeImplication.ACTEUR
        ).exists()

    def test_simple_user_cannot_create_point(self, authenticated_client):
        client, _ = authenticated_client
        point_type = PointType.objects.create(code="COLLECTE_TEST", libelle="Point de collecte (test)")
        response = client.post(
            reverse('pointoperationnel-list'),
            {"nom": "Point test", "type": str(point_type.id)},
            format='json',
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
