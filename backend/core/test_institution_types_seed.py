import pytest

from core.models import InstitutionType


@pytest.mark.django_db
def test_association_and_entreprise_types_seeded():
    codes = set(InstitutionType.objects.values_list('code', flat=True))
    assert {'association', 'entreprise'}.issubset(codes)
