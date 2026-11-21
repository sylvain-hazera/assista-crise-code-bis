"""Une campagne de disponibilité vue par un membre qui n'a pas encore de fiche de ressource.

Constaté le 21/11/2026 en jouant le parcours du bénévole : la demande n'apparaissait pas, la
grille disait seulement « complétez d'abord votre fiche ». Le membre visé ne savait donc pas
qu'on lui demandait quelque chose. La demande s'affiche désormais, et la ressource est créée à
sa première réponse.
"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    CampagneDisponibilite, CibleCampagne, ContactInstitution, DisponibiliteOffre, EchelonCiblage,
    Institution, InstitutionType, MotifCampagne, Offer,
)


@pytest.fixture
def asso(db):
    t, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="Réserve essai sans fiche", type=t)


@pytest.fixture
def membre(create_user, asso):
    u = create_user(username="sans-fiche@test.fr", email="sans-fiche@test.fr", type="SECOURS")
    ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True)
    return u


@pytest.fixture
def campagne(asso, membre):
    c = CampagneDisponibilite.objects.create(
        institution=asso, intitule="Renfort crue", motif=MotifCampagne.CRISE_A_VENIR,
        periode_debut=timezone.localdate() + datetime.timedelta(days=1),
        periode_fin=timezone.localdate() + datetime.timedelta(days=3),
        echelon=EchelonCiblage.NATIONAL, environment="PROD")
    CibleCampagne.objects.create(campagne=c, utilisateur=membre, environment="PROD")
    return c


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.mark.django_db
def test_la_demande_s_affiche_sans_fiche_de_ressource(membre, campagne):
    assert not Offer.objects.filter(author=membre).exists()
    r = _client(membre).get(reverse("mes_disponibilites"), {"campagne": str(campagne.id)})
    assert r.status_code == 200
    assert r.data["campagne"]["intitule"] == "Renfort crue"
    assert len(r.data["jours"]) == 3
    assert r.data["ressources"] == []


@pytest.mark.django_db
def test_la_premiere_reponse_cree_la_ressource(membre, campagne, asso):
    jour = campagne.periode_debut
    r = _client(membre).post(reverse("mes_disponibilites"),
                             {"date": jour.isoformat(), "creneau": "MATIN", "disponible": True,
                              "campagne": str(campagne.id)}, format="json")
    assert r.status_code in (200, 201), r.data
    offre = Offer.objects.get(author=membre, institution=asso)
    assert DisponibiliteOffre.objects.filter(offer=offre, date=jour).exists()


@pytest.mark.django_db
def test_sans_campagne_rien_ne_change(membre):
    r = _client(membre).get(reverse("mes_disponibilites"))
    assert r.data["ressources"] == [] and r.data["jours"] == []


@pytest.mark.django_db
def test_une_campagne_qui_ne_le_vise_pas_ne_cree_rien(create_user, campagne):
    autre = create_user(username="non-cible@test.fr", email="non-cible@test.fr", type="SECOURS")
    r = _client(autre).post(reverse("mes_disponibilites"),
                            {"date": campagne.periode_debut.isoformat(), "creneau": "MATIN",
                             "disponible": True, "campagne": str(campagne.id)}, format="json")
    assert r.status_code == 400
    assert not Offer.objects.filter(author=autre).exists()
