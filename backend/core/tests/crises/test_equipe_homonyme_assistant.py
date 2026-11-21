"""Assistant de démarrage : une « nouvelle équipe » au nom d'une équipe existante (21/11/2026).

Cinq « Équipe du poste de commandement » sont apparues sur l'instance d'exemple après cinq
passages dans l'assistant, sans le moindre avertissement. Une équipe de même nom (casse, accents
et espaces ignorés) est désormais reprise. La cellule de crise reste propre à sa crise (elle
porte le salon de la crise) : elle n'est reprise que sur la même crise, et sinon prend le nom de
la crise pour qu'on la distingue.
"""
import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, Crisis, Institution, InstitutionType, PointOperationnel, PointType, Team, User,
)


@pytest.fixture
def contexte(db):
    itype, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
    inst = Institution.objects.create(nom="Mairie homonymes", type=itype, commune_code="38185", commune_nom="Grenoble")
    user = User.objects.create_user(username="homonyme@test.fr", email="homonyme@test.fr", password="Test1234!",
                                    type="AUT_LOCALE", institution=inst)
    ContactInstitution.objects.create(institution=inst, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return inst, client


def _point(type_code, crise):
    ptype, _ = PointType.objects.get_or_create(code=type_code, defaults={"libelle": type_code})
    return PointOperationnel.objects.create(nom=f"Point {type_code}", type=ptype, crise=crise)


def _crise(nom):
    return Crisis.objects.create(name=nom, location=Point(5.7, 45.2, srid=4326))


@pytest.mark.django_db
def test_un_centre_reprend_l_equipe_de_meme_nom(contexte):
    inst, client = contexte
    existante = Team.objects.create(name="Réserve communale", institution=inst, environment="PROD")
    point = _point("CENTRE_ACCUEIL", _crise("Crue A"))
    r = client.patch(f"/api/points-operationnels/{point.id}/", {"nouvelle_equipe_nom": "  reserve COMMUNALE "}, format="json")
    assert r.status_code == 200, r.data
    assert str(r.data["equipe"]) == str(existante.id)
    assert Team.objects.filter(institution=inst).count() == 1


@pytest.mark.django_db
def test_la_cellule_d_une_autre_crise_prend_le_nom_de_sa_crise(contexte):
    inst, client = contexte
    premiere = _point("CELLULE_CRISE", _crise("Crue A"))
    client.patch(f"/api/points-operationnels/{premiere.id}/", {"nouvelle_equipe_nom": "Poste de commandement"}, format="json")
    seconde = _point("CELLULE_CRISE", _crise("Crue B"))
    r = client.patch(f"/api/points-operationnels/{seconde.id}/", {"nouvelle_equipe_nom": "Poste de commandement"}, format="json")
    assert r.status_code == 200, r.data
    noms = sorted(Team.objects.filter(institution=inst).values_list("name", flat=True))
    assert noms == ["Poste de commandement", "Poste de commandement — Crue B"]


@pytest.mark.django_db
def test_relancer_l_assistant_sur_la_meme_crise_reprend_la_cellule(contexte):
    inst, client = contexte
    crise = _crise("Crue A")
    premiere = _point("CELLULE_CRISE", crise)
    client.patch(f"/api/points-operationnels/{premiere.id}/", {"nouvelle_equipe_nom": "Poste de commandement"}, format="json")
    autre = _point("CELLULE_CRISE", crise)
    client.patch(f"/api/points-operationnels/{autre.id}/", {"nouvelle_equipe_nom": "Poste de commandement"}, format="json")
    assert Team.objects.filter(institution=inst).count() == 1
