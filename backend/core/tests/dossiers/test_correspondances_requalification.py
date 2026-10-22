"""Correspondances type → besoin → compétence (22/10/2026) : modifiables par les seuls
administrateurs, et une correspondance ajoutée donne aussitôt leur compétence (et une équipe
suggérée) aux dossiers encore en attente qui en manquaient."""
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    AffectationCompetence, Besoin, BesoinCompetence, Competence, Crisis, Dossier, Request, RequestType, Team,
)


def _client(create_user, type_compte, nom):
    client = APIClient()
    client.force_authenticate(user=create_user(username=f"{nom}@test.fr", email=f"{nom}@test.fr", type=type_compte))
    return client


@pytest.fixture
def hebergement(db):
    type_demande = RequestType.objects.create(type="Hébergement (test requalif)", description="")
    besoin = Besoin.objects.create(nom="Hébergement (test requalif)")
    competence = Competence.objects.create(nom="Accueil / hébergement (test requalif)")
    BesoinCompetence.objects.create(besoin=besoin, competence=competence)
    return type_demande, besoin, competence


@pytest.mark.django_db
def test_seul_un_administrateur_modifie_les_correspondances(create_user, hebergement):
    type_demande, besoin, _ = hebergement
    corps = {"request_type": str(type_demande.id), "besoin": str(besoin.id)}

    elu = _client(create_user, "AUT_LOCALE", "elu-corresp")
    assert elu.get(reverse('requesttypebesoin-list')).status_code == 200
    assert elu.post(reverse('requesttypebesoin-list'), corps, format="json").status_code == 403

    admin = _client(create_user, "ADMIN", "admin-corresp")
    assert admin.post(reverse('requesttypebesoin-list'), corps, format="json").status_code == 201


@pytest.mark.django_db
def test_correspondance_ajoutee_requalifie_les_dossiers_en_attente(create_user, hebergement):
    type_demande, besoin, competence = hebergement
    crise = Crisis.objects.create(name="Crise requalif", type="INONDATION", location=Point(4.5, 45.5, srid=4326))
    cai = Team.objects.create(name="CAI requalif")
    AffectationCompetence.objects.create(crise=crise, competence=competence, equipe=cai)
    demande = Request.objects.create(
        title="Famille à reloger", location=Point(4.5, 45.5, srid=4326), first_name_request="A", last_name_request="B",
        email_request="a@t.fr", phone_request="0600000000", request_type=type_demande, commune_code="42207", crisis=crise,
    )
    dossier = Dossier.objects.create(numero="DOS-RQ1", crise=crise, demande=demande, titre=demande.title,
                                     statut=Dossier.Statut.EN_ATTENTE_AFFECTATION)

    admin = _client(create_user, "ADMIN", "admin-requalif")
    reponse = admin.post(reverse('requesttypebesoin-list'), {"request_type": str(type_demande.id), "besoin": str(besoin.id)}, format="json")

    assert reponse.status_code == 201, reponse.data
    dossier.refresh_from_db()
    assert dossier.competence == competence and dossier.besoin == besoin
    assert dossier.equipe == cai and dossier.statut == Dossier.Statut.EN_ATTENTE_AFFECTATION   # suggérée
