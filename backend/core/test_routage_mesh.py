"""Sélection du meilleur companion MeshCore pour joindre un contact — core/routage_mesh.py.
Voir la discussion du 2026-09-18 (régions/ACL MeshCore en France) : aucune notion protocolaire
de région n'existe, region_tag est une simple étiquette communautaire posée à la main."""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    CompagnonMeshCore, ContactInstitution, ContactMeshCore, Institution, InstitutionType,
    MessageMeshLog,
)
from core.routage_mesh import meilleur_compagnon_pour_contact


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="TEST_ROUTAGE", defaults={"libelle": "Test"})
    return Institution.objects.create(nom="Mairie Routage", type=itype)


@pytest.fixture
def autre_institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="TEST_ROUTAGE_2", defaults={"libelle": "Test 2"})
    return Institution.objects.create(nom="Mairie Routage Autre", type=itype)


@pytest.fixture
def acteur_client(create_user, institution):
    user = create_user(username="routage@test.fr", email="routage@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestMeilleurCompagnonPourContact:
    def test_aucun_companion_actif(self):
        resultat = meilleur_compagnon_pour_contact(pubkey_hex="abc123")
        assert resultat.compagnon is None
        assert "aucun companion actif" in resultat.raison

    def test_repli_sur_principal_sans_contact_ni_region(self, institution):
        CompagnonMeshCore.objects.create(nom="Secondaire", connexion_type="TCP", institution=institution)
        principal = CompagnonMeshCore.objects.create(
            nom="Principal", connexion_type="TCP", institution=institution, principal=True,
        )
        resultat = meilleur_compagnon_pour_contact(institution=institution)
        assert resultat.compagnon == principal
        assert "principal" in resultat.raison

    def test_repli_sur_premier_actif_sans_principal(self, institution):
        seul = CompagnonMeshCore.objects.create(nom="Seul", connexion_type="TCP", institution=institution)
        resultat = meilleur_compagnon_pour_contact(institution=institution)
        assert resultat.compagnon == seul

    def test_contact_deja_entendu_prioritaire_sur_principal(self, institution):
        principal = CompagnonMeshCore.objects.create(
            nom="Principal", connexion_type="TCP", institution=institution, principal=True,
        )
        autre = CompagnonMeshCore.objects.create(nom="Autre", connexion_type="TCP", institution=institution)
        ContactMeshCore.objects.create(compagnon=autre, pubkey_hex="node1", nombre_sauts=2)

        resultat = meilleur_compagnon_pour_contact(pubkey_hex="node1", institution=institution)
        assert resultat.compagnon == autre
        assert "déjà entendu" in resultat.raison

    def test_prefere_le_companion_avec_le_moins_de_sauts(self, institution):
        loin = CompagnonMeshCore.objects.create(nom="Loin", connexion_type="TCP", institution=institution)
        proche = CompagnonMeshCore.objects.create(nom="Proche", connexion_type="TCP", institution=institution)
        ContactMeshCore.objects.create(compagnon=loin, pubkey_hex="node2", nombre_sauts=4)
        ContactMeshCore.objects.create(compagnon=proche, pubkey_hex="node2", nombre_sauts=1)

        resultat = meilleur_compagnon_pour_contact(pubkey_hex="node2", institution=institution)
        assert resultat.compagnon == proche

    def test_sauts_inconnus_relegues_derriere_un_chemin_confirme(self, institution):
        inconnu = CompagnonMeshCore.objects.create(nom="Inconnu", connexion_type="TCP", institution=institution)
        confirme = CompagnonMeshCore.objects.create(nom="Confirme", connexion_type="TCP", institution=institution)
        ContactMeshCore.objects.create(compagnon=inconnu, pubkey_hex="node3", nombre_sauts=None)
        ContactMeshCore.objects.create(compagnon=confirme, pubkey_hex="node3", nombre_sauts=3)

        resultat = meilleur_compagnon_pour_contact(pubkey_hex="node3", institution=institution)
        assert resultat.compagnon == confirme

    def test_repli_sur_la_region_si_aucun_contact_direct_connu(self, institution):
        principal = CompagnonMeshCore.objects.create(
            nom="Principal", connexion_type="TCP", institution=institution, principal=True,
        )
        regional = CompagnonMeshCore.objects.create(
            nom="Regional", connexion_type="TCP", institution=institution, region_tag="fr-naq",
        )
        resultat = meilleur_compagnon_pour_contact(pubkey_hex="jamais-entendu", region_tag="fr-naq", institution=institution)
        assert resultat.compagnon == regional
        assert resultat.region_tag == "fr-naq"
        assert "région fr-naq" in resultat.raison

    def test_ne_choisit_jamais_un_companion_dune_autre_institution(self, institution, autre_institution):
        CompagnonMeshCore.objects.create(nom="Étranger", connexion_type="TCP", institution=autre_institution, principal=True)
        resultat = meilleur_compagnon_pour_contact(institution=institution)
        assert resultat.compagnon is None


@pytest.mark.django_db
class TestActionMeilleurPourContact:
    def _url(self):
        return reverse('compagnonmeshcore-meilleur-pour-contact')

    def test_400_sans_parametre(self, acteur_client):
        client, _ = acteur_client
        response = client.get(self._url())
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_suggere_le_bon_companion(self, acteur_client, institution):
        client, _ = acteur_client
        compagnon = CompagnonMeshCore.objects.create(
            nom="Régional", connexion_type="TCP", institution=institution, region_tag="fr-naq",
        )
        response = client.get(self._url(), {"region_tag": "fr-naq"})
        assert response.status_code == status.HTTP_200_OK
        assert response.data["compagnon_id"] == str(compagnon.id)

    def test_ne_suggere_pas_un_companion_dune_autre_institution(self, acteur_client, autre_institution):
        CompagnonMeshCore.objects.create(
            nom="Étranger", connexion_type="TCP", institution=autre_institution, region_tag="fr-naq", principal=True,
        )
        client, _ = acteur_client
        response = client.get(self._url(), {"region_tag": "fr-naq"})
        assert response.data["compagnon_id"] is None


@pytest.mark.django_db
class TestAutoResolutionMessageMeshLog:
    def _url(self):
        return reverse('messagemeshlog-list')

    def test_message_sortant_sans_compagnon_est_auto_resolu(self, acteur_client, institution):
        client, _ = acteur_client
        compagnon = CompagnonMeshCore.objects.create(
            nom="Auto", connexion_type="TCP", institution=institution, principal=True,
        )
        response = client.post(self._url(), {
            "direction": "SORTANT", "contact_pubkey_hex": "abcd", "contenu": "salut",
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data
        message = MessageMeshLog.objects.get(id=response.data["id"])
        assert message.compagnon_id == compagnon.id

    def test_compagnon_explicite_nest_jamais_ecrase(self, acteur_client, institution):
        client, _ = acteur_client
        CompagnonMeshCore.objects.create(nom="Auto", connexion_type="TCP", institution=institution, principal=True)
        choisi = CompagnonMeshCore.objects.create(nom="Choisi à la main", connexion_type="TCP", institution=institution)
        response = client.post(self._url(), {
            "direction": "SORTANT", "contact_pubkey_hex": "abcd", "contenu": "salut", "compagnon": str(choisi.id),
        }, format='json')
        assert response.status_code == status.HTTP_201_CREATED, response.data
        message = MessageMeshLog.objects.get(id=response.data["id"])
        assert message.compagnon_id == choisi.id

    def test_400_si_aucun_companion_disponible(self, acteur_client):
        client, _ = acteur_client
        response = client.post(self._url(), {
            "direction": "SORTANT", "contact_pubkey_hex": "abcd", "contenu": "salut",
        }, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
