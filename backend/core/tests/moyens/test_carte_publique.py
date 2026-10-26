"""Centres visibles sans authentification (PointOperationnelViewSet.carte_publique).

Alimente à la fois la carte et le récapitulatif de la page d'accueil (26/10/2026) : c'est la
seule information de la plateforme sur laquelle un habitant se déplace physiquement, donc un
centre fermé ne doit jamais y figurer, et aucune donnée interne (responsable, contact, équipe,
note interne) ne doit fuiter dans la réponse.
"""
import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import Crisis, PointOperationnel, PointType


@pytest.fixture
def crise_ouverte(db):
    return Crisis.objects.create(
        name="Crise carte publique", type="INONDATION", location="POINT (5.72 45.18)",
    )


@pytest.fixture
def crise_terminee(db):
    return Crisis.objects.create(
        name="Crise terminée carte publique", type="INONDATION",
        location="POINT (5.72 45.18)", end_date=timezone.now(),
    )


@pytest.fixture
def type_hebergement(db):
    return PointType.objects.get_or_create(
        code="HEBERGEMENT", defaults={"libelle": "Centre d'accueil"},
    )[0]


def _point(crise, type_point, nom="Gymnase", **kwargs):
    return PointOperationnel.objects.create(
        nom=nom, type=type_point, crise=crise, actif=True,
        location="POINT (5.72 45.18)", **kwargs,
    )


def _noms(response):
    return {p["nom"] for p in response.data}


@pytest.mark.django_db
class TestCartePublique:

    def test_visiteur_anonyme_voit_les_centres_ouverts(self, crise_ouverte, type_hebergement):
        _point(crise_ouverte, type_hebergement, nom="Gymnase ouvert",
                adresse="12 rue de la Mairie, Grenoble", capacite_accueil=80)

        response = APIClient().get(reverse('pointoperationnel-carte-publique'))

        assert response.status_code == 200
        assert "Gymnase ouvert" in _noms(response)

    def test_centre_d_une_crise_terminee_est_masque(self, crise_terminee, type_hebergement):
        """Une crise close garde ses centres en base (historique, export) : les annoncer encore
        au public enverrait des gens devant une porte fermée."""
        _point(crise_terminee, type_hebergement, nom="Gymnase crise finie")

        response = APIClient().get(reverse('pointoperationnel-carte-publique'))

        assert "Gymnase crise finie" not in _noms(response)

    def test_centre_dont_la_fermeture_est_passee_est_masque(self, crise_ouverte, type_hebergement):
        _point(crise_ouverte, type_hebergement, nom="Gymnase refermé",
                date_fermeture=timezone.now() - timezone.timedelta(hours=2))

        response = APIClient().get(reverse('pointoperationnel-carte-publique'))

        assert "Gymnase refermé" not in _noms(response)

    def test_fermeture_a_venir_reste_visible(self, crise_ouverte, type_hebergement):
        """Une fermeture programmée pour ce soir ne doit pas faire disparaître le centre
        maintenant : il est ouvert, on y envoie encore des gens."""
        _point(crise_ouverte, type_hebergement, nom="Gymnase ferme ce soir",
                date_fermeture=timezone.now() + timezone.timedelta(hours=6))

        response = APIClient().get(reverse('pointoperationnel-carte-publique'))

        assert "Gymnase ferme ce soir" in _noms(response)

    def test_centre_inactif_est_masque(self, crise_ouverte, type_hebergement):
        point = _point(crise_ouverte, type_hebergement, nom="Gymnase inactif")
        PointOperationnel.objects.filter(pk=point.pk).update(actif=False)

        response = APIClient().get(reverse('pointoperationnel-carte-publique'))

        assert "Gymnase inactif" not in _noms(response)

    def test_les_champs_servent_le_recapitulatif_public(self, crise_ouverte, type_hebergement):
        """Ce dont la page d'accueil a besoin pour qu'un habitant s'y rende : où c'est, ce que
        le centre fait, combien de places, et à quelle crise il se rattache."""
        _point(
            crise_ouverte, type_hebergement, nom="Gymnase complet",
            description="Accueil de jour et de nuit, repas chauds.",
            adresse="12 rue de la Mairie, Grenoble",
            capacite_accueil=80, accepte_animaux=True,
        )

        response = APIClient().get(reverse('pointoperationnel-carte-publique'))
        fiche = next(p for p in response.data if p["nom"] == "Gymnase complet")

        assert fiche["description"] == "Accueil de jour et de nuit, repas chauds."
        assert fiche["adresse"] == "12 rue de la Mairie, Grenoble"
        assert fiche["crise_nom"] == "Crise carte publique"
        assert fiche["capacite_accueil"] == 80
        assert fiche["accepte_animaux"] is True
        assert fiche["latitude"] is not None and fiche["longitude"] is not None

    def test_aucune_donnee_interne_n_est_exposee(self, crise_ouverte, type_hebergement):
        _point(crise_ouverte, type_hebergement, nom="Gymnase discret",
                commentaire="Code du portail : 1234. Référent joignable au 0600000000.")

        response = APIClient().get(reverse('pointoperationnel-carte-publique'))
        fiche = next(p for p in response.data if p["nom"] == "Gymnase discret")

        for champ in ("commentaire", "responsable", "responsables", "responsables_contacts",
                      "equipe", "equipes_gestion", "competences_requises"):
            assert champ not in fiche, champ
        corps = str(response.data)
        assert "1234" not in corps
        assert "0600000000" not in corps

    def test_la_liste_complete_reste_fermee_aux_anonymes(self):
        """Seules les deux actions publiques le sont : la liste détaillée ne doit pas s'ouvrir
        au passage."""
        response = APIClient().get(reverse('pointoperationnel-list'))

        assert response.status_code in (401, 403)
