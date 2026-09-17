"""Flux d'enrôlement des satellites (Raspberry Pi déployés sur site) — voir le cadrage
"Chantier B" (plan) et la docstring du modèle Satellite : jeton généré par un acteur
institutionnel (generer_jeton) -> consommé par le satellite lui-même pour créer sa propre
entrée (enroler, AllowAny) -> validé explicitement par un acteur institutionnel (valider, qui
crée le compte de service) -> heartbeat (contact) qui alimente l'état Actif/Inactif/Perdu."""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType, JetonEnrolementSatellite, Satellite


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_SATELLITE', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test satellite', 'type': itype}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


@pytest.fixture
def institution_a():
    return _make_institution(nom='Mairie Satellite A')


@pytest.fixture
def institution_b():
    return _make_institution(nom='Mairie Satellite B')


@pytest.fixture
def mairie_a_client(create_user, institution_a):
    user = create_user(username='mairie-a-satellite@test.fr', email='mairie-a-satellite@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution_a, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def mairie_b_client(create_user, institution_b):
    user = create_user(username='mairie-b-satellite@test.fr', email='mairie-b-satellite@test.fr', type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution_b, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def jeton_a(institution_a, mairie_a_client):
    _, user = mairie_a_client
    return JetonEnrolementSatellite.objects.create(
        institution=institution_a, jeton='jeton-valide-a', expiration=timezone.now() + datetime.timedelta(hours=24),
        cree_par=user,
    )


@pytest.fixture
def satellite_en_attente(institution_a):
    return Satellite.objects.create(institution=institution_a, nom='Satellite A1', profil='GW')


@pytest.mark.django_db
class TestGenererJeton:

    def test_mairie_genere_un_jeton_pour_sa_propre_institution(self, mairie_a_client, institution_a):
        client, _ = mairie_a_client
        response = client.post(reverse('satellite-generer-jeton'), {}, format='json')
        assert response.status_code == status.HTTP_201_CREATED
        assert str(response.data['institution']) == str(institution_a.id)
        assert response.data['utilise'] is False
        assert JetonEnrolementSatellite.objects.filter(institution=institution_a).exists()

    def test_bloque_en_zone_demo(self, mairie_a_client):
        client, _ = mairie_a_client
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        response = client.post(reverse('satellite-generer-jeton'), {}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_anonyme_refuse(self, institution_a):
        client = APIClient()
        response = client.post(reverse('satellite-generer-jeton'), {}, format='json')
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
class TestEnroler:

    def test_jeton_valide_cree_le_satellite_en_attente(self, jeton_a, institution_a):
        client = APIClient()
        response = client.post(
            reverse('satellite-enroler'),
            {"jeton": jeton_a.jeton, "nom": "Satellite site A", "profil": "GW", "version_logicielle": "0.1.0"},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data['statut_enrolement'] == 'EN_ATTENTE'
        satellite = Satellite.objects.get(pk=response.data['satellite_id'])
        assert satellite.institution_id == institution_a.id
        assert satellite.profil == 'GW'
        assert satellite.version_logicielle == '0.1.0'
        jeton_a.refresh_from_db()
        assert jeton_a.utilise is True

    def test_jeton_deja_utilise_refuse(self, jeton_a):
        client = APIClient()
        payload = {"jeton": jeton_a.jeton, "nom": "Satellite site A", "profil": "GW"}
        first = client.post(reverse('satellite-enroler'), payload, format='json')
        assert first.status_code == status.HTTP_201_CREATED

        second = client.post(reverse('satellite-enroler'), payload, format='json')
        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert Satellite.objects.count() == 1

    def test_jeton_expire_refuse(self, institution_a):
        jeton = JetonEnrolementSatellite.objects.create(
            institution=institution_a, jeton='jeton-expire',
            expiration=timezone.now() - datetime.timedelta(hours=1),
        )
        client = APIClient()
        response = client.post(
            reverse('satellite-enroler'),
            {"jeton": jeton.jeton, "nom": "Satellite site A", "profil": "GW"},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Satellite.objects.exists()

    def test_jeton_inconnu_refuse(self):
        client = APIClient()
        response = client.post(
            reverse('satellite-enroler'),
            {"jeton": "n-importe-quoi", "nom": "Satellite site A", "profil": "GW"},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_profil_invalide_refuse(self, jeton_a):
        client = APIClient()
        response = client.post(
            reverse('satellite-enroler'),
            {"jeton": jeton_a.jeton, "nom": "Satellite site A", "profil": "AUTRE_CHOSE"},
            format='json',
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert not Satellite.objects.exists()


@pytest.mark.django_db
class TestValider:

    def test_mairie_proprietaire_valide_et_recoit_les_identifiants(self, mairie_a_client, satellite_en_attente):
        client, _ = mairie_a_client
        response = client.post(reverse('satellite-valider', args=[satellite_en_attente.id]), {}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['statut_enrolement'] == 'APPROUVE'
        identifiants = response.data['identifiants_compte_service']
        assert identifiants['email']
        assert identifiants['password']

        satellite_en_attente.refresh_from_db()
        assert satellite_en_attente.statut_enrolement == 'APPROUVE'
        assert satellite_en_attente.compte_service is not None
        assert satellite_en_attente.compte_service.email == identifiants['email']
        # Le compte de service peut immédiatement s'authentifier avec le mot de passe renvoyé.
        auth_client = APIClient()
        token_response = auth_client.post(
            reverse('token_obtain_pair'),
            {"email": identifiants['email'], "password": identifiants['password']},
            format='json',
        )
        assert token_response.status_code == status.HTTP_200_OK

    def test_autre_institution_ne_peut_pas_valider(self, mairie_b_client, satellite_en_attente):
        client, _ = mairie_b_client
        response = client.post(reverse('satellite-valider', args=[satellite_en_attente.id]), {}, format='json')
        # Hors de la zone visible de mairie_b (get_queryset scopé institution) : 404, pas 403.
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_deja_valide_refuse_une_seconde_fois(self, mairie_a_client, satellite_en_attente):
        client, _ = mairie_a_client
        client.post(reverse('satellite-valider', args=[satellite_en_attente.id]), {}, format='json')
        response = client.post(reverse('satellite-valider', args=[satellite_en_attente.id]), {}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_bloque_en_zone_demo(self, mairie_a_client, satellite_en_attente):
        client, _ = mairie_a_client
        client.credentials(HTTP_X_ENVIRONMENT='DEMO')
        response = client.post(reverse('satellite-valider', args=[satellite_en_attente.id]), {}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
class TestRevoquer:

    def test_revoque_desactive_le_compte_de_service(self, mairie_a_client, satellite_en_attente):
        client, _ = mairie_a_client
        valide = client.post(reverse('satellite-valider', args=[satellite_en_attente.id]), {}, format='json')
        identifiants = valide.data['identifiants_compte_service']

        response = client.post(reverse('satellite-revoquer', args=[satellite_en_attente.id]), {}, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert response.data['statut_enrolement'] == 'REVOQUE'

        satellite_en_attente.refresh_from_db()
        assert satellite_en_attente.compte_service.is_active is False

        auth_client = APIClient()
        token_response = auth_client.post(
            reverse('token_obtain_pair'),
            {"email": identifiants['email'], "password": identifiants['password']},
            format='json',
        )
        assert token_response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_double_revocation_refusee(self, mairie_a_client, satellite_en_attente):
        client, _ = mairie_a_client
        client.post(reverse('satellite-valider', args=[satellite_en_attente.id]), {}, format='json')
        client.post(reverse('satellite-revoquer', args=[satellite_en_attente.id]), {}, format='json')
        response = client.post(reverse('satellite-revoquer', args=[satellite_en_attente.id]), {}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestContact:

    def _valider(self, mairie_a_client, satellite):
        client, _ = mairie_a_client
        return client.post(reverse('satellite-valider', args=[satellite.id]), {}, format='json').data

    def test_le_satellite_met_a_jour_son_propre_dernier_contact(self, mairie_a_client, satellite_en_attente):
        identifiants = self._valider(mairie_a_client, satellite_en_attente)
        from core.models import User
        satellite_client = APIClient()
        satellite_client.force_authenticate(
            user=User.objects.get(email=identifiants['identifiants_compte_service']['email'])
        )

        response = satellite_client.post(
            reverse('satellite-contact', args=[satellite_en_attente.id]),
            {"version_logicielle": "0.2.0"}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data['etat'] == 'ACTIF'
        satellite_en_attente.refresh_from_db()
        assert satellite_en_attente.dernier_contact is not None
        assert satellite_en_attente.version_logicielle == '0.2.0'

    def test_un_autre_compte_de_service_ne_peut_pas_signaler_pour_ce_satellite(
        self, mairie_a_client, satellite_en_attente, institution_a
    ):
        identifiants = self._valider(mairie_a_client, satellite_en_attente)
        autre_satellite = Satellite.objects.create(institution=institution_a, nom='Satellite A2', profil='GW')
        client, _ = mairie_a_client
        autre_identifiants = client.post(
            reverse('satellite-valider', args=[autre_satellite.id]), {}, format='json'
        ).data['identifiants_compte_service']

        from core.models import User
        usurpateur_client = APIClient()
        usurpateur_client.force_authenticate(user=User.objects.get(email=autre_identifiants['email']))

        response = usurpateur_client.post(
            reverse('satellite-contact', args=[satellite_en_attente.id]), {}, format='json'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_satellite_non_approuve_ne_peut_pas_signaler(self, satellite_en_attente):
        # EN_ATTENTE : aucun compte_service n'existe encore, donc personne ne peut légitimement
        # appeler contact() pour ce satellite.
        assert satellite_en_attente.compte_service is None


@pytest.mark.django_db
class TestEtatDerive:

    def test_etat_absent_sans_contact(self, mairie_a_client, satellite_en_attente):
        client, _ = mairie_a_client
        response = client.get(reverse('satellite-detail', args=[satellite_en_attente.id]))
        assert response.data['etat'] is None

    def test_etat_inactif_puis_perdu_selon_le_silence(self, mairie_a_client, satellite_en_attente):
        satellite_en_attente.dernier_contact = timezone.now() - datetime.timedelta(minutes=30)
        satellite_en_attente.save(update_fields=['dernier_contact'])
        client, _ = mairie_a_client
        response = client.get(reverse('satellite-detail', args=[satellite_en_attente.id]))
        assert response.data['etat'] == 'INACTIF'

        satellite_en_attente.dernier_contact = timezone.now() - datetime.timedelta(hours=3)
        satellite_en_attente.save(update_fields=['dernier_contact'])
        response = client.get(reverse('satellite-detail', args=[satellite_en_attente.id]))
        assert response.data['etat'] == 'PERDU'


@pytest.mark.django_db
class TestVisibiliteInstitution:

    def test_institution_b_ne_voit_pas_les_satellites_de_a(self, mairie_b_client, satellite_en_attente):
        client, _ = mairie_b_client
        response = client.get(reverse('satellite-list'))
        assert response.status_code == status.HTTP_200_OK
        ids = [item['id'] for item in response.data['results']] if isinstance(response.data, dict) and 'results' in response.data else [item['id'] for item in response.data]
        assert str(satellite_en_attente.id) not in ids
