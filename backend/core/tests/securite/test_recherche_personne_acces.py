"""Décision utilisateur du 2026-09-18 (revue RGPD, /rgpd) : la page RGPD décrivait déjà
RecherchePersonne comme "réservé aux comptes institutionnels", mais le code (IsAuthenticated
seul, sur les 5 viewsets RecherchePersonne*) permettait en réalité à n'importe quel compte
authentifié d'y accéder — écart corrigé ici pour que le code corresponde au texte."""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import RecherchePersonne, RecherchePersonneCommentaire, RecherchePersonneHistorique


@pytest.fixture
def recherche(db, create_user):
    createur = create_user(username="createur-acces@test.fr", email="createur-acces@test.fr", type="UTIL_SIMPLE")
    return RecherchePersonne.objects.create(
        nom="Martin", prenom="Alice", age=42, source="DOMICILE", ville="Testville",
        contact_nom="Contact test", contact_email="contact-acces@test.fr", contact_telephone="0600000000",
        createur=createur,
    )


@pytest.fixture
def simple_client(create_user):
    user = create_user(username="simple-acces@test.fr", email="simple-acces@test.fr", type="UTIL_SIMPLE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def institutionnel_client(create_user):
    user = create_user(username="institutionnel-acces@test.fr", email="institutionnel-acces@test.fr", type="AUT_LOCALE")
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestAccesRecherchePersonne:
    def test_liste_refusee_a_un_compte_non_institutionnel(self, simple_client):
        response = simple_client.get(reverse('recherchepersonne-list'))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_liste_autorisee_a_un_compte_institutionnel(self, institutionnel_client, recherche):
        response = institutionnel_client.get(reverse('recherchepersonne-list'))
        assert response.status_code == status.HTTP_200_OK

    def test_detail_refuse_a_un_compte_non_institutionnel(self, simple_client, recherche):
        response = simple_client.get(reverse('recherchepersonne-detail', args=[recherche.id]))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_creation_autorisee_a_un_compte_non_institutionnel(self, simple_client):
        """Revu le 08/10 (voir le commentaire de RecherchePersonneViewSet.get_permissions) : le
        DÉPÔT d'une fiche de recherche doit rester ouvert à tout compte authentifié, qu'il soit
        institutionnel ou non -- un citoyen peut signaler la disparition d'un proche sans être
        rattaché à une institution. Seules la consultation et la gestion du registre restent
        réservées aux acteurs institutionnels (voir test_liste_refusee_a_un_compte_non_institutionnel
        et test_detail_refuse_a_un_compte_non_institutionnel ci-dessus)."""
        response = simple_client.post(reverse('recherchepersonne-list'), {
            "nom": "Test", "prenom": "X", "age": 30, "source": "DOMICILE", "ville": "Testville",
            "contact_nom": "C", "contact_email": "c@test.fr", "contact_telephone": "0600000000",
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED

    def test_anonyme_refuse(self, recherche):
        client = APIClient()
        response = client.get(reverse('recherchepersonne-list'))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.django_db
class TestAccesRecherchePersonneCommentaireEtHistorique:
    def test_commentaires_refuses_a_un_compte_non_institutionnel(self, simple_client, recherche, create_user):
        auteur = create_user(username="auteur-commentaire-acces@test.fr", email="auteur-commentaire-acces@test.fr", type="UTIL_SIMPLE")
        RecherchePersonneCommentaire.objects.create(recherche=recherche, commentaire="Test", auteur=auteur)
        response = simple_client.get(reverse('recherchepersonnecommentaire-list'))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_historique_refuse_a_un_compte_non_institutionnel(self, simple_client, recherche):
        RecherchePersonneHistorique.objects.create(recherche=recherche, evenement="Créée")
        response = simple_client.get(reverse('recherchepersonnehistorique-list'))
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_commentaires_autorises_a_un_compte_institutionnel(self, institutionnel_client, recherche):
        response = institutionnel_client.get(reverse('recherchepersonnecommentaire-list'))
        assert response.status_code == status.HTTP_200_OK
