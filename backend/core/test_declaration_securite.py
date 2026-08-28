from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework import status

from core.models import (
    Crisis,
    DeclarationSecurite,
    Institution,
    InstitutionType,
    PointOperationnel,
    PointType,
    RegistrePresence,
    Team,
    User,
)


def _make_crisis(**kwargs):
    defaults = {'name': 'Crise test', 'location': Point(1.0, 1.0, srid=4326)}
    defaults.update(kwargs)
    return Crisis.objects.create(**defaults)


def _make_point(**kwargs):
    ptype, _ = PointType.objects.get_or_create(code='ACCUEIL_TEST', defaults={'libelle': 'Accueil'})
    defaults = {'nom': 'Centre test', 'type': ptype}
    defaults.update(kwargs)
    return PointOperationnel.objects.create(**defaults)


def _make_admin(authenticated_client):
    client, admin = authenticated_client
    admin.type = 'ADMIN'
    admin.save()
    return client, admin


@pytest.mark.django_db
class TestDeclarationSecuritePublicSelfDeclare:
    """Auto-déclaration publique : ouverte à tous, sans centre d'accueil."""

    def test_anonymous_can_self_declare_without_centre(self, api_client):
        response = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dupont', 'prenom_referent': 'Jean',
                'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['declare_par'] is None
        assert response.data['registre_presence'] is None

    def test_anonymous_can_declare_famille_with_headcount(self, api_client):
        response = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'FAMILLE', 'nom_referent': 'Martin', 'prenom_referent': 'Alice',
                'contact_referent': '0600000000', 'nombre_adultes': 2, 'nombre_enfants': 3,
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['nombre_adultes'] == 2
        assert response.data['nombre_enfants'] == 3

    def test_anonymous_cannot_set_centre_accueil(self, api_client):
        """Une entrée en centre d'accueil n'est jamais une auto-déclaration anonyme — c'est
        forcément un recensement fait par l'équipe du centre."""
        point = _make_point()

        response = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dupont', 'prenom_referent': 'Jean',
                'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
                'centre_accueil': str(point.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert not DeclarationSecurite.objects.filter(nom_referent='Dupont').exists()

    def test_authenticated_but_unrelated_user_cannot_set_centre_accueil(self, authenticated_client):
        """Un simple compte authentifié sans lien avec le centre reste refusé — pas juste
        l'anonymat qui bloque, l'appartenance à l'équipe/la responsabilité du centre."""
        client, _ = authenticated_client
        point = _make_point()

        response = client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dupont', 'prenom_referent': 'Jean',
                'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
                'centre_accueil': str(point.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestDeclarationSecuriteOperateurCentre:
    """Recensement à l'entrée d'un centre d'accueil : réservé à l'équipe du centre / un admin,
    crée aussi une ligne RegistrePresence pour que le secrétariat existant reste cohérent."""

    def test_admin_can_declare_entry_and_registre_presence_is_created(self, authenticated_client):
        client, admin = _make_admin(authenticated_client)
        point = _make_point()

        response = client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'GROUPE', 'nom_referent': 'Leroy', 'prenom_referent': 'Sophie',
                'contact_referent': 'sophie@test.fr', 'nombre_adultes': 4, 'nombre_enfants': 6,
                'centre_accueil': str(point.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['declare_par'] == admin.id
        registre_id = response.data['registre_presence']
        assert registre_id is not None

        registre = RegistrePresence.objects.get(id=registre_id)
        assert registre.point_id == point.id
        assert registre.nombre == 10  # 4 adultes + 6 enfants
        assert registre.nom == "Sophie Leroy"

    def test_regime_alimentaire_flag_is_relayed_as_warning_on_registre(self, authenticated_client):
        client, _ = _make_admin(authenticated_client)
        point = _make_point()

        response = client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'FAMILLE', 'nom_referent': 'Petit', 'prenom_referent': 'Marc',
                'contact_referent': 'marc@test.fr', 'nombre_adultes': 2, 'nombre_enfants': 1,
                'centre_accueil': str(point.id), 'regime_alimentaire_specifique': True,
            },
            format='json',
        )

        registre = RegistrePresence.objects.get(id=response.data['registre_presence'])
        assert 'régime alimentaire' in registre.commentaire.lower()

    def test_team_member_of_point_can_declare_entry(self, authenticated_client):
        client, user = authenticated_client
        team = Team.objects.create(name='Equipe centre')
        team.members.add(user)
        point = _make_point(equipe=team)

        response = client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dupont', 'prenom_referent': 'Jean',
                'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
                'centre_accueil': str(point.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED


@pytest.mark.django_db
class TestDeclarationSecuriteVueMairie:
    """Filtrage par commune de l'institution de l'utilisateur appelant — via reverse-géocodage
    du centre d'accueil (mocké ici, pas d'appel réseau réel dans les tests)."""

    def _make_mairie_user(self, commune_code="38185"):
        itype = InstitutionType.objects.create(code="MAIRIE_DS", libelle="Mairie")
        institution = Institution.objects.create(
            nom="Mairie DS Test", type=itype, commune_code=commune_code, commune_nom="Grenoble",
        )
        return User.objects.create_user(
            username="mairie-ds@test.fr", email="mairie-ds@test.fr", password="Test1234!",
            type="AUT_LOCALE", institution=institution,
        )

    @patch("core.views.commune_code_from_point")
    def test_filters_by_centre_commune(self, mock_geocode, authenticated_client):
        client, admin = _make_admin(authenticated_client)
        point_in = _make_point(nom="Centre dans la commune", location=Point(1, 1, srid=4326))
        point_out = _make_point(nom="Centre hors commune", location=Point(2, 2, srid=4326))
        mock_geocode.side_effect = lambda p: "38185" if p.x == 1 else "75056"

        client.post(reverse('declarationsecurite-list'), {
            'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dedans', 'prenom_referent': 'A',
            'contact_referent': 'a@t.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
            'centre_accueil': str(point_in.id),
        }, format='json')
        client.post(reverse('declarationsecurite-list'), {
            'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dehors', 'prenom_referent': 'B',
            'contact_referent': 'b@t.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
            'centre_accueil': str(point_out.id),
        }, format='json')

        mairie_user = self._make_mairie_user()
        client.force_authenticate(user=mairie_user)

        response = client.get(reverse('declarationsecurite-vue-mairie'))

        assert response.status_code == status.HTTP_200_OK
        noms = [d['nom_referent'] for d in response.data]
        assert noms == ['Dedans']

    def test_requires_institution_with_commune(self, authenticated_client):
        client, user = authenticated_client
        user.type = 'SECOURS'
        user.save()

        response = client.get(reverse('declarationsecurite-vue-mairie'))

        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestDeclarationSecuriteListPermissions:
    """Ce sont des coordonnées personnelles : la liste ne doit jamais être publique."""

    def test_anonymous_cannot_list(self, api_client):
        response = api_client.get(reverse('declarationsecurite-list'))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_simple_user_cannot_list(self, authenticated_client):
        client, _ = authenticated_client
        response = client.get(reverse('declarationsecurite-list'))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_institutional_actor_can_list(self, authenticated_client):
        client, _ = _make_admin(authenticated_client)
        response = client.get(reverse('declarationsecurite-list'))
        assert response.status_code == status.HTTP_200_OK
