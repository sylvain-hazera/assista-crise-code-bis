import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status

from core.models import (
    Crisis,
    Information,
    InformationType,
    Institution,
    InstitutionDomaine,
    InstitutionType,
    Request,
    RequestType,
    User,
)


def _activation_url(user):
    from django.utils.encoding import force_bytes
    from django.utils.http import urlsafe_base64_encode
    from core.views import MAGIC_LINK_SIGNER
    uidb64 = urlsafe_base64_encode(force_bytes(str(user.pk)))
    token = MAGIC_LINK_SIGNER.sign(uidb64)
    return reverse('activate_account', args=[uidb64, token])


def _make_crisis(**kwargs):
    defaults = {'name': 'Crise test', 'location': Point(1.0, 1.0, srid=4326)}
    defaults.update(kwargs)
    return Crisis.objects.create(**defaults)


def _make_admin(authenticated_client):
    client, admin = authenticated_client
    admin.type = 'ADMIN'
    admin.save()
    return client, admin


@pytest.mark.django_db
class TestInstitutionCommuneAttachment:
    """Institution.commune_code/commune_nom doivent être renseignés à l'activation d'un compte
    AUT_LOCALE, à partir des informations déclarées à l'inscription (user.pending_commune_*) —
    avant, ces champs étaient toujours vides une fois l'inscription nettoyée."""

    def test_activation_persists_commune_on_institution(self, api_client, user_data):
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        institution = Institution.objects.create(nom="Mairie de Testville", type=institution_type)
        InstitutionDomaine.objects.create(institution=institution, domaine="testville.fr", valide=True)

        payload = {
            **user_data,
            "email": "agent@testville.fr",
            "username": "agent@testville.fr",
            "type": "AUT_LOCALE",
            "institution_name": "Mairie de Testville",
            "institution_type": "mairie",
            "commune_name": "Testville",
            "commune_code": "38999",
        }
        register_response = api_client.post(reverse('user-register'), payload, format='json')
        assert register_response.status_code == status.HTTP_201_CREATED

        user = User.objects.get(id=register_response.data["user"]["id"])
        activation_response = api_client.get(_activation_url(user))
        assert activation_response.status_code == status.HTTP_200_OK

        institution.refresh_from_db()
        assert institution.commune_code == "38999"
        assert institution.commune_nom == "Testville"

    def test_activation_backfills_commune_on_preexisting_institution(self, api_client, user_data):
        """Une institution créée avant l'ajout de ces champs (ou par un premier membre sans
        commune déclarée) doit être complétée par le rattachement suivant, pas ignorée."""
        institution_type = InstitutionType.objects.create(code="MAIRIE", libelle="Mairie")
        institution = Institution.objects.create(nom="Mairie de Vieuxville", type=institution_type)
        InstitutionDomaine.objects.create(institution=institution, domaine="vieuxville.fr", valide=True)
        assert institution.commune_code is None

        payload = {
            **user_data,
            "email": "agent@vieuxville.fr",
            "username": "agent@vieuxville.fr",
            "type": "AUT_LOCALE",
            "institution_name": "Mairie de Vieuxville",
            "institution_type": "mairie",
            "commune_name": "Vieuxville",
            "commune_code": "38111",
        }
        register_response = api_client.post(reverse('user-register'), payload, format='json')
        user = User.objects.get(id=register_response.data["user"]["id"])
        api_client.get(_activation_url(user))

        institution.refresh_from_db()
        assert institution.commune_code == "38111"


@pytest.mark.django_db
class TestVueMairieEndpoints:
    """GET /api/demandes/vue_mairie/ et /api/informations/vue_mairie/ : filtrage par la
    commune de l'institution de l'utilisateur appelant."""

    def _make_mairie_user(self, commune_code="38185"):
        itype = InstitutionType.objects.create(code="MAIRIE2", libelle="Mairie")
        institution = Institution.objects.create(
            nom="Mairie Vue Test", type=itype, commune_code=commune_code, commune_nom="Grenoble",
        )
        user = User.objects.create_user(
            username="mairie@vuetest.fr", email="mairie@vuetest.fr", password="Test1234!",
            type="AUT_LOCALE", institution=institution,
        )
        return user

    def test_vue_mairie_filters_requests_by_commune(self, api_client, request_type):
        user = self._make_mairie_user()
        api_client.force_authenticate(user=user)
        crisis = _make_crisis()
        Request.objects.create(
            title="Dans la commune", location=Point(1, 1, srid=4326),
            first_name_request="A", last_name_request="B", email_request="a@t.fr",
            phone_request="0600000000", crisis=crisis, deletion_token="tok-in",
            request_type=request_type, commune_code="38185",
        )
        Request.objects.create(
            title="Hors commune", location=Point(1, 1, srid=4326),
            first_name_request="C", last_name_request="D", email_request="c@t.fr",
            phone_request="0600000000", crisis=crisis, deletion_token="tok-out",
            request_type=request_type, commune_code="75056",
        )

        response = api_client.get(reverse('request-vue-mairie'))

        assert response.status_code == status.HTTP_200_OK
        titles = [r['title'] for r in response.data]
        assert titles == ["Dans la commune"]

    def test_vue_mairie_filters_informations_by_commune(self, api_client, information_type):
        user = self._make_mairie_user()
        api_client.force_authenticate(user=user)
        Information.objects.create(
            title="Signalement local", location=Point(1, 1, srid=4326),
            first_name_information="A", last_name_information="B", email_information="a@t.fr",
            phone_information="0600000000", information_type=information_type,
            deletion_token="tok-info-in", commune_code="38185",
        )
        Information.objects.create(
            title="Signalement ailleurs", location=Point(1, 1, srid=4326),
            first_name_information="C", last_name_information="D", email_information="c@t.fr",
            phone_information="0600000000", information_type=information_type,
            deletion_token="tok-info-out", commune_code="75056",
        )

        response = api_client.get(reverse('information-vue-mairie'))

        assert response.status_code == status.HTTP_200_OK
        titles = [r['title'] for r in response.data]
        assert titles == ["Signalement local"]

    def test_vue_mairie_requires_institution_with_commune(self, authenticated_client):
        client, user = authenticated_client
        user.type = 'SECOURS'
        user.save()

        response = client.get(reverse('request-vue-mairie'))

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_vue_mairie_requires_authentication(self, api_client):
        response = api_client.get(reverse('request-vue-mairie'))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)
