import tempfile
from io import BytesIO

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from PIL import Image

from core.models import Commune, Crisis, Dossier, DossierParticipant, Document, Information, InstitutionType, Institution, InformationType, Request, Team
from core.serializers import DocumentSerializer
from core.views import build_magic_link, extract_exif_metadata, resolve_or_invite_demandeur

User = get_user_model()

REQUEST_PAYLOAD = {
    "title": "Besoin de nourriture",
    "location": "POINT (5.7245 45.1885)",
    "email_request": "anonyme.demandeur@test.fr",
    "phone_request": "0600000000",
    "status": "NON_TRAITEE",
}


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(name="Crise suivi dossier", type="INCENDIE", location="POINT (5.72 45.18)")


@pytest.fixture
def team(db):
    return Team.objects.create(name="Equipe suivi", description="", color="#3b82f6")


@pytest.fixture
def anonymous_request(db, request_type, crisis):
    return Request.objects.create(
        request_type=request_type, crisis=crisis, author=None,
        first_name_request="Anna", last_name_request="Nonyme", **REQUEST_PAYLOAD,
    )


@pytest.fixture
def local_authority_client(create_user):
    user = create_user(username="autorite-suivi@test.fr", email="autorite-suivi@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.fixture
def dossier_with_demandeur(db, crisis, team, create_user):
    demandeur = create_user(username="demandeur-suivi@test.fr", email="demandeur-suivi@test.fr", type="UTIL_SIMPLE")
    dossier = Dossier.objects.create(
        numero="DOS-TESTSUIVI", crise=crisis, equipe=team, titre="Dossier de test", statut=Dossier.Statut.AFFECTE,
    )
    DossierParticipant.objects.create(dossier=dossier, utilisateur=demandeur, role=DossierParticipant.Role.DEMANDEUR)
    return dossier, demandeur


class DummyRequest:
    def build_absolute_uri(self, path):
        return f"http://testserver{path}"


@pytest.mark.django_db
class TestBuildMagicLink:

    def test_magic_login_routes_to_frontend_with_next(self, create_user, settings):
        settings.SERVER_URL = "https://assista-crise.fr"
        user = create_user(username="magiclink@test.fr", email="magiclink@test.fr", type="UTIL_SIMPLE")

        link = build_magic_link(DummyRequest(), user, "magic-login", next_url="/dossier-suivi/abc")

        assert link.startswith("https://assista-crise.fr/connexion-magique/")
        assert link.endswith("?next=%2Fdossier-suivi%2Fabc")

    def test_other_actions_still_route_to_api(self, create_user, settings):
        # Le lien doit toujours pointer vers l'URL publique canonique configurée
        # (settings.SERVER_URL), jamais vers le Host de la requête entrante — sinon un accès
        # via une IP interne ou un domaine alternatif fuiterait dans un email envoyé à un vrai
        # utilisateur (bug réel corrigé : SERVER_URL n'était même pas positionnée en prod,
        # valeur par défaut = IP privée).
        settings.SERVER_URL = "https://www.assista-crise.fr"
        user = create_user(username="apilink@test.fr", email="apilink@test.fr", type="UTIL_SIMPLE")

        link = build_magic_link(DummyRequest(), user, "delete-request")

        assert link.startswith("https://www.assista-crise.fr/api/delete-request/")


@pytest.mark.django_db
class TestResolveOrInviteDemandeur:

    def test_anonymous_request_creates_enabled_user(self, anonymous_request):
        user, created = resolve_or_invite_demandeur(anonymous_request)

        assert created is True
        assert user.email == anonymous_request.email_request
        assert user.enabled is True
        assert user.is_active is True

    def test_existing_email_is_reused_not_duplicated(self, anonymous_request, create_user):
        existing = create_user(
            username=anonymous_request.email_request, email=anonymous_request.email_request, type="UTIL_SIMPLE",
        )

        user, created = resolve_or_invite_demandeur(anonymous_request)

        assert created is False
        assert user.pk == existing.pk


@pytest.mark.django_db
class TestAssignTeamCreatesTrackingAccess:

    def test_anonymous_request_gets_demandeur_account_and_link(self, local_authority_client, anonymous_request, team):
        client, _ = local_authority_client

        response = client.post(
            reverse('request-assign-team', args=[anonymous_request.id]), {"team": str(team.id)}, format='json'
        )

        assert response.status_code == status.HTTP_200_OK
        dossier = Dossier.objects.get(id=response.data["dossier"])
        created_user = User.objects.get(email=anonymous_request.email_request)
        assert DossierParticipant.objects.filter(
            dossier=dossier, utilisateur=created_user, role=DossierParticipant.Role.DEMANDEUR
        ).exists()
        assert len(mail.outbox) == 1
        assert "connexion-magique" in mail.outbox[0].body
        assert f"next=%2Fdossier-suivi%2F{dossier.id}" in mail.outbox[0].body


@pytest.mark.django_db
class TestDossierAccessScoping:

    def test_non_participant_sees_nothing(self, create_user):
        outsider = create_user(username="outsider@test.fr", email="outsider@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=outsider)

        assert client.get(reverse('dossier-list')).data == []
        assert client.get(reverse('document-list')).data == []
        assert client.get(reverse('dossiercommentaire-list')).data == []

    def test_participant_sees_only_own_dossier(self, dossier_with_demandeur, create_user, crisis, team):
        dossier, demandeur = dossier_with_demandeur
        Dossier.objects.create(numero="DOS-AUTRE", crise=crisis, equipe=team, titre="Autre dossier")
        client = APIClient()
        client.force_authenticate(user=demandeur)

        response = client.get(reverse('dossier-list'))

        assert [d["id"] for d in response.data] == [str(dossier.id)]

    def test_participant_can_comment_and_auteur_is_forced(self, dossier_with_demandeur, create_user):
        dossier, demandeur = dossier_with_demandeur
        someone_else = create_user(username="spoofed@test.fr", email="spoofed@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=demandeur)

        response = client.post(
            reverse('dossiercommentaire-list'),
            {"dossier": str(dossier.id), "commentaire": "Merci pour votre aide", "auteur": str(someone_else.id)},
            format='json',
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["auteur"] == demandeur.id

    def test_non_participant_cannot_comment_on_dossier(self, dossier_with_demandeur, create_user):
        dossier, _ = dossier_with_demandeur
        outsider = create_user(username="outsider2@test.fr", email="outsider2@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=outsider)

        response = client.post(
            reverse('dossiercommentaire-list'),
            {"dossier": str(dossier.id), "commentaire": "Je m'incruste"},
            format='json',
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_institutional_actor_without_institution_sees_nothing(self, dossier_with_demandeur, local_authority_client, crisis, team):
        # AVANT le correctif de zonage, un acteur institutionnel voyait TOUS les dossiers de
        # l'environnement, sans filtre géographique — même sans institution rattachée (donc
        # sans aucune zone de compétence résolvable). C'est exactement le bug corrigé : zéro
        # zone résolvable = zéro dossier visible, jamais la liste complète par défaut.
        Dossier.objects.create(numero="DOS-AUTRE2", crise=crisis, equipe=team, titre="Autre dossier 2")
        client, _ = local_authority_client

        response = client.get(reverse('dossier-list'))

        assert response.data == []

    def test_institutional_actor_sees_dossiers_in_its_zone_only(self, create_user, crisis):
        commune_in = Commune.objects.create(
            code="38185", nom="Grenoble", departement_code="38", epci_code="200040715",
            region_code="84", centre_latitude=45.18, centre_longitude=5.72,
        )
        commune_out = Commune.objects.create(
            code="38544", nom="Voiron", departement_code="38", epci_code="200070078",
            region_code="84", centre_latitude=45.36, centre_longitude=5.59,
        )
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_DOSSIER_ZONE", defaults={"libelle": "Mairie"})
        institution_in = Institution.objects.create(nom="Mairie dossier zone in", type=itype, commune_code=commune_in.code)
        institution_out = Institution.objects.create(nom="Mairie dossier zone out", type=itype, commune_code=commune_out.code)
        team_in = Team.objects.create(name="Equipe zone in", institution=institution_in)
        team_out = Team.objects.create(name="Equipe zone out", institution=institution_out)
        dossier_in = Dossier.objects.create(numero="DOS-ZONE-IN", crise=crisis, equipe=team_in, titre="Dans la zone")
        dossier_out = Dossier.objects.create(numero="DOS-ZONE-OUT", crise=crisis, equipe=team_out, titre="Hors zone")

        user = create_user(username="mairie-dossier-zone@test.fr", email="mairie-dossier-zone@test.fr", type="AUT_LOCALE")
        user.institution = institution_in
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('dossier-list'))

        ids = {d["id"] for d in response.data}
        assert str(dossier_in.id) in ids
        assert str(dossier_out.id) not in ids

    def test_institutional_actor_at_region_level_sees_dossier_linked_via_information(self, create_user, crisis):
        """Régression : Information n'a, contrairement à Request/Team.institution, que
        commune_code (pas epci_code/departement_code/region_code dénormalisés) — le résolveur
        de zone de DossierViewSet.get_queryset filtrait directement `information__region_code`
        (champ inexistant), levant une FieldError dès qu'un compte est scopé au-delà de la
        commune (EPCI/département/région) — reproduit avec une institution secteur_override=
        "region" : la liste des dossiers plantait alors que la liste des signalements
        elle-même fonctionnait déjà (protégée par _information_zone_resolver)."""
        commune = Commune.objects.create(
            code="38185", nom="Grenoble", departement_code="38", epci_code="200040715",
            region_code="84", centre_latitude=45.18, centre_longitude=5.72,
        )
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_DOSSIER_REGION", defaults={"libelle": "Mairie"})
        institution = Institution.objects.create(
            nom="Mairie dossier région", type=itype, commune_code=commune.code, secteur_override="region",
        )
        info_type, _ = InformationType.objects.get_or_create(type="Danger imminent")
        information = Information.objects.create(
            title="Arbre sur la chaussée", first_name_information="A", last_name_information="B",
            email_information="a@test.fr", phone_information="0600000000",
            location="POINT (5.72 45.18)", commune_code=commune.code,
            information_type=info_type, crisis=crisis,
        )
        dossier = Dossier.objects.create(
            numero="DOS-INFO-REGION", crise=crisis, information=information, titre="Depuis un signalement",
        )

        user = create_user(username="mairie-dossier-region@test.fr", email="mairie-dossier-region@test.fr", type="AUT_LOCALE")
        user.institution = institution
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('dossier-list'))

        assert response.status_code == status.HTTP_200_OK
        assert str(dossier.id) in {d["id"] for d in response.data}


def _jpeg_with_gps_exif():
    img = Image.new('RGB', (10, 10), color='blue')
    exif = img.getexif()
    exif[0x8825] = {1: 'N', 2: (48.0, 51.0, 24.0), 3: 'E', 4: (2.0, 21.0, 3.0)}
    exif[0x0110] = 'TestCameraModel'  # Model (non-GPS, doit rester public)
    buf = BytesIO()
    img.save(buf, format='JPEG', exif=exif)
    buf.seek(0)
    return buf.getvalue()


class TestExtractExifMetadata:

    def test_gps_data_goes_only_to_private_metadata(self):
        jpeg_bytes = _jpeg_with_gps_exif()
        with tempfile.NamedTemporaryFile(suffix='.jpg') as f:
            f.write(jpeg_bytes)
            f.flush()

            public, private = extract_exif_metadata(f.name)

        assert private, "les données GPS devraient être présentes dans le dict privé"
        assert 'GPSInfo' not in public
        assert not any('GPS' in str(k) for k in public.keys())
        assert public.get('Model') == 'TestCameraModel'


@pytest.mark.django_db
class TestDocumentPrivacySerializer:

    def _make_document(self, auteur, dossier=None):
        fichier = SimpleUploadedFile("photo.jpg", b"fake-bytes", content_type="image/jpeg")
        return Document.objects.create(
            fichier=fichier,
            auteur=auteur,
            dossier=dossier,
            metadata_publiques={"Model": "TestCameraModel"},
            metadata_privees={"GPSLatitude": "48.0"},
        )

    def _serialize(self, document, viewer):
        class DummyRequest:
            user = viewer
            META = {}
        return DocumentSerializer(document, context={'request': DummyRequest()}).data

    def test_fichier_not_in_representation(self, create_user):
        auteur = create_user(username="doc-auteur@test.fr", email="doc-auteur@test.fr", type="UTIL_SIMPLE")
        document = self._make_document(auteur)

        data = self._serialize(document, auteur)

        assert 'fichier' not in data
        # secure_document_path renomme le fichier stocké en UUID : on vérifie juste
        # que nom_fichier est bien un nom de fichier .jpg, pas un chemin/URL complet.
        assert data['nom_fichier'].endswith('.jpg')
        assert '/' not in data['nom_fichier']

    def test_metadata_privees_visible_to_author(self, create_user):
        auteur = create_user(username="doc-auteur2@test.fr", email="doc-auteur2@test.fr", type="UTIL_SIMPLE")
        document = self._make_document(auteur)

        data = self._serialize(document, auteur)

        assert data['metadata_privees'] == {"GPSLatitude": "48.0"}

    def test_metadata_privees_visible_to_institutional_actor(self, create_user):
        auteur = create_user(username="doc-auteur3@test.fr", email="doc-auteur3@test.fr", type="UTIL_SIMPLE")
        institutional = create_user(username="doc-institution@test.fr", email="doc-institution@test.fr", type="AUT_LOCALE")
        document = self._make_document(auteur)

        data = self._serialize(document, institutional)

        assert data['metadata_privees'] == {"GPSLatitude": "48.0"}

    def test_metadata_privees_hidden_from_other_participant(self, create_user):
        auteur = create_user(username="doc-auteur4@test.fr", email="doc-auteur4@test.fr", type="UTIL_SIMPLE")
        other = create_user(username="doc-other@test.fr", email="doc-other@test.fr", type="UTIL_SIMPLE")
        document = self._make_document(auteur)

        data = self._serialize(document, other)

        assert data['metadata_privees'] == {}

    def test_metadata_privees_visible_to_dossier_coequipier(self, create_user, dossier_with_demandeur):
        """Décision explicite : contrairement à une photo d'offre/demande, une photo rattachée
        à un Dossier partage son GPS avec tout participant du dossier, pas seulement son
        auteur — les coéquipiers en ont besoin pour la minimap de suivi terrain."""
        dossier, demandeur = dossier_with_demandeur
        auteur = create_user(username="doc-auteur5@test.fr", email="doc-auteur5@test.fr", type="UTIL_SIMPLE")
        document = self._make_document(auteur, dossier=dossier)

        data = self._serialize(document, demandeur)

        assert data['metadata_privees'] == {"GPSLatitude": "48.0"}

    def test_metadata_privees_still_hidden_for_non_participant_on_dossier_photo(self, create_user, dossier_with_demandeur):
        dossier, _demandeur = dossier_with_demandeur
        auteur = create_user(username="doc-auteur6@test.fr", email="doc-auteur6@test.fr", type="UTIL_SIMPLE")
        unrelated = create_user(username="doc-unrelated6@test.fr", email="doc-unrelated6@test.fr", type="UTIL_SIMPLE")
        document = self._make_document(auteur, dossier=dossier)

        data = self._serialize(document, unrelated)

        assert data['metadata_privees'] == {}


@pytest.mark.django_db
class TestDocumentGpsDecimalFields:

    def _make_document_with_gps(self, auteur, dossier=None):
        fichier = SimpleUploadedFile("photo.jpg", b"fake-bytes", content_type="image/jpeg")
        return Document.objects.create(
            fichier=fichier,
            auteur=auteur,
            dossier=dossier,
            metadata_privees={
                "GPSLatitude": "(48.0, 51.0, 24.0)",
                "GPSLatitudeRef": "N",
                "GPSLongitude": "(2.0, 21.0, 3.0)",
                "GPSLongitudeRef": "E",
                "GPSImgDirection": "90.5",
            },
        )

    def _serialize(self, document, viewer):
        class DummyRequest:
            user = viewer
            META = {}
        return DocumentSerializer(document, context={'request': DummyRequest()}).data

    def test_converts_dms_to_decimal_for_author(self, create_user):
        auteur = create_user(username="doc-gps-auteur@test.fr", email="doc-gps-auteur@test.fr", type="UTIL_SIMPLE")
        document = self._make_document_with_gps(auteur)

        data = self._serialize(document, auteur)

        assert data['latitude'] == pytest.approx(48.8567, abs=1e-3)
        assert data['longitude'] == pytest.approx(2.3508, abs=1e-3)
        assert data['azimuth'] == pytest.approx(90.5)

    def test_negative_for_south_west_hemisphere(self, create_user):
        auteur = create_user(username="doc-gps-sw@test.fr", email="doc-gps-sw@test.fr", type="UTIL_SIMPLE")
        fichier = SimpleUploadedFile("photo.jpg", b"fake-bytes", content_type="image/jpeg")
        document = Document.objects.create(
            fichier=fichier, auteur=auteur,
            metadata_privees={
                "GPSLatitude": "(48.0, 51.0, 24.0)", "GPSLatitudeRef": "S",
                "GPSLongitude": "(2.0, 21.0, 3.0)", "GPSLongitudeRef": "W",
            },
        )

        data = self._serialize(document, auteur)

        assert data['latitude'] < 0
        assert data['longitude'] < 0

    def test_hidden_when_metadata_not_visible(self, create_user):
        auteur = create_user(username="doc-gps-hidden@test.fr", email="doc-gps-hidden@test.fr", type="UTIL_SIMPLE")
        other = create_user(username="doc-gps-other@test.fr", email="doc-gps-other@test.fr", type="UTIL_SIMPLE")
        document = self._make_document_with_gps(auteur)

        data = self._serialize(document, other)

        assert data['latitude'] is None
        assert data['longitude'] is None
        assert data['azimuth'] is None

    def test_none_when_no_gps_data(self, create_user):
        auteur = create_user(username="doc-gps-none@test.fr", email="doc-gps-none@test.fr", type="UTIL_SIMPLE")
        fichier = SimpleUploadedFile("photo.jpg", b"fake-bytes", content_type="image/jpeg")
        document = Document.objects.create(fichier=fichier, auteur=auteur)

        data = self._serialize(document, auteur)

        assert data['latitude'] is None
        assert data['longitude'] is None
        assert data['azimuth'] is None


@pytest.mark.django_db
class TestDossierRegulateurContact:

    def test_regulateurs_included_and_masked_in_demo(self, create_user, crisis, team):
        """Le viewer est un acteur institutionnel (accès garanti à dossier-detail) : on vérifie
        ici uniquement le contenu du champ regulateurs et son masquage DEMO, pas qui peut voir
        le dossier lui-même (couvert ailleurs par TestDossierAccessScoping)."""
        from core.models import AffectationRoleOperationnel, Competence, Institution, InstitutionType, RoleOperationnel

        competence = Competence.objects.create(nom="Competence dossier regulateur test")
        dossier = Dossier.objects.create(
            numero="DOS-REGUL-TEST", crise=crisis, equipe=team, competence=competence, titre="Titre", statut=Dossier.Statut.NOUVEAU,
        )
        role, _ = RoleOperationnel.objects.get_or_create(code="REGULATEUR", defaults={"libelle": "Régulateur"})
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_REGUL_DOSSIER_TEST", defaults={"libelle": "Mairie"})
        institution = Institution.objects.create(nom="Mairie régul dossier test", type=itype)
        regulateur = create_user(
            username="regul-contact@test.fr", email="regul-contact@test.fr", type="UTIL_SIMPLE",
            phone_number="0611223344",
        )
        AffectationRoleOperationnel.objects.create(
            utilisateur=regulateur, institution=institution, competence=competence, role=role, actif=True,
        )
        viewer = create_user(
            username="admin-regul-dossier-test@test.fr", email="admin-regul-dossier-test@test.fr",
            type="ADMIN", demo_role="ADMIN",
        )

        client = APIClient()
        client.force_authenticate(user=viewer)
        response = client.get(reverse('dossier-detail', args=[dossier.id]))

        assert response.status_code == status.HTTP_200_OK
        regulateurs = response.data['regulateurs']
        assert len(regulateurs) == 1
        assert regulateurs[0]['email'] == "regul-contact@test.fr"
        assert regulateurs[0]['telephone'] == "0611223344"

        dossier.environment = "DEMO"
        dossier.save(update_fields=['environment'])
        client.credentials(HTTP_X_ENVIRONMENT="DEMO")
        response = client.get(reverse('dossier-detail', args=[dossier.id]))
        regulateurs = response.data['regulateurs']
        assert regulateurs[0]['email'] != "regul-contact@test.fr"
        assert regulateurs[0]['telephone'] != "0611223344"
