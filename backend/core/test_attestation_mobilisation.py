from unittest.mock import patch

import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.attestation_mobilisation import (
    generer_mini_carte, generer_pdf_demande_mobilisation, immatriculation_cible, url_verification,
)
from core.models import (
    AffectationRoleOperationnel, ContactInstitution, Crisis, DemandeMobilisation, Institution,
    InstitutionType, Offer, OfferType, PointOperationnel, PointType, RoleOperationnel, Team,
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


@pytest.mark.django_db
class TestImmatriculationCible:

    def test_absente_si_cible_utilisateur(self, demande):
        assert immatriculation_cible(demande) is None

    def test_presente_si_cible_offre_avec_immatriculation(self, responsable_client, crisis, institution_a):
        client, _ = responsable_client
        offer_type, _ = OfferType.objects.get_or_create(type='Test Offre Immat', defaults={'description': ''})
        offre = Offer.objects.create(
            title='Camion', first_name_offer='Jean', last_name_offer='Vehicule',
            email_offer='vehicule@test.fr', status='DISPONIBLE', offer_type=offer_type,
            immatriculation='AB-123-CD',
        )
        response = client.post(reverse('demandemobilisation-list'), {
            'crise': str(crisis.id), 'institution_emettrice': str(institution_a.id),
            'type_demande': 'MISE_A_DISPOSITION', 'cible_offre': str(offre.id),
        }, format='json')
        d = DemandeMobilisation.objects.get(id=response.data['id'])
        assert immatriculation_cible(d) == 'AB-123-CD'


@pytest.mark.django_db
class TestMiniCarte:
    """generer_mini_carte ne doit jamais lever d'exception — un problème réseau externe (OSM
    indisponible, pas de connexion) ne doit jamais casser la génération du PDF, voir son
    docstring. Réseau toujours mocké ici : jamais de vrai appel à tile.openstreetmap.org
    pendant la suite de tests (lent, flaky, dépendant d'un service tiers)."""

    def test_retourne_none_si_echec_reseau(self):
        with patch('requests.Session.get', side_effect=Exception('pas de réseau')):
            resultat = generer_mini_carte(44.9, -0.98)
        assert resultat is None

    def test_retourne_un_png_si_succes(self):
        from PIL import Image
        import io as io_module

        tuile = Image.new('RGB', (256, 256), 'blue')
        tuile_bytes = io_module.BytesIO()
        tuile.save(tuile_bytes, format='PNG')

        class FausseReponse:
            content = tuile_bytes.getvalue()
            def raise_for_status(self):
                pass

        with patch('requests.Session.get', return_value=FausseReponse()):
            resultat = generer_mini_carte(44.9, -0.98)

        assert resultat is not None
        image = Image.open(resultat)
        assert image.format == 'PNG'


@pytest.mark.django_db
class TestZone4ContactFallback:
    """Voir attestation_mobilisation._contact_point : responsable du point > leader d'équipe >
    régulateur d'équipe > repli sur l'institution émettrice (aucun contact de terrain)."""

    def test_repli_institution_si_aucun_point(self, responsable_client, demande):
        pdf = generer_pdf_demande_mobilisation(demande, 'https://www.assista-crise.fr')
        assert pdf.startswith(b'%PDF')  # pas de point_operationnel sur `demande` : ne doit pas planter

    def test_contact_est_le_responsable_du_point(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        point_type, _ = PointType.objects.get_or_create(code='TEST_PT_ATTEST', defaults={'libelle': 'Test'})
        responsable_point = create_user(
            username='resp-point-attest@test.fr', email='resp-point-attest@test.fr',
            first_name='Resp', last_name='Point', phone_number='0611111111',
        )
        point = PointOperationnel.objects.create(nom='Point Test', type=point_type, responsable=responsable_point)
        cible = create_user(username='cible-point-attest@test.fr', email='cible-point-attest@test.fr')

        response = client.post(reverse('demandemobilisation-list'), {
            'crise': str(crisis.id), 'institution_emettrice': str(institution_a.id),
            'type_demande': 'SE_RENDRE_A', 'point_operationnel': str(point.id),
            'cible_utilisateur': str(cible.id),
        }, format='json')
        d = DemandeMobilisation.objects.get(id=response.data['id'])

        from core.attestation_mobilisation import _contact_point
        contact, equipe = _contact_point(d)
        assert contact == responsable_point
        assert equipe is None

    def test_contact_repli_sur_leader_equipe_si_point_sans_responsable(self, responsable_client, crisis, institution_a, create_user):
        client, _ = responsable_client
        point_type, _ = PointType.objects.get_or_create(code='TEST_PT_ATTEST2', defaults={'libelle': 'Test'})
        leader = create_user(username='leader-equipe-attest@test.fr', email='leader-equipe-attest@test.fr')
        equipe = Team.objects.create(name='Équipe Test Attestation', institution=institution_a, leader=leader)
        point = PointOperationnel.objects.create(nom='Point Sans Resp', type=point_type, equipe=equipe)
        cible = create_user(username='cible-point-attest2@test.fr', email='cible-point-attest2@test.fr')

        response = client.post(reverse('demandemobilisation-list'), {
            'crise': str(crisis.id), 'institution_emettrice': str(institution_a.id),
            'type_demande': 'SE_RENDRE_A', 'point_operationnel': str(point.id),
            'cible_utilisateur': str(cible.id),
        }, format='json')
        d = DemandeMobilisation.objects.get(id=response.data['id'])

        from core.attestation_mobilisation import _contact_point
        contact, equipe_trouvee = _contact_point(d)
        assert contact == leader
        assert equipe_trouvee == equipe
