import pytest

from core.models import InstitutionType


@pytest.mark.django_db
def test_association_and_entreprise_types_seeded():
    codes = set(InstitutionType.objects.values_list('code', flat=True))
    assert {'association', 'entreprise'}.issubset(codes)


@pytest.mark.django_db
def test_official_verified_types_seeded():
    """Ces codes doivent matcher exactement `type_service_local` tel que renvoyé par
    l'annuaire officiel de l'administration, pour que la création automatique d'institution
    (institution_attachment.resolve_or_create_institution_from_annuaire) réutilise ces lignes
    plutôt que d'en dupliquer de nouvelles."""
    codes = set(InstitutionType.objects.values_list('code', flat=True))
    assert {'gendarmerie', 'prefecture', 'sous_pref', 'cg', 'cr', 'epci'}.issubset(codes)


@pytest.mark.django_db
def test_sante_and_police_municipale_types_seeded():
    codes = set(InstitutionType.objects.values_list('code', flat=True))
    assert {'police_municipale', 'ars_antenne', 'chu'}.issubset(codes)
