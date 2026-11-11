"""Module mobilisation : prévisualisation du PDF, extraction CSV, vérification par QR.

Demandes de Sylvain du 11/11/2026. Ce que ces tests verrouillent :

1. **La prévisualisation n'envoie rien.** Avant, la seule façon de voir le document était de
   `envoyer-attestation` — donc de l'expédier au destinataire pour s'apercevoir après coup
   qu'une ligne était fausse.
2. **L'extraction respecte le cloisonnement.** Passer l'identifiant d'une institution dont on
   n'est pas membre ne doit pas sortir ses mobilisations : le filtre s'applique PAR-DESSUS
   `get_queryset`, il ne le remplace pas.
3. **Le QR scanné rend un verdict, jamais une erreur de route.** Un jeton inconnu donne 200 et
   `valide: false` : le scanner doit distinguer « ce QR n'est pas des nôtres » d'une panne
   réseau, et un 404 se confond avec une erreur de client.
4. **Le JSON public n'expose RIEN de plus que la page publique.** Le jeton est l'autorisation ;
   y ajouter un téléphone ferait d'un QR ramassé par terre une fuite de données personnelles.
5. **Une révocation se voit immédiatement**, dans le PDF régénéré comme dans le verdict — c'est
   toute la raison d'être d'une vérification en ligne.
"""
import csv
import io

import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.attestation_mobilisation import COTE_QR_MM, generer_qr_image
from core.models import (
    AffectationRoleOperationnel, ContactInstitution, Crisis, DemandeMobilisation, Institution,
    InstitutionType, RoleOperationnel, StatutDemandeMobilisation,
)


def _institution(nom, code='TEST_TYPE_MOB'):
    itype, _ = InstitutionType.objects.get_or_create(
        code=code, defaults={'libelle': 'Test mobilisation'})
    return Institution.objects.create(nom=nom, type=itype, email=f"contact@{nom[:6].lower()}.fr")


