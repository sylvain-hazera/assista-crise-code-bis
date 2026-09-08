import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import Besoin, BesoinCompetence, Competence, InformationType


@pytest.mark.django_db
class TestCompetenceKeywordSearch:

    def test_search_is_order_independent(self, authenticated_client):
        client, _ = authenticated_client
        Competence.objects.create(nom="Transport d'animaux")
        Competence.objects.create(nom="Nourriture et eau")

        r1 = client.get(reverse('competence-list'), {"q": "transport animaux"})
        r2 = client.get(reverse('competence-list'), {"q": "animaux transport"})

        assert r1.status_code == status.HTTP_200_OK
        names1 = {c["nom"] for c in r1.data}
        names2 = {c["nom"] for c in r2.data}
        assert names1 == names2 == {"Transport d'animaux"}

    def test_search_requires_all_tokens(self, authenticated_client):
        client, _ = authenticated_client
        Competence.objects.create(nom="Transport de matériel")
        Competence.objects.create(nom="Transport d'animaux")

        response = client.get(reverse('competence-list'), {"q": "transport animaux"})

        names = {c["nom"] for c in response.data}
        assert names == {"Transport d'animaux"}

    def test_search_expands_via_linked_besoin(self, authenticated_client):
        """Une compétence rattachée à un besoin dont le nom matche doit remonter, même si le
        mot-clé cherché n'apparaît pas dans le nom de la compétence elle-même."""
        client, _ = authenticated_client
        competence = Competence.objects.create(nom="Sauvetage")
        besoin = Besoin.objects.create(nom="Animaux en détresse")
        BesoinCompetence.objects.create(besoin=besoin, competence=competence)
        Competence.objects.create(nom="Autre compétence sans lien")

        response = client.get(reverse('competence-list'), {"q": "animaux"})

        names = {c["nom"] for c in response.data}
        assert names == {"Sauvetage"}

    def test_no_query_returns_full_list(self, authenticated_client):
        client, _ = authenticated_client
        Competence.objects.create(nom="Transport")
        Competence.objects.create(nom="Nourriture")

        response = client.get(reverse('competence-list'))

        assert len(response.data) == 2

    def test_create_reuses_case_insensitive_duplicate(self, authenticated_client):
        client, _ = authenticated_client
        existing = Competence.objects.create(nom="transport")

        response = client.post(reverse('competence-list'), {"nom": "Transport"}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(existing.id)
        assert Competence.objects.filter(nom__iexact="transport").count() == 1

    def test_create_new_theme_normalizes_whitespace(self, authenticated_client):
        client, _ = authenticated_client

        response = client.post(reverse('competence-list'), {"nom": "  Transport   Animaux  "}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["nom"] == "Transport Animaux"

    def test_anonymous_can_list_competences(self):
        """Régression : le formulaire public "Proposer mon aide" (accessible sans compte)
        affiche un champ de recherche de compétences — un visiteur anonyme doit pouvoir le
        lister/chercher, comme pour InformationType (other-declaration-form)."""
        Competence.objects.create(nom="Secourisme")
        client = APIClient()

        response = client.get(reverse('competence-list'), {"q": "secourisme"})

        assert response.status_code == status.HTTP_200_OK
        assert {c["nom"] for c in response.data} == {"Secourisme"}

    def test_anonymous_can_create_competence(self):
        """Un visiteur sans compte proposant son aide en personne doit pouvoir déclarer une
        compétence inédite, immédiatement réutilisable par d'autres ensuite — même traitement
        qu'InformationType, ouvert pour la même raison (formulaire public sans compte)."""
        client = APIClient()

        response = client.post(reverse('competence-list'), {"nom": "Nouveau theme"}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert Competence.objects.filter(nom="Nouveau theme").exists()


@pytest.mark.django_db
class TestCompetenceParent:
    """Regroupement optionnel des compétences (sous-compétences), pour l'affichage en menu
    déroulant côté équipe (voir TeamsComponent.competenceGroups)."""

    def test_parent_is_writable_and_readable(self, authenticated_client):
        client, _ = authenticated_client
        parent = Competence.objects.create(nom="Secourisme")
        enfant = Competence.objects.create(nom="PSC1")

        response = client.patch(
            reverse('competence-detail', args=[enfant.id]), {"parent": str(parent.id)}, format='json',
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["parent"] == parent.id
        enfant.refresh_from_db()
        assert enfant.parent_id == parent.id

    def test_parent_defaults_to_null(self, authenticated_client):
        client, _ = authenticated_client
        response = client.post(reverse('competence-list'), {"nom": "Autonome"}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["parent"] is None


@pytest.mark.django_db
class TestInformationTypeKeywordSearchAndPublicAccess:

    def test_anonymous_can_list_types(self):
        """Régression : la page de signalement (other-declaration-form) est publique, sans
        compte, mais chargeait un 401 sur le sélecteur de type avant ce correctif."""
        InformationType.objects.create(type="Danger imminent")
        client = APIClient()

        response = client.get(reverse('informationtype-list'))

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1

    def test_anonymous_can_create_new_type(self):
        """Un passant doit pouvoir signaler avec un type inédit (ex: 'Arbre sur la chaussée')
        sans avoir de compte, et ce type devient réutilisable par d'autres ensuite."""
        client = APIClient()

        response = client.post(reverse('informationtype-list'), {"type": "Arbre sur la chaussée"}, format='json')

        assert response.status_code == status.HTTP_201_CREATED
        assert InformationType.objects.filter(type="Arbre sur la chaussée").exists()

    def test_anonymous_create_reuses_existing_type(self):
        existing = InformationType.objects.create(type="Route inondée")
        client = APIClient()

        response = client.post(reverse('informationtype-list'), {"type": "route inondée"}, format='json')

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == str(existing.id)
        assert InformationType.objects.count() == 1

    def test_search_order_independent(self):
        InformationType.objects.create(type="Route inondée")
        InformationType.objects.create(type="Arbre sur la chaussée")
        client = APIClient()

        r1 = client.get(reverse('informationtype-list'), {"q": "route inondée"})
        r2 = client.get(reverse('informationtype-list'), {"q": "inondée route"})

        types1 = {t["type"] for t in r1.data}
        types2 = {t["type"] for t in r2.data}
        assert types1 == types2 == {"Route inondée"}
