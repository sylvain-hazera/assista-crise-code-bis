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
        crisis = _make_crisis()
        response = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dupont', 'prenom_referent': 'Jean',
                'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
                'crise': str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['declare_par'] is None
        assert response.data['registre_presence'] is None

    def test_anonymous_can_declare_famille_with_headcount(self, api_client):
        crisis = _make_crisis()
        response = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'FAMILLE', 'nom_referent': 'Martin', 'prenom_referent': 'Alice',
                'contact_referent': '0600000000', 'nombre_adultes': 2, 'nombre_enfants': 3,
                'crise': str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['nombre_adultes'] == 2
        assert response.data['nombre_enfants'] == 3

    def test_ages_enfants_is_saved_as_simple_age_list(self, api_client):
        """Pas de nom, pas d'identité — juste les âges, voir DeclarationSecurite.ages_enfants."""
        crisis = _make_crisis()
        response = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'FAMILLE', 'nom_referent': 'Martin', 'prenom_referent': 'Alice',
                'contact_referent': '0600000000', 'nombre_adultes': 2, 'nombre_enfants': 3,
                'ages_enfants': [12, 7, 3], 'crise': str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['ages_enfants'] == [12, 7, 3]
        declaration = DeclarationSecurite.objects.get(id=response.data['id'])
        assert declaration.ages_enfants == [12, 7, 3]

    def test_ages_enfants_defaults_to_empty_list(self, api_client):
        crisis = _make_crisis()
        response = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dupont', 'prenom_referent': 'Jean',
                'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
                'crise': str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['ages_enfants'] == []

    def test_missing_crise_rejected(self, api_client):
        response = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dupont', 'prenom_referent': 'Jean',
                'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
            },
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_anonymous_can_declare_entry_at_a_centre(self, api_client):
        """Une personne peut se déclarer elle-même "arrivée" dans un centre d'accueil (ex:
        depuis son téléphone une fois sur place), sans avoir besoin d'être un membre de
        l'équipe du centre — ça crée aussi la ligne RegistrePresence associée, comme pour un
        recensement fait par un opérateur."""
        crisis = _make_crisis()
        point = _make_point()

        response = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dupont', 'prenom_referent': 'Jean',
                'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
                'centre_accueil': str(point.id), 'crise': str(crisis.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['declare_par'] is None
        assert response.data['registre_presence'] is not None
        registre = RegistrePresence.objects.get(id=response.data['registre_presence'])
        assert registre.point_id == point.id
        assert registre.enregistre_par is None


@pytest.mark.django_db
class TestDeclarationSecuriteOperateurCentre:
    """Recensement à l'entrée d'un centre d'accueil par un opérateur authentifié (secrétariat) :
    crée aussi une ligne RegistrePresence pour que le secrétariat existant reste cohérent, avec
    enregistre_par posé (contrairement à l'auto-déclaration anonyme, voir
    TestDeclarationSecuritePublicSelfDeclare.test_anonymous_can_declare_entry_at_a_centre)."""

    def test_admin_can_declare_entry_and_registre_presence_is_created(self, authenticated_client):
        client, admin = _make_admin(authenticated_client)
        point = _make_point()
        crisis = _make_crisis()

        response = client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'GROUPE', 'nom_referent': 'Leroy', 'prenom_referent': 'Sophie',
                'contact_referent': 'sophie@test.fr', 'nombre_adultes': 4, 'nombre_enfants': 6,
                'centre_accueil': str(point.id), 'crise': str(crisis.id),
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

    def test_crise_deduced_from_centre_when_omitted(self, authenticated_client):
        """Le secrétariat d'un centre (PointSecretariatModalComponent côté frontend) n'envoie
        jamais `crise` dans son payload — seulement `centre_accueil` — contrairement au
        formulaire public "je suis en sécurité" qui la fait choisir explicitement. Sans
        déduction serveur, la création échouait systématiquement en 400 pour ce cas d'usage
        (reproduit puis corrigé, voir DeclarationSecuriteViewSet.perform_create)."""
        client, _ = _make_admin(authenticated_client)
        crisis = _make_crisis()
        point = _make_point(crise=crisis)

        response = client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Sans', 'prenom_referent': 'Crise',
                'contact_referent': 'sanscrise@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
                'centre_accueil': str(point.id),
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        declaration = DeclarationSecurite.objects.get(id=response.data['id'])
        assert declaration.crise_id == crisis.id

    def test_missing_crise_and_centre_rejected(self, authenticated_client):
        """Sans centre pour la déduire, `crise` reste obligatoire (auto-déclaration générique
        côté formulaire public, ou saisie secrétariat mal formée)."""
        client, _ = _make_admin(authenticated_client)

        response = client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Rejete', 'prenom_referent': 'X',
                'contact_referent': 'rejete@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
            },
            format='json',
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_regime_alimentaire_flag_is_relayed_as_warning_on_registre(self, authenticated_client):
        client, _ = _make_admin(authenticated_client)
        point = _make_point()
        crisis = _make_crisis()

        response = client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'FAMILLE', 'nom_referent': 'Petit', 'prenom_referent': 'Marc',
                'contact_referent': 'marc@test.fr', 'nombre_adultes': 2, 'nombre_enfants': 1,
                'centre_accueil': str(point.id), 'regime_alimentaire_specifique': True,
                'crise': str(crisis.id),
            },
            format='json',
        )

        registre = RegistrePresence.objects.get(id=response.data['registre_presence'])
        assert 'régime alimentaire' in registre.commentaire.lower()


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
        crisis = _make_crisis()

        client.post(reverse('declarationsecurite-list'), {
            'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dedans', 'prenom_referent': 'A',
            'contact_referent': 'a@t.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
            'centre_accueil': str(point_in.id), 'crise': str(crisis.id),
        }, format='json')
        client.post(reverse('declarationsecurite-list'), {
            'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dehors', 'prenom_referent': 'B',
            'contact_referent': 'b@t.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
            'centre_accueil': str(point_out.id), 'crise': str(crisis.id),
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


@pytest.mark.django_db
class TestDeclarationSecuriteListZoneScoping:
    """Hors zone = exclusion totale sur la liste par défaut (pas de résumé, contrairement à
    Request) — voir DeclarationSecuriteViewSet.get_queryset. Ne s'applique ni à vue_mairie
    (filtrage par géocodage inverse, voir TestDeclarationSecuriteVueMairie) ni à
    retrieve/update/destroy (doivent rester visibles pour IsOwnDeclarationOrInstitutional, voir
    TestUpdateOwnDeclaration)."""

    def _make_mairie_user(self, commune_code):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_DS_ZONE", defaults={"libelle": "Mairie"})
        institution = Institution.objects.create(
            nom=f"Mairie DS Zone {commune_code}", type=itype, commune_code=commune_code,
        )
        return User.objects.create_user(
            username=f"mairie-ds-zone-{commune_code}@test.fr", email=f"mairie-ds-zone-{commune_code}@test.fr",
            password="Test1234!", type="AUT_LOCALE", institution=institution,
        )

    def test_list_excludes_declarations_outside_zone(self, authenticated_client):
        client, _ = authenticated_client
        crisis = _make_crisis()
        declaration_in = DeclarationSecurite.objects.create(
            crise=crisis, nom_referent="Dedans", prenom_referent="A", contact_referent="a@t.fr",
            commune_code="38185", epci_code="200040715", departement_code="38", region_code="84",
        )
        declaration_out = DeclarationSecurite.objects.create(
            crise=crisis, nom_referent="Dehors", prenom_referent="B", contact_referent="b@t.fr",
            commune_code="75056", epci_code="200054781", departement_code="75", region_code="11",
        )

        mairie_user = self._make_mairie_user("38185")
        client.force_authenticate(user=mairie_user)

        response = client.get(reverse('declarationsecurite-list'))

        assert response.status_code == status.HTTP_200_OK
        noms = {d['nom_referent'] for d in response.data}
        assert 'Dedans' in noms
        assert 'Dehors' not in noms


@pytest.mark.django_db
class TestMesDeclarations:
    """Un utilisateur connecté doit pouvoir retrouver ses propres déclarations, même sans
    droits institutionnels — contrairement à la liste générale (réservée, voir
    TestDeclarationSecuriteListPermissions) ou à vue_mairie (réservée + filtrée commune)."""

    def test_simple_user_sees_only_their_own_declarations(self, authenticated_client):
        client, user = authenticated_client
        other = User.objects.create_user(username='autre@test.fr', email='autre@test.fr', password='Test1234!')

        crisis = _make_crisis()
        api = client
        api.force_authenticate(user=user)
        r1 = api.post(reverse('declarationsecurite-list'), {
            'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Moi', 'prenom_referent': 'A',
            'contact_referent': 'a@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0, 'situation': 'RELOGE',
            'crise': str(crisis.id),
        }, format='json')
        assert r1.status_code == status.HTTP_201_CREATED

        api.force_authenticate(user=other)
        api.post(reverse('declarationsecurite-list'), {
            'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Autrui', 'prenom_referent': 'B',
            'contact_referent': 'b@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0, 'situation': 'RELOGE',
            'crise': str(crisis.id),
        }, format='json')

        api.force_authenticate(user=user)
        response = api.get(reverse('declarationsecurite-mes-declarations'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['nom_referent'] == 'Moi'

    def test_requires_authentication(self, api_client):
        response = api_client.get(reverse('declarationsecurite-mes-declarations'))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
class TestUpdateOwnDeclaration:
    """L'auteur d'une déclaration peut faire évoluer sa situation (arrivée/départ d'un centre
    d'accueil, relogement...) — le registre de présence du centre doit rester synchronisé,
    comme s'il s'agissait d'un opérateur du secrétariat."""

    def _declare(self, client, user, **overrides):
        payload = {
            'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Test', 'prenom_referent': 'Jean',
            'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
            'situation': 'HORS_ZONE', 'crise': str(_make_crisis().id),
        }
        payload.update(overrides)
        client.force_authenticate(user=user)
        response = client.post(reverse('declarationsecurite-list'), payload, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        return response.data

    def test_owner_arriving_at_a_centre_creates_registre_presence(self, authenticated_client):
        client, user = authenticated_client
        point = _make_point()
        declaration = self._declare(client, user)
        assert declaration['registre_presence'] is None

        response = client.patch(
            reverse('declarationsecurite-detail', kwargs={'pk': declaration['id']}),
            {'situation': 'EN_CENTRE', 'centre_accueil': str(point.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data['registre_presence'] is not None
        registre = RegistrePresence.objects.get(id=response.data['registre_presence'])
        assert registre.point_id == point.id
        assert registre.date_depart is None

    def test_owner_leaving_a_centre_sets_date_depart_on_registre(self, authenticated_client):
        client, user = authenticated_client
        point = _make_point()
        declaration = self._declare(client, user, situation='EN_CENTRE', centre_accueil=str(point.id))
        registre_id = declaration['registre_presence']
        assert registre_id is not None

        response = client.patch(
            reverse('declarationsecurite-detail', kwargs={'pk': declaration['id']}),
            {'situation': 'RELOGE', 'centre_accueil': None},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        registre = RegistrePresence.objects.get(id=registre_id)
        assert registre.date_depart is not None

    def test_owner_cannot_update_someone_elses_declaration(self, authenticated_client):
        client, user = authenticated_client
        other = User.objects.create_user(username='autre2@test.fr', email='autre2@test.fr', password='Test1234!')
        declaration = self._declare(client, other)

        client.force_authenticate(user=user)
        response = client.patch(
            reverse('declarationsecurite-detail', kwargs={'pk': declaration['id']}),
            {'situation': 'RELOGE'},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_institutional_actor_can_update_any_declaration(self, authenticated_client):
        client, user = authenticated_client
        declaration = self._declare(client, user)

        admin = User.objects.create_user(
            username='admin2@test.fr', email='admin2@test.fr', password='Test1234!', type='ADMIN',
        )
        client.force_authenticate(user=admin)
        response = client.patch(
            reverse('declarationsecurite-detail', kwargs={'pk': declaration['id']}),
            {'situation': 'RELOGE'},
            format='json',
        )

        assert response.status_code == status.HTTP_200_OK

    def test_anonymous_cannot_update(self, authenticated_client):
        client, user = authenticated_client
        declaration = self._declare(client, user)
        client.force_authenticate(user=None)

        response = client.patch(
            reverse('declarationsecurite-detail', kwargs={'pk': declaration['id']}),
            {'situation': 'RELOGE'},
            format='json',
        )

        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_owner_can_delete_own_declaration(self, authenticated_client):
        client, user = authenticated_client
        declaration = self._declare(client, user)

        response = client.delete(reverse('declarationsecurite-detail', kwargs={'pk': declaration['id']}))

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not DeclarationSecurite.objects.filter(id=declaration['id']).exists()

    def test_owner_cannot_delete_someone_elses_declaration(self, authenticated_client):
        client, user = authenticated_client
        other = User.objects.create_user(username='autre3@test.fr', email='autre3@test.fr', password='Test1234!')
        declaration = self._declare(client, other)

        client.force_authenticate(user=user)
        response = client.delete(reverse('declarationsecurite-detail', kwargs={'pk': declaration['id']}))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert DeclarationSecurite.objects.filter(id=declaration['id']).exists()


@pytest.mark.django_db
class TestCentresAccueilPublic:
    """Endpoint public (formulaire "je suis en sécurité") listant les centres d'accueil
    (PointType HEBERGEMENT) actifs d'une crise, à champs restreints."""

    def _make_centre(self, crisis, **kwargs):
        heb_type, _ = PointType.objects.get_or_create(
            code='HEBERGEMENT', defaults={'libelle': "Centre d'accueil des personnes"},
        )
        defaults = {'nom': 'Centre', 'type': heb_type, 'crise': crisis, 'actif': True}
        defaults.update(kwargs)
        return PointOperationnel.objects.create(**defaults)

    def test_requires_crise_param(self, api_client):
        response = api_client.get(reverse('pointoperationnel-centres-accueil'))
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_anonymous_can_list_centres_for_a_crisis(self, api_client):
        crisis = _make_crisis()
        centre = self._make_centre(crisis, capacite_accueil=30)

        response = api_client.get(reverse('pointoperationnel-centres-accueil'), {'crise': str(crisis.id)})

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1
        assert response.data[0]['id'] == str(centre.id)
        assert response.data[0]['capacite_accueil'] == 30
        assert response.data[0]['personnes_presentes'] == 0
        # Champs internes de PointOperationnelSerializer volontairement absents de la version publique
        assert 'commentaire' not in response.data[0]
        assert 'responsable' not in response.data[0]

    def test_excludes_non_hebergement_points(self, api_client):
        crisis = _make_crisis()
        other_type, _ = PointType.objects.get_or_create(code='COLLECTE', defaults={'libelle': 'Point de collecte'})
        PointOperationnel.objects.create(nom='Point collecte', type=other_type, crise=crisis, actif=True)

        response = api_client.get(reverse('pointoperationnel-centres-accueil'), {'crise': str(crisis.id)})

        assert response.status_code == status.HTTP_200_OK
        assert response.data == []

    def test_excludes_inactive_centres(self, api_client):
        crisis = _make_crisis()
        self._make_centre(crisis, actif=False)

        response = api_client.get(reverse('pointoperationnel-centres-accueil'), {'crise': str(crisis.id)})

        assert response.data == []


@pytest.mark.django_db
class TestDeclarationSecuriteAdresse:
    """Adresse optionnelle (latitude/longitude/location) — même régime de confidentialité que
    Information : jamais visible au grand public, seulement aux acteurs institutionnels."""

    def test_location_accepted_and_hidden_from_public(self, api_client):
        crisis = _make_crisis()
        response = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dupont', 'prenom_referent': 'Jean',
                'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
                'crise': str(crisis.id),
                'location': '{"type": "Point", "coordinates": [5.72, 45.18]}',
                'commune_code': '38185',
            },
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['latitude'] is None
        assert response.data['longitude'] is None
        declaration = DeclarationSecurite.objects.get(id=response.data['id'])
        assert declaration.location is not None
        assert declaration.commune_code == '38185'

    def test_location_visible_to_institutional_actor(self, api_client, authenticated_client):
        crisis = _make_crisis()
        creation = api_client.post(
            reverse('declarationsecurite-list'),
            {
                'type_declarant': 'PERSONNE_SEULE', 'nom_referent': 'Dupont', 'prenom_referent': 'Jean',
                'contact_referent': 'jean@test.fr', 'nombre_adultes': 1, 'nombre_enfants': 0,
                'crise': str(crisis.id),
                'location': '{"type": "Point", "coordinates": [5.72, 45.18]}',
            },
            format='json',
        )

        client, _ = _make_admin(authenticated_client)
        response = client.get(reverse('declarationsecurite-detail', kwargs={'pk': creation.data['id']}))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['latitude'] == pytest.approx(45.18)
        assert response.data['longitude'] == pytest.approx(5.72)
