import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.attestation_mobilisation import generer_pdf_demande_mobilisation, url_verification
from core.models import (
    AffectationRoleOperationnel, ContactInstitution, Crisis, DemandeMobilisation, Institution,
    InstitutionType, RoleOperationnel,
)


def _make_institution(**kwargs):
    itype, _ = InstitutionType.objects.get_or_create(code='TEST_TYPE_ATTEST', defaults={'libelle': 'Test'})
    defaults = {'nom': 'Mairie test attestation', 'type': itype, 'email': 'contact@mairie-attest.fr'}
    defaults.update(kwargs)
    return Institution.objects.create(**defaults)


def _make_crisis():
    return Crisis.objects.create(name='Crise attestation test', type='INCENDIE', location='POINT (5.72 45.18)')


def _client_avec_role(create_user, institution, role_code, email):
    user = create_user(username=email, email=email, type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    if role_code:
        role, _ = RoleOperationnel.objects.get_or_create(code=role_code, defaults={'libelle': role_code})
        AffectationRoleOperationnel.objects.create(utilisateur=user, institution=institution, role=role, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def institution_a():
    return _make_institution(nom='Mairie Attestation A')


@pytest.fixture
def crisis():
    return _make_crisis()


@pytest.fixture
def responsable_client(create_user, institution_a):
    return _client_avec_role(create_user, institution_a, 'RESPONSABLE', 'responsable-attest@test.fr')


@pytest.fixture
def simple_membre_client(create_user, institution_a):
    return _client_avec_role(create_user, institution_a, None, 'membre-simple-attest@test.fr')


@pytest.fixture
def demande(responsable_client, crisis, institution_a, create_user):
    client, _ = responsable_client
    cible = create_user(username='cible-attest@test.fr', email='cible-attest@test.fr', first_name='Jean', last_name='Cible')
    response = client.post(reverse('demandemobilisation-list'), {
        'crise': str(crisis.id),
        'institution_emettrice': str(institution_a.id),
        'type_demande': 'SE_RENDRE_A',
        'lieu_texte': 'Salle des fêtes',
        'motif': 'Renfort',
        'cible_utilisateur': str(cible.id),
    }, format='json')
    assert response.status_code == status.HTTP_201_CREATED
    return DemandeMobilisation.objects.get(id=response.data['id'])


@pytest.mark.django_db
class TestGenerationPdf:

    def test_pdf_bytes_valides(self, demande):
        pdf = generer_pdf_demande_mobilisation(demande, 'https://172.16.1.113/')
        assert pdf.startswith(b'%PDF')
        assert len(pdf) > 500

    def test_url_verification_sous_api(self, demande):
        url = url_verification(demande, 'https://172.16.1.113/')
        assert url == f'https://172.16.1.113/api/verifier-mobilisation/{demande.jeton_verification}/'


@pytest.mark.django_db
class TestEnvoyerAttestation:

    def test_responsable_peut_envoyer(self, responsable_client, demande):
        client, _ = responsable_client
        mail.outbox.clear()

        response = client.post(reverse('demandemobilisation-envoyer-attestation', args=[demande.id]))

        assert response.status_code == status.HTTP_200_OK
        assert response.data['envoye_a'] == 'cible-attest@test.fr'
        assert len(mail.outbox) == 1
        envoye = mail.outbox[0]
        assert envoye.to == ['cible-attest@test.fr']
        assert len(envoye.attachments) == 1
        nom_fichier, contenu, mimetype = envoye.attachments[0]
        assert nom_fichier == 'attestation_mobilisation.pdf'
        assert contenu.startswith(b'%PDF')
        assert mimetype == 'application/pdf'

    def test_membre_simple_ne_peut_pas_envoyer(self, simple_membre_client, demande):
        client, _ = simple_membre_client
        mail.outbox.clear()

        response = client.post(reverse('demandemobilisation-envoyer-attestation', args=[demande.id]))

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert len(mail.outbox) == 0

    def test_refuse_si_aucun_email_connu(self, responsable_client, crisis, institution_a):
        """Une cible institution sans email renseigné ne doit jamais planter l'envoi — 400
        explicite plutôt qu'une exception SMTP non gérée."""
        client, _ = responsable_client
        institution_sans_email = _make_institution(nom='Institution Sans Email', email=None)
        create_response = client.post(reverse('demandemobilisation-list'), {
            'crise': str(crisis.id),
            'institution_emettrice': str(institution_a.id),
            'type_demande': 'MISE_A_DISPOSITION',
            'cible_institution': str(institution_sans_email.id),
        }, format='json')
        demande_id = create_response.data['id']
        mail.outbox.clear()

        response = client.post(reverse('demandemobilisation-envoyer-attestation', args=[demande_id]))

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert len(mail.outbox) == 0

    def test_requires_institutional_actor(self, api_client, demande):
        response = api_client.post(reverse('demandemobilisation-envoyer-attestation', args=[demande.id]))
        assert response.status_code in (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)


@pytest.mark.django_db
class TestVerificationPublique:

    def test_jeton_valide_affiche_valide(self, demande):
        client = APIClient()  # non authentifié — c'est justement le point
        response = client.get(reverse('verifier_demande_mobilisation', args=[demande.jeton_verification]))

        assert response.status_code == status.HTTP_200_OK
        contenu = response.content.decode('utf-8')
        assert 'ATTESTATION VALIDE' in contenu
        assert demande.institution_emettrice.nom in contenu
        assert demande.crise.name in contenu

    def test_jeton_revoque_affiche_revoquee(self, responsable_client, demande):
        client, _ = responsable_client
        client.post(reverse('demandemobilisation-revoquer', args=[demande.id]))

        verif_client = APIClient()
        response = verif_client.get(reverse('verifier_demande_mobilisation', args=[demande.jeton_verification]))

        assert response.status_code == status.HTTP_200_OK
        assert 'RÉVOQUÉE' in response.content.decode('utf-8')

    def test_jeton_inconnu_404(self):
        client = APIClient()
        response = client.get(reverse('verifier_demande_mobilisation', args=['jeton-qui-nexiste-pas']))
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_ne_fuit_pas_email_ou_telephone(self, demande):
        """Page publique, sans authentification — jamais de coordonnées de contact dessus."""
        client = APIClient()
        response = client.get(reverse('verifier_demande_mobilisation', args=[demande.jeton_verification]))
        contenu = response.content.decode('utf-8')
        assert 'cible-attest@test.fr' not in contenu
