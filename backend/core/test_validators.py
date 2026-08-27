import pytest
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from core.validators import validate_image_file
from core.auth_validation import InstitutionEmailValidator
from core.serializers import UserSerializer
from core.models import User, UserRole
from io import BytesIO
from PIL import Image


@pytest.mark.django_db
class TestImageValidator:
    """Tests du validateur d'images"""
    
    def create_test_image(self, format='PNG', size=(100, 100), file_size_mb=None):
        """Créer une image de test"""
        img = Image.new('RGB', size, color='red')
        img_io = BytesIO()
        img.save(img_io, format=format)
        img_io.seek(0)
        
        # Si on veut une taille spécifique, remplir avec des données
        if file_size_mb:
            target_size = file_size_mb * 1024 * 1024
            img_io = BytesIO(b'0' * int(target_size))
        
        return SimpleUploadedFile(
            f"test.{format.lower()}",
            img_io.getvalue(),
            content_type=f"image/{format.lower()}"
        )
    
    def test_valid_png_image(self):
        """Test image PNG valide"""
        file = self.create_test_image('PNG')
        try:
            validate_image_file(file)
        except ValidationError:
            pytest.fail("Image PNG valide ne devrait pas lever d'exception")
    
    def test_valid_jpeg_image(self):
        """Test image JPEG valide"""
        file = self.create_test_image('JPEG')
        try:
            validate_image_file(file)
        except ValidationError:
            pytest.fail("Image JPEG valide ne devrait pas lever d'exception")
    
    def test_valid_webp_image(self):
        """Test image WEBP valide"""
        file = self.create_test_image('WEBP')
        try:
            validate_image_file(file)
        except ValidationError:
            pytest.fail("Image WEBP valide ne devrait pas lever d'exception")
    
    def test_valid_gif_image(self):
        """Test image GIF valide"""
        file = self.create_test_image('GIF')
        try:
            validate_image_file(file)
        except ValidationError:
            pytest.fail("Image GIF valide ne devrait pas lever d'exception")
    
    def test_image_too_large(self):
        """Test image trop volumineuse (> 5 Mo)"""
        file = self.create_test_image('PNG', file_size_mb=6)
        
        with pytest.raises(ValidationError) as exc_info:
            validate_image_file(file)
        
        assert "Fichier trop volumineux" in str(exc_info.value)
        assert "5 Mo" in str(exc_info.value)
    
    def test_invalid_format_bmp(self):
        """Test format non autorisé (BMP)"""
        file = self.create_test_image('BMP')
        
        with pytest.raises(ValidationError) as exc_info:
            validate_image_file(file)
        
        # BMP est capturé par l'exception générale car verify() échoue avant
        assert "Fichier image invalide" in str(exc_info.value) or "Format d'image non supporté" in str(exc_info.value)
    
    def test_corrupted_file(self):
        """Test fichier corrompu"""
        corrupted_file = SimpleUploadedFile(
            "corrupted.png",
            b"This is not an image file",
            content_type="image/png"
        )
        
        with pytest.raises(ValidationError) as exc_info:
            validate_image_file(corrupted_file)
        
        assert "Fichier image invalide" in str(exc_info.value)


def test_institutional_email_with_mairie_domain_is_accepted():
    """Un email de mairie doit être accepté comme domaine institutionnel valide."""
    valid, message = InstitutionEmailValidator.validate_email_domain("contact@mairie-bordeaux.fr")

    assert valid is True
    assert message == "Adresse email valide"


def test_institutional_email_with_unrelated_domain_is_rejected():
    """Un email non institutionnel doit être rejeté."""
    valid, message = InstitutionEmailValidator.validate_email_domain("contact@randommail.com")

    assert valid is False
    assert "doit correspondre" in message.lower()


