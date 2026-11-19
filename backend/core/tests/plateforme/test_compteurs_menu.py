"""Compteurs du menu latéral et « crise ouverte » (revue du menu, 19/11/2026)."""
import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, Crisis, ImplicationInstitution, Institution, InstitutionType, TypeImplication,
)

URL = "/api/compteurs-menu/"


@pytest.fixture
def maire(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie des compteurs", type=itype, commune_code="42186")
    compte = create_user(username="maire@compteurs.fr", email="maire@compteurs.fr", type="AUT_LOCALE")
    compte.institution = mairie
    compte.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=compte, actif=True)
    return compte


def _client(compte):
    client = APIClient()
    client.force_authenticate(user=compte)
    return client


@pytest.mark.django_db
def test_hors_crise_le_menu_le_sait(maire):
    reponse = _client(maire).get(URL)
    assert reponse.status_code == 200
    assert set(reponse.data) == {"signalements", "messages_a_relire", "demandes_mobilisation", "crise_ouverte"}
    assert reponse.data["crise_ouverte"] is False
    # Des nombres, pas None : aucun contrôle de droits n'a refusé en silence.
    for cle in ("signalements", "messages_a_relire", "demandes_mobilisation"):
        assert isinstance(reponse.data[cle], int), cle


@pytest.mark.django_db
def test_une_crise_ouverte_de_l_institution_est_vue_et_plus_une_fois_close(maire):
    crise = Crisis.objects.create(name="Crue", type="INONDATION", location=Point(4.6, 45.5, srid=4326))
    ImplicationInstitution.objects.create(crise=crise, institution=maire.institution, responsable=maire,
                                          type_implication=TypeImplication.ACTEUR, actif=True)
    assert _client(maire).get(URL).data["crise_ouverte"] is True
    from django.utils import timezone
    Crisis.objects.filter(pk=crise.pk).update(end_date=timezone.now())
    assert _client(maire).get(URL).data["crise_ouverte"] is False


@pytest.mark.django_db
def test_un_citoyen_n_a_aucun_compteur_et_aucune_erreur(create_user):
    citoyen = create_user(username="c@compteurs.fr", email="c@compteurs.fr", type="UTIL_SIMPLE")
    reponse = _client(citoyen).get(URL)
    assert reponse.status_code == 200
    assert reponse.data["messages_a_relire"] in (None, 0) and reponse.data["crise_ouverte"] is False
