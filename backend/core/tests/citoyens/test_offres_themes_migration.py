"""Migration 0367 : les offres « Bénévolat » et « Matériel » reliées aux thèmes écoutés.

Sans ces liens, un bénévole externe ne pouvait jamais choisir « Bénévolat » sur une crise dont
les institutions écoutaient le nettoyage, et l'offre d'une pompe n'était pas proposée à une
mairie qui écoutait « Pompage & citernes » (constaté en production le 21/11/2026).
"""
import importlib

import pytest
from django.apps import apps

from core.models import Besoin, OfferType, OfferTypeBesoin

migration = importlib.import_module("core.migrations.0367_offres_benevolat_materiel_themes")


@pytest.mark.django_db
def test_relie_benevolat_et_materiel_et_reste_reexecutable():
    benevolat, _ = OfferType.objects.get_or_create(type="Bénévolat")
    materiel, _ = OfferType.objects.get_or_create(type="Matériel")
    nettoyage, _ = Besoin.objects.get_or_create(nom="Nettoyage - déblaiement")
    pompage, _ = Besoin.objects.get_or_create(nom="Pompage")
    OfferTypeBesoin.objects.filter(offer_type__in=[benevolat, materiel]).delete()

    migration.relier(apps)

    assert OfferTypeBesoin.objects.filter(offer_type=benevolat, besoin=nettoyage).count() == 1
    assert OfferTypeBesoin.objects.filter(offer_type=materiel, besoin=pompage).count() == 1
    assert migration.relier(apps) == 0  # deuxième passage : aucun doublon


@pytest.mark.django_db
def test_ignore_ce_qui_n_existe_pas():
    OfferTypeBesoin.objects.all().delete()
    OfferType.objects.filter(type__in=["Bénévolat", "Matériel"]).delete()
    assert migration.relier(apps) == 0
