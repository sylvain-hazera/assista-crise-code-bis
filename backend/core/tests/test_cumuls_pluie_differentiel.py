"""Cumuls de pluie écrits en différentiel (25/11/2026) : la table n'est plus effacée et réécrite à
chaque image radar (des dizaines de Go de journal de transactions par jour, NAS plein)."""
import datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.models import CumulPluieCommune, PluieCommunesImage
from core.orages import derniere_image_pluie, ecrire_cumuls


@pytest.mark.django_db
def test_seules_les_communes_qui_changent_sont_reecrites():
    h1 = timezone.now() - datetime.timedelta(minutes=5)
    assert ecrire_cumuls({"42218": (1.0, 2.0, 3.0), "42186": (0.0, 0.0, 1.0)}, h1) == {"retirees": 0, "changees": 0, "creees": 2}
    h2 = timezone.now()
    bilan = ecrire_cumuls({"42218": (1.5, 2.5, 3.5), "42186": (0.0, 0.0, 1.0), "43157": (0.0, 0.5, 0.5)}, h2)
    assert bilan == {"retirees": 0, "changees": 1, "creees": 1}
    assert CumulPluieCommune.objects.get(commune_code="42186").heure == h1        # inchangée : pas réécrite
    assert CumulPluieCommune.objects.get(commune_code="42218").mm_1h == 1.5
    assert ecrire_cumuls({"43157": (0.0, 0.5, 0.5)}, h2) == {"retirees": 2, "changees": 0, "creees": 0}
    assert list(CumulPluieCommune.objects.values_list("commune_code", flat=True)) == ["43157"]


@pytest.mark.django_db
def test_rien_ne_change_aucune_ecriture():
    h = timezone.now()
    ecrire_cumuls({"42218": (1.0, 2.0, 3.0)}, h)
    with CaptureQueriesContext(connection) as requetes:
        ecrire_cumuls({"42218": (1.0, 2.0, 3.0)}, h)
    ecritures = [q["sql"] for q in requetes.captured_queries if q["sql"].lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE"))]
    assert ecritures == []


@pytest.mark.django_db
def test_fraicheur_lue_sur_la_derniere_image():
    assert derniere_image_pluie() is None
    h = timezone.now()
    PluieCommunesImage.objects.create(heure=h, valeurs={})
    assert derniere_image_pluie() == h