def test_institutional_email_with_public_authority_domains_is_accepted():
    """Les emails de collectivités et services publics doivent être acceptés."""
    accepted_domains = [
        "contact@prefecture-bordeaux.fr",
        "contact@police-bordeaux.fr",
        "contact@gendarmerie.fr",
        "contact@samu-33.fr",
        "contact@cc-pays-auron.fr",
        "contact@collectivites-locales.fr",
        "contact@ministere.gouv.fr",
    ]

    for email in accepted_domains:
        valid, message = InstitutionEmailValidator.validate_email_domain(email)
        assert valid is True, f"{email} should be accepted: {message}"


@pytest.mark.django_db
def test_validate_institution_account_matches_commune_and_institution_type():
    """La validation institutionnelle doit combiner institution, commune et domaine."""
    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@mairie-bordeaux.fr",
        institution_name="Mairie de Bordeaux",
        institution_type="mairie",
        commune_name="Bordeaux",
        commune_code="33063",
    )

    assert valid is True
    assert details["commune"]["name"] == "Bordeaux"
    # La confirmation peut désormais venir soit de l'annuaire officiel (voie prioritaire),
    # soit des heuristiques existantes (opendata/nom) selon ce que l'annuaire renvoie en direct.
    assert "mairie" in message.lower() or "valide" in message.lower() or "confirmée" in message.lower()


@pytest.mark.django_db
def test_validate_institution_account_rejects_mismatch_between_type_and_domain():
    """Un type d'institution incompatible avec le domaine doit être rejeté."""
    valid, message, _ = InstitutionEmailValidator.validate_institution_account(
        email="contact@prefecture-bordeaux.fr",
        institution_name="Mairie de Bordeaux",
        institution_type="mairie",
        commune_name="Bordeaux",
        commune_code="33063",
    )

    assert valid is False
    assert "incompatible" in message.lower() or "doit correspondre" in message.lower()


@pytest.mark.django_db
def test_institution_registration_is_rejected_when_validation_fails():
    """Une inscription institutionnelle invalide doit être refusée, sans créer de compte."""
    serializer = UserSerializer(data={
        'username': 'institution-invalid',
        'email': 'contact@prefecture-bordeaux.fr',
        'password': 'StrongPass123!',
        'type': UserRole.LOCAL_AUTHORITY,
        'first_name': 'Mairie',
        'last_name': 'Bordeaux',
        'phone_number': '0123456789',
        'institution_name': 'Mairie de Bordeaux',
        'institution_type': 'mairie',
        'commune_name': 'Bordeaux',
        'commune_code': '33063',
    })

    assert serializer.is_valid() is False
    assert 'email' in serializer.errors or 'non_field_errors' in serializer.errors


ANNUAIRE_SDIS_RECORD = {
    "fields": {
        "nom": "SDIS 33",
        "adresse_courriel": "contact@sdis33.fr",
        "pivot": {"type_service_local": "sdis"},
    }
}

ANNUAIRE_MAIRIE_RECORD = {
    "fields": {
        "nom": "Mairie - Bordeaux",
        "site_internet": [{"libelle": "", "valeur": "https://www.bordeaux.fr"}],
        "pivot": {"type_service_local": "mairie"},
    }
}


