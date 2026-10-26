"""Ce qu'un visiteur ANONYME voit dans la liste publique des demandes (26/10/2026).

La liste est volontairement ouverte (carte publique), et les coordonnées en sont bien retirées.
Deux champs échappaient pourtant au masquage, constatés en production :
  - `author_nom`, le nom en clair de l'auteur de la fiche ;
  - `email_request_bidx`, l'index aveugle de son adresse — un identifiant stable qui permet de
    recouper les dépôts d'une même personne.
"""
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Crisis, Request, RequestType


@pytest.fixture
def demande(db, create_user):
    auteur = create_user(username="denis@exposition.fr", email="denis@exposition.fr",
                         type="AUT_LOCALE", first_name="Denis", last_name="Lapeyre")
    crise = Crisis.objects.create(name="Crise exposition", type="INCENDIE",
                                  location=Point(5.72, 45.18, srid=4326))
    type_demande = RequestType.objects.create(type="Besoin exposition", description="")
    return Request.objects.create(
        title="Besoin d'une cuve", location=Point(5.72, 45.18, srid=4326),
        first_name_request="Denis", last_name_request="Lapeyre",
        email_request="denis@exposition.fr", phone_request="0600000000",
        request_type=type_demande, commune_code="33503", crisis=crise, author=auteur,
    )


@pytest.mark.django_db
class TestListePubliqueDesDemandes:

    def _anonyme(self):
        return APIClient().get(reverse('request-list')).data

    def test_aucun_nom_d_auteur_pour_un_anonyme(self, demande):
        fiches = self._anonyme()

        assert len(fiches) == 1
        assert fiches[0]['author_nom'] is None
        assert fiches[0]['first_name_request'] is None
        assert fiches[0]['last_name_request'] is None

    def test_aucun_index_aveugle_exposé(self, demande):
        fiches = self._anonyme()

        assert [c for c in fiches[0] if c.endswith('_bidx')] == []

    def test_un_compte_institutionnel_garde_le_nom_de_l_auteur(self, demande, create_user):
        client = APIClient()
        client.force_authenticate(user=create_user(
            username="cadre-expo@test.fr", email="cadre-expo@test.fr", type="ADMIN"))

        fiches = client.get(reverse('request-list'), {"avec_coordonnees": "1"}).data

        assert fiches[0]['author_nom'] == "Denis Lapeyre"
        assert [c for c in fiches[0] if c.endswith('_bidx')] == []
