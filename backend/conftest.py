import pytest
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from core.models import RequestType, OfferType, InformationType

User = get_user_model()

@pytest.fixture
def api_client():
    """Client API pour les tests"""
    return APIClient()


@pytest.fixture(autouse=True)
def _inscription_sans_controle_anti_robot(settings):
    """La création de compte passe par un contrôle anti-robot (core/defi_inscription.py) qui
    compte les demandes par adresse : laissé actif, il ferait dépendre chaque test qui crée
    plus de trois comptes d'une règle qui ne le concerne pas. Coupé pour toute la suite ; les
    tests du contrôle lui-même le rallument (tests/securite/test_defi_inscription.py)."""
    settings.INSCRIPTION_DEFI_ACTIF = False


@pytest.fixture(autouse=True)
def _reset_geo_resolution_budget():
    """core.geo_lookup._budget est un threading.local posé par GeoResolutionBudgetMiddleware à
    CHAQUE requête HTTP réelle (donc jamais un problème en production) — mais pytest exécute
    tous les tests dans le même process/thread : un test appelant un endpoint (donc passant par
    le middleware) épuise le budget pour le reste de la suite, faisant échouer silencieusement
    tout test suivant qui appelle core.geo_lookup directement (sans requête HTTP pour le
    réinitialiser). Autouse : protège toute la suite, pas seulement les tests qui connaissent
    ce mécanisme (voir l'incident du 14/09 constaté sur test_geo_lookup_db_cache.py/
    test_commune_risques.py après l'ajout du budget)."""
    from core.geo_lookup import _budget
    if hasattr(_budget, "remaining"):
        del _budget.remaining
    yield
    if hasattr(_budget, "remaining"):
        del _budget.remaining

@pytest.fixture
def user_data():
    """Données utilisateur pour les tests"""
    return {
        'username': 'test@test.com',
        'email': 'test@test.com',
        'password': 'TestPass123!',
        'first_name': 'Test',
        'last_name': 'User',
        'type': 'UTIL_SIMPLE',
        'phone_number': '0123456789',
        'postal_code': '38000',
    }

@pytest.fixture
def create_user(db, user_data):
    """Fixture pour créer un utilisateur"""
    def make_user(**kwargs):
        data = user_data.copy()
        data.update(kwargs)
        password = data.pop('password')
        user = User.objects.create_user(**data)
        user.set_password(password)
        user.enabled = True
        user.save()
        return user
    return make_user

@pytest.fixture
def authenticated_client(api_client, create_user):
    """Client authentifié"""
    user = create_user()
    api_client.force_authenticate(user=user)
    return api_client, user

@pytest.fixture
def request_type(db):
    """Créer un type de demande"""
    return RequestType.objects.create(
        type='Aide urgente',
        description='Demande d\'aide urgente'
    )

@pytest.fixture
def offer_type(db):
    """Créer un type d'offre"""
    return OfferType.objects.create(
        type='Hébergement',
        description='Offre d\'hébergement'
    )

@pytest.fixture
def information_type(db):
    """Créer un type d'information"""
    return InformationType.objects.create(
        type='Info utile',
        description='Information utile'
    )


# ── Garde-fou : aucun tri SQL sur une colonne chiffrée ───────────────────────────────────────
# Le tri porterait sur le texte chiffré, donc dans un ordre aléatoire, sans erreur. Les filtres
# et recherches sont gardés par EncryptedTextField.get_lookup ; le tri ne passe pas par là,
# d'où ce contrôle au moment où la requête est compilée (essais seulement).
def _colonnes(expression):
    from django.db.models.expressions import Col
    if isinstance(expression, Col):
        yield expression
    for enfant in getattr(expression, "get_source_expressions", lambda: [])():
        if enfant is not None:
            yield from _colonnes(enfant)


@pytest.fixture(autouse=True, scope="session")
def _pas_de_tri_sur_colonne_chiffree():
    from django.db.models.sql.compiler import SQLCompiler
    from core.crypto_fields import EncryptedTextField, RequeteSurChampChiffre

    origine = SQLCompiler.get_order_by

    def get_order_by(self):
        resultat = origine(self)
        for expression, _ in resultat:
            for colonne in _colonnes(expression):
                if isinstance(colonne.target, EncryptedTextField):
                    raise RequeteSurChampChiffre(
                        f"Tri SQL sur la colonne chiffrée {colonne.target.model.__name__}.{colonne.target.name} : "
                        "trier en Python après déchiffrement.")
        return resultat

    SQLCompiler.get_order_by = get_order_by
    yield
    SQLCompiler.get_order_by = origine