def test_extract_domain_candidates_reads_email_and_website():
    """Le domaine doit être extrait aussi bien d'un email officiel que d'une URL de site web."""
    assert "sdis33.fr" in InstitutionEmailValidator._extract_domain_candidates(ANNUAIRE_SDIS_RECORD)
    assert "bordeaux.fr" in InstitutionEmailValidator._extract_domain_candidates(ANNUAIRE_MAIRIE_RECORD)


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_annuaire_match_validates_domain_not_covered_by_regex(mock_search):
    """sdis33.fr n'est reconnu par aucun motif de validate_email_domain : l'annuaire doit
    quand même confirmer l'inscription quand il connaît le domaine officiel de l'institution."""
    mock_search.return_value = [ANNUAIRE_SDIS_RECORD]

    assert InstitutionEmailValidator.validate_email_domain("agent@sdis33.fr")[0] is False

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="agent@sdis33.fr",
        institution_name="SDIS 33",
        institution_type="sdis",
    )

    assert valid is True
    assert details["validation_mode"] == "annuaire"
    assert details["annuaire"]["domain"] == "sdis33.fr"
    mock_search.assert_called_once()


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_annuaire_unavailable_falls_back_to_regex_validation(mock_search):
    """Si l'annuaire ne trouve rien (institution absente, API en panne...), la validation
    existante par regex/heuristiques doit continuer à fonctionner comme avant."""
    mock_search.return_value = None

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@mairie-bordeaux.fr",
        institution_name="Mairie de Bordeaux",
        institution_type="mairie",
        commune_name="Bordeaux",
        commune_code="33063",
    )

    assert valid is True
    assert details.get("validation_mode") != "annuaire"


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_annuaire_domain_mismatch_does_not_short_circuit(mock_search):
    """Une institution trouvée par l'annuaire mais dont le domaine ne correspond pas à
    l'email fourni ne doit pas valider à tort : on retombe sur la validation existante."""
    mock_search.return_value = [ANNUAIRE_MAIRIE_RECORD]

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@unrelated-domain.com",
        institution_name="Mairie de Bordeaux",
        institution_type="mairie",
    )

    assert details.get("validation_mode") != "annuaire"
    assert valid is False


def test_best_geo_match_requires_exact_name_not_top_score():
    """geo.api.gouv.fr classe par pertinence, pas par exactitude (ex: chercher 'Loire' classe la
    commune 'Loiret' en tête) : on ne doit accepter qu'un nom rigoureusement identique."""
    entries = [
        {"code": "45", "nom": "Loiret", "_score": 0.8},
        {"code": "42", "nom": "Loire", "_score": 0.6},
    ]
    match = InstitutionEmailValidator._best_geo_match(entries, "Loire")
    assert match["code"] == "42"


def test_best_geo_match_returns_none_without_exact_match():
    """Sans nom strictement identique dans les résultats, on ne devine pas : on renvoie None
    pour laisser l'appelant retomber sur le niveau administratif suivant."""
    entries = [{"code": "49178", "nom": "Loiré", "_score": 0.9}]
    assert InstitutionEmailValidator._best_geo_match(entries, "Loire") is None


@patch("core.auth_validation.InstitutionEmailValidator._fetch_json")
def test_resolve_zone_code_falls_back_to_departement(mock_fetch):
    """'Loire' n'est le nom exact d'aucune commune (seulement de la commune voisine 'Loiré') :
    la résolution doit retomber sur le département Loire (42), pas rester bloquée au niveau commune."""
    def fake_fetch(url):
        if "/communes" in url:
            return [{"code": "49178", "nom": "Loiré"}]
        if "/departements" in url:
            return [{"code": "42", "nom": "Loire"}]
        return None

    mock_fetch.side_effect = fake_fetch

    zone = InstitutionEmailValidator._resolve_zone_code("Loire", "")
    assert zone == {"level": "departement", "code": "42", "nom": "Loire"}


@patch("core.auth_validation.InstitutionEmailValidator._fetch_json")
def test_resolve_zone_code_falls_back_to_region(mock_fetch):
    """Sans correspondance commune ni département, on tente la région avant d'abandonner."""
    def fake_fetch(url):
        if "/regions" in url:
            return [{"code": "84", "nom": "Auvergne-Rhône-Alpes"}]
        return []

    mock_fetch.side_effect = fake_fetch

    zone = InstitutionEmailValidator._resolve_zone_code("Auvergne-Rhône-Alpes", "")
    assert zone == {"level": "region", "code": "84", "nom": "Auvergne-Rhône-Alpes"}