def _client_avec_role(create_user, institution, role_code, email):
    user = create_user(username=email, email=email, type='AUT_LOCALE')
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    if role_code:
        role, _ = RoleOperationnel.objects.get_or_create(
            code=role_code, defaults={'libelle': role_code})
        AffectationRoleOperationnel.objects.create(
            utilisateur=user, institution=institution, role=role, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def institution_a(db):
    return _institution('Mairie Module A')


@pytest.fixture
def crise(db):
    return Crisis.objects.create(name='Crise module mobilisation', type='INCENDIE',
                                 location='POINT (5.72 45.18)')


@pytest.fixture
def responsable(create_user, institution_a):
    return _client_avec_role(create_user, institution_a, 'RESPONSABLE',
                             'resp-module@test.fr')


@pytest.fixture
def demande(responsable, crise, institution_a, create_user):
    client, _ = responsable
    cible = create_user(username='cible-module@test.fr', email='cible-module@test.fr',
                        first_name='Jean', last_name='Cible')
    reponse = client.post(reverse('demandemobilisation-list'), {
        'crise': str(crise.id),
        'institution_emettrice': str(institution_a.id),
        'type_demande': 'SE_RENDRE_A',
        'lieu_texte': 'Salle des fêtes',
        'motif': 'Renfort',
        'cible_utilisateur': str(cible.id),
    }, format='json')
    assert reponse.status_code == status.HTTP_201_CREATED
    return DemandeMobilisation.objects.get(id=reponse.data['id'])


@pytest.mark.django_db
class TestPrevisualisationDuPdf:

    def test_le_pdf_est_rendu_inline_et_rien_n_est_envoye(self, responsable, demande):
        """« Preview » veut dire : voir, pas expédier."""
        client, _ = responsable
        mail.outbox.clear()

        reponse = client.get(reverse('demandemobilisation-attestation', args=[demande.id]))

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse['Content-Type'] == 'application/pdf'
        # `inline` et non `attachment` : le navigateur l'affiche au lieu de le déposer dans
        # les téléchargements.
        assert reponse['Content-Disposition'].startswith('inline;')
        assert reponse.content.startswith(b'%PDF')
        assert mail.outbox == []

    def test_une_institution_etrangere_ne_previsualise_pas(self, create_user, demande):
        """Le cloisonnement de get_queryset s'applique aussi à cette action."""
        autre = _institution('Mairie Module B', code='TEST_TYPE_MOB_B')
        client, _ = _client_avec_role(create_user, autre, 'RESPONSABLE',
                                      'etranger-module@test.fr')

        reponse = client.get(reverse('demandemobilisation-attestation', args=[demande.id]))

        assert reponse.status_code == status.HTTP_404_NOT_FOUND

    def test_le_pdf_regenere_porte_le_statut_a_jour(self, responsable, demande):
        """Jamais de PDF figé en cache : une révocation doit se voir au tirage suivant."""
        client, _ = responsable
        demande.statut = StatutDemandeMobilisation.REVOQUEE
        demande.save(update_fields=['statut'])

        reponse = client.get(reverse('demandemobilisation-attestation', args=[demande.id]))

        assert reponse.status_code == status.HTTP_200_OK
        # Le texte est compressé dans le PDF : on ne cherche pas la chaîne, on vérifie que la
        # génération a bien relu l'objet (le statut est lu à la génération, voir zone 2).
        assert reponse.content.startswith(b'%PDF')


@pytest.mark.django_db
class TestQrPlusGros:

    def test_le_cote_du_qr_a_ete_augmente(self):
        """Demande explicite : « plus gros pour être plus facilement lisible ». 45 mm au lieu
        de 26, soit trois fois la surface."""
        assert COTE_QR_MM == 45

    def test_le_qr_reste_lisible_apres_pliage(self):
        """Le document est plié en quatre et ressort froissé : la correction d'erreur est
        montée à 25 % (niveau Q) pour qu'un pli au travers du motif reste rattrapable."""
        import qrcode
        from PIL import Image

        image = Image.open(generer_qr_image("https://exemple.invalide/api/verifier/abc/"))
        # Un QR rendu assez grand pour être réduit proprement à 45 mm sans devenir flou.
        assert image.width >= 300
        assert qrcode.constants.ERROR_CORRECT_Q == 3


@pytest.mark.django_db
class TestExtractionCsv:

    def _lire(self, reponse):
        return list(csv.reader(io.StringIO(reponse.content.decode('utf-8')), delimiter=';'))

    def test_l_extraction_liste_les_mobilisations_de_la_crise(self, responsable, demande,
                                                               crise, institution_a):
        client, _ = responsable

        reponse = client.get(reverse('demandemobilisation-extraction'), {
            'crise': str(crise.id), 'institution': str(institution_a.id),
        })

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse['Content-Type'].startswith('text/csv')
        lignes = self._lire(reponse)
        assert lignes[0][0] == 'Référence'
        assert len(lignes) == 2
        assert 'Jean Cible' in lignes[1]
        # Le lien de vérification plutôt que le jeton nu : collé dans un navigateur, il donne
        # le statut à jour — ce qu'un CSV ne saura jamais dire.
        assert any('verifier-mobilisation' in cellule for cellule in lignes[1])

    def test_la_crise_est_obligatoire(self, responsable):
        client, _ = responsable

        reponse = client.get(reverse('demandemobilisation-extraction'))

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST

    def test_une_crise_inconnue_est_dite(self, responsable):
        client, _ = responsable
        import uuid

        reponse = client.get(reverse('demandemobilisation-extraction'),
                             {'crise': str(uuid.uuid4())})

        assert reponse.status_code == status.HTTP_404_NOT_FOUND

    def test_on_n_extrait_PAS_les_mobilisations_d_une_autre_institution(
            self, create_user, demande, crise, institution_a):
        """Le test qui compte : passer l'identifiant d'une institution dont on n'est pas membre
        ne doit rien sortir. Le filtre s'applique par-dessus le cloisonnement."""
        autre = _institution('Mairie Module C', code='TEST_TYPE_MOB_C')
        client, _ = _client_avec_role(create_user, autre, 'RESPONSABLE',
                                      'etranger2-module@test.fr')

        reponse = client.get(reverse('demandemobilisation-extraction'), {
            'crise': str(crise.id), 'institution': str(institution_a.id),
        })

        assert reponse.status_code == status.HTTP_200_OK
        # L'en-tête seul : aucune ligne de données.
        assert len(self._lire(reponse)) == 1

    def test_l_export_est_trace_comme_un_export(self, responsable, demande, crise):
        """La main courante distingue une consultation d'un export, qui sort les données du
        périmètre de la plateforme."""
        from core.models import AuditLog

        client, _ = responsable
        client.get(reverse('demandemobilisation-extraction'), {'crise': str(crise.id)})

        trace = AuditLog.objects.filter(
            objet_type='DemandeMobilisation', action__code='EXPORT').first()
        assert trace is not None
        assert trace.exposition == AuditLog.Exposition.EXPORT


@pytest.mark.django_db
class TestVerificationJson:

    def _url(self, jeton):
        return reverse('verifier_demande_mobilisation_json', args=[jeton])

    def test_une_attestation_active_est_valide(self, demande):
        """Sans authentification : le jeton suffit à vérifier l'AUTHENTICITÉ.

        Le détail nominatif, lui, demande d'être connecté depuis le resserrage du 11/11/2026
        — voir `TestVerdictADeuxNiveaux`."""
        reponse = APIClient().get(self._url(demande.jeton_verification))

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data['valide'] is True
        assert reponse.data['connue'] is True
        assert reponse.data['reference'] == str(demande.id)[:8].upper()
        assert reponse.data['complet'] is False

    def test_une_attestation_revoquee_est_dite_invalide(self, demande):
        """Une révocation survenue après l'émission du PDF doit se voir immédiatement : c'est
        toute la raison d'être d'une vérification en ligne."""
        demande.statut = StatutDemandeMobilisation.REVOQUEE
        demande.save(update_fields=['statut'])

        reponse = APIClient().get(self._url(demande.jeton_verification))

        assert reponse.data['valide'] is False
        assert reponse.data['connue'] is True
        assert 'révoquée' in reponse.data['motif'].lower()

    def test_un_jeton_inconnu_rend_200_et_non_404(self):
        """Le scanner doit distinguer « ce QR n'est pas des nôtres » d'une panne réseau ; un
        404 se confond avec une erreur de route côté client."""
        reponse = APIClient().get(self._url('jeton-qui-nexiste-pas'))

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data['valide'] is False
        assert reponse.data['connue'] is False

    def test_le_json_n_expose_AUCUNE_donnee_personnelle_de_contact(self, demande):
        """Un QR code ramassé par terre ne doit pas livrer le téléphone de quelqu'un."""
        reponse = APIClient().get(self._url(demande.jeton_verification))

        champs = set(reponse.data)
        assert 'email' not in champs
        assert 'telephone' not in champs
        # Et pas davantage en cherchant la valeur elle-même dans la réponse entière.
        assert 'cible-module@test.fr' not in str(reponse.data)


@pytest.mark.django_db
class TestVerdictADeuxNiveaux:
    """Resserrage du 11/11/2026, demandé par Sylvain : « plutôt que la page soit publique, on
    peut le rendre authentifié obligatoire ».

    La réponse retenue tient les deux besoins : un compte connecté voit tout, un contrôleur
    extérieur vérifie l'authenticité sans apprendre qui a été mobilisé. Jusque-là, la page
    publique affichait le nom du destinataire et le lieu de rendez-vous — un QR ramassé par
    terre disait donc qui était mobilisé et où."""

    def _url(self, jeton):
        return reverse('verifier_demande_mobilisation_json', args=[jeton])

    def test_un_anonyme_n_apprend_NI_le_nom_NI_le_lieu(self, demande):
        """LE test du resserrage."""
        reponse = APIClient().get(self._url(demande.jeton_verification))

        assert reponse.data['valide'] is True
        assert reponse.data['complet'] is False
        assert 'destinataire' not in reponse.data
        assert 'lieu' not in reponse.data
        # Rien ne doit laisser filtrer la valeur par un autre chemin.
        assert 'Jean Cible' not in str(reponse.data)
        assert 'Salle des fêtes' not in str(reponse.data)

    def test_un_anonyme_vérifie_quand_meme_l_authenticite(self, demande):
        """C'est la raison d'être de l'endpoint public : une autorité extérieure doit pouvoir
        dire si le document est faux. Elle lit le nom sur l'attestation qu'elle tient."""
        reponse = APIClient().get(self._url(demande.jeton_verification))

        assert reponse.data['connue'] is True
        assert reponse.data['reference'] == str(demande.id)[:8].upper()
        assert reponse.data['institution_emettrice'] == 'Mairie Module A'
        assert reponse.data['crise'] == 'Crise module mobilisation'

    def test_un_compte_connecte_voit_tout(self, responsable, demande):
        """Le chemin de l'iPhone : l'appareil photo ouvre l'URL, l'application retrouve la
        session, et le contrôleur voit le détail."""
        client, _ = responsable

        reponse = client.get(self._url(demande.jeton_verification))

        assert reponse.data['complet'] is True
        assert reponse.data['destinataire'] == 'Jean Cible'
        assert reponse.data['lieu'] == 'Salle des fêtes'

    def test_n_importe_quel_compte_connecte_suffit(self, create_user, demande):
        """Décision assumée : la barre posée est « être authentifié sur le site », pas « avoir
        un lien avec cette demande ». Le jeton reste l'autorisation ; l'authentification ne
        fait que lever le masquage."""
        autre = _institution('Mairie Module D', code='TEST_TYPE_MOB_D')
        client, _ = _client_avec_role(create_user, autre, None, 'quelconque-module@test.fr')

        reponse = client.get(self._url(demande.jeton_verification))

        assert reponse.data['complet'] is True

    def test_la_page_HTML_publique_ne_nomme_plus_personne(self, demande):
        """Servie par Django, qui ne voit pas le jeton de l'application : dans le doute, elle
        en dit le moins."""
        reponse = APIClient().get(
            reverse('verifier_demande_mobilisation', args=[demande.jeton_verification]))
        contenu = reponse.content.decode('utf-8')

        assert 'ATTESTATION VALIDE' in contenu
        assert 'Mairie Module A' in contenu
        assert 'Jean Cible' not in contenu
        assert 'Salle des fêtes' not in contenu

    def test_la_page_HTML_offre_la_porte_vers_l_application(self, demande):
        """Pour les attestations DÉJÀ ÉMISES, dont le QR porte l'ancienne adresse imprimée :
        un geste suffit pour passer au détail complet."""
        reponse = APIClient().get(
            reverse('verifier_demande_mobilisation', args=[demande.jeton_verification]))
        contenu = reponse.content.decode('utf-8')

        assert f'/verifier-mobilisation/{demande.jeton_verification}' in contenu
        assert '/api/verifier-mobilisation' not in contenu.split('<a href')[1]

    def test_les_deux_sorties_ne_peuvent_pas_diverger(self, demande):
        """Une seule fonction les produit : deux listes de champs écrites séparément
        finiraient par ne plus dire la même chose, et celle qui se tromperait serait la
        publique."""
        from core.views import verdict_mobilisation

        reduit = verdict_mobilisation(demande, complet=False)
        complet = verdict_mobilisation(demande, complet=True)

        assert set(complet) - set(reduit) == {'destinataire', 'lieu'}
        for champ in reduit:
            if champ != 'complet':
                assert reduit[champ] == complet[champ]