def test_extract_domain_candidates_handles_json_encoded_string_fields():
    """L'API annuaire renvoie site_internet/adresse_courriel comme des CHAÎNES contenant du JSON
    sérialisé (vérifié en direct), pas comme des objets natifs : ça doit être désérialisé."""
    record = {
        "fields": {
            "nom": "Conseil départemental - Loire",
            "adresse_courriel": "info@loire.fr",
            "site_internet": '[{"libelle": "", "valeur": "https://www.loire.fr/"}]',
        }
    }
    candidates = InstitutionEmailValidator._extract_domain_candidates(record)
    assert "loire.fr" in candidates


@pytest.mark.django_db
def test_match_annuaire_domain_parses_json_encoded_pivot():
    """Le champ 'pivot' est lui aussi une chaîne JSON sérialisée dans les vraies réponses ;
    le prendre pour un dict natif faisait planter la correspondance (AttributeError)."""
    record = {
        "fields": {
            "nom": "Mairie - Bordeaux",
            "adresse_courriel": "contact@mairie-bordeaux.fr",
            "pivot": '[{"type_service_local": "mairie", "code_insee_commune": ["33063"]}]',
        }
    }
    with patch("core.auth_validation.InstitutionEmailValidator._search_annuaire", return_value=[record]):
        match = InstitutionEmailValidator._match_annuaire_domain(
            "mairie-bordeaux.fr", "Mairie de Bordeaux"
        )
    assert match["matched"] is True
    assert match["type_service_local"] == "mairie"


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._fetch_json")
def test_departement_level_registration_validates_via_annuaire(mock_fetch):
    """Bout-en-bout : un Conseil départemental (ex: Loire, loire.fr) doit être validé via
    l'annuaire même sans code commune, en résolvant 'Loire' comme département plutôt que
    comme la commune homonyme la plus proche."""
    conseil_departemental = {
        "fields": {
            "nom": "Conseil départemental - Loire",
            "adresse_courriel": "info@loire.fr",
            "pivot": '[{"type_service_local": "cg"}]',
        }
    }

    def fake_fetch(url):
        if "/communes" in url:
            return [{"code": "49178", "nom": "Loiré"}]
        if "/departements" in url:
            return [{"code": "42", "nom": "Loire"}]
        if "api-lannuaire-administration" in url:
            return {"records": [conseil_departemental]}
        return None

    mock_fetch.side_effect = fake_fetch

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@loire.fr",
        institution_name="Conseil Général de la Loire",
        institution_type="collectivite",
        commune_name="Loire",
    )

    assert valid is True
    assert details["validation_mode"] == "annuaire"
    assert details["annuaire"]["domain"] == "loire.fr"


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_conseil_departemental_falls_back_to_name_check(mock_search):
    """Sans correspondance annuaire (mock vide), un conseil départemental doit encore passer
    la validation via la vérification nom/domaine (comme prefecture/gendarmerie/etc.)."""
    mock_search.return_value = None

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@departement-haute-savoie.fr",
        institution_name="Conseil départemental de la Haute-Savoie",
        institution_type="conseil_departemental",
    )

    assert valid is True
    assert details.get("validation_mode") != "annuaire"


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_conseil_departemental_rejects_unrelated_name(mock_search):
    mock_search.return_value = None

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@randommail.com",
        institution_name="Boulangerie du coin",
        institution_type="conseil_departemental",
    )

    assert valid is False


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_conseil_regional_falls_back_to_name_check(mock_search):
    mock_search.return_value = None

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@region-bretagne.fr",
        institution_name="Conseil régional de Bretagne",
        institution_type="conseil_regional",
    )

    assert valid is True


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_sous_prefecture_falls_back_to_name_check(mock_search):
    mock_search.return_value = None

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@sous-prefecture-thonon.fr",
        institution_name="Sous-préfecture de Thonon-les-Bains",
        institution_type="sous_prefecture",
    )

    assert valid is True


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._fetch_json")
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_communaute_de_communes_validated_via_epci_lookup(mock_search, mock_fetch):
    """Contrairement aux autres types (dépendants de etablissements-publics.api.gouv.fr,
    actuellement hors service), les EPCI (cc/métropole) sont vérifiés via geo.api.gouv.fr,
    qui répond réellement — ce test vérifie ce chemin spécifique."""
    mock_search.return_value = None
    mock_fetch.return_value = [{"nom": "CC du Genevois", "code": "200011identifier"}]

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@cc-genevois.fr",
        institution_name="CC du Genevois",
        institution_type="cc",
        commune_name="Saint-Julien-en-Genevois",
        commune_code="74258",
    )

    assert valid is True
    assert details["validation_mode"] == "opendata"


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._fetch_json")
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_metropole_falls_back_to_name_check_when_epci_lookup_empty(mock_search, mock_fetch):
    mock_search.return_value = None
    mock_fetch.return_value = None

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@metropole-lyon.fr",
        institution_name="Métropole de Lyon",
        institution_type="metropole",
    )

    assert valid is True
    assert details.get("validation_mode") != "opendata"


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_police_municipale_falls_back_to_name_check(mock_search):
    mock_search.return_value = None

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@police-municipale-annecy.fr",
        institution_name="Police municipale d'Annecy",
        institution_type="police_municipale",
    )

    assert valid is True


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_ars_email_domain_format_accepted(mock_search):
    """Domaine réel type ars.sante.fr — jeton court volontairement absent du groupe générique
    (cf. commentaire sur 'ars'/'chu'/'chr' dans validate_email_domain) : vérifie le motif dédié."""
    mock_search.return_value = None

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@iledefrance.ars.sante.fr",
        institution_name="ARS Île-de-France",
        institution_type="ars",
    )

    assert valid is True


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_ars_rejects_unrelated_name(mock_search):
    mock_search.return_value = None

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@iledefrance.ars.sante.fr",
        institution_name="Boulangerie du coin",
        institution_type="ars",
    )

    assert valid is False


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._fetch_json")
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_chu_validated_via_recherche_entreprises_public_nature_juridique(mock_search, mock_fetch):
    """Les hôpitaux publics n'ont pas d'API de recherche FINESS en direct (jeu de données
    statique uniquement) : vérifiés ici via recherche-entreprises.api.gouv.fr, en ne retenant
    que les résultats dont la catégorie juridique (nature_juridique) commence par '7'
    (personne morale de droit public), pour écarter les cliniques privées homonymes."""
    mock_search.return_value = None
    mock_fetch.return_value = {
        "results": [
            {"nom_complet": "CENTRE HOSPITALIER UNIVERSITAIRE GRENOBLE ALPES", "nature_juridique": "7364"},
            {"nom_complet": "CLINIQUE PRIVEE HOMONYME", "nature_juridique": "5710"},
        ]
    }

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@chu-grenoble.fr",
        institution_name="CHU Grenoble Alpes",
        institution_type="chu",
        commune_name="Grenoble",
        commune_code="38185",
    )

    assert valid is True
    assert details["validation_mode"] == "opendata"


@pytest.mark.django_db
@patch("core.auth_validation.InstitutionEmailValidator._fetch_json")
@patch("core.auth_validation.InstitutionEmailValidator._search_annuaire")
def test_chu_rejected_when_only_private_matches_found(mock_search, mock_fetch):
    mock_search.return_value = None
    mock_fetch.return_value = {
        "results": [
            {"nom_complet": "CLINIQUE PRIVEE FANTAISISTE", "nature_juridique": "5710"},
        ]
    }

    valid, message, details = InstitutionEmailValidator.validate_institution_account(
        email="contact@chu-fantaisiste.fr",
        institution_name="Clinique privée fantaisiste",
        institution_type="chu",
        commune_name="Grenoble",
        commune_code="38185",
    )

    assert valid is False
