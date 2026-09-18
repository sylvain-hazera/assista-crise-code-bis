"""Décisions utilisateur du 2026-09-18 (crise incendie de Saumos, .113) :
1) une commune qui se raccroche à une crise (IMPLIQUE ou ACTEUR) voit la zone de la crise
   s'étendre automatiquement sur son propre territoire (_etendre_zone_crise_pour_implication) ;
2) un utilisateur d'une collectivité ne peut pas retirer de la zone la contribution d'une AUTRE
   collectivité (CrisisViewSet.perform_update) — seul un administrateur global peut le faire à
   sa place."""
import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, ContributionZoneCommune, Crisis, ImplicationInstitution, Institution,
    InstitutionType,
)


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(
        name="Crise Saumos test", type="INCENDIE", location="POINT (5.72 45.18)",
    )


@pytest.fixture
def mairie_a(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie A", type=itype, commune_code="33390")


@pytest.fixture
def mairie_b(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie B", type=itype, commune_code="33200")


@pytest.fixture
def user_mairie_a(create_user, mairie_a):
    user = create_user(username="mairie-a-zone@test.fr", email="mairie-a-zone@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=mairie_a, utilisateur=user, actif=True)
    return user


@pytest.fixture
def user_mairie_b(create_user, mairie_b):
    user = create_user(username="mairie-b-zone@test.fr", email="mairie-b-zone@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=mairie_b, utilisateur=user, actif=True)
    return user


@pytest.fixture
def admin_user(create_user):
    return create_user(username="admin-zone@test.fr", email="admin-zone@test.fr", type="ADMIN")


@pytest.mark.django_db
class TestExtensionAutomatiqueZone:
    def test_declaration_impliquee_etend_la_zone(self, user_mairie_a, mairie_a, crisis):
        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(mairie_a.id), "type_implication": "IMPLIQUE"},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED, response.data
        crisis.refresh_from_db()
        assert "33390" in crisis.zone_communes
        contribution = ContributionZoneCommune.objects.get(crise=crisis, commune_code="33390")
        assert contribution.institution == mairie_a

    def test_ne_duplique_pas_si_deja_present(self, user_mairie_a, mairie_a, crisis):
        crisis.zone_communes = ["33390"]
        crisis.save(update_fields=['zone_communes'])
        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(mairie_a.id), "type_implication": "IMPLIQUE"},
            format='json',
        )
        crisis.refresh_from_db()
        assert crisis.zone_communes.count("33390") == 1

    def test_declaration_acteur_en_attente_netend_pas_avant_validation(self, create_user, crisis):
        itype, _ = InstitutionType.objects.get_or_create(code="aasc-zone", defaults={"libelle": "AASC"})
        association = Institution.objects.create(nom="Association zone", type=itype, commune_code="33390")
        membre = create_user(username="membre-asso-zone@test.fr", email="membre-asso-zone@test.fr", type="SECOURS")
        ContactInstitution.objects.create(institution=association, utilisateur=membre, actif=True)

        client = APIClient()
        client.force_authenticate(user=membre)
        response = client.post(
            reverse('implicationinstitution-list'),
            {"crise": str(crisis.id), "institution": str(association.id), "type_implication": "ACTEUR"},
            format='json',
        )
        assert response.status_code == status.HTTP_201_CREATED
        crisis.refresh_from_db()
        assert "33390" not in crisis.zone_communes

    def test_validation_dune_declaration_en_attente_etend_la_zone(self, create_user, crisis, user_mairie_a, mairie_a):
        # user_mairie_a devient régulateur AUT_LOCALE de la crise via son implication.
        ImplicationInstitution.objects.create(
            crise=crisis, institution=mairie_a, type_implication="IMPLIQUE", utilisateur=user_mairie_a, actif=True,
        )
        itype, _ = InstitutionType.objects.get_or_create(code="aasc-zone-2", defaults={"libelle": "AASC"})
        association = Institution.objects.create(nom="Association zone 2", type=itype, commune_code="33200")
        implication = ImplicationInstitution.objects.create(
            crise=crisis, institution=association, type_implication="ACTEUR", statut="EN_ATTENTE", actif=True,
        )

        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        response = client.post(reverse('implicationinstitution-valider', args=[implication.id]))
        assert response.status_code == status.HTTP_200_OK, response.data
        crisis.refresh_from_db()
        assert "33200" in crisis.zone_communes

    def test_changement_de_type_via_patch_etend_la_zone(self, user_mairie_a, mairie_a, crisis):
        implication = ImplicationInstitution.objects.create(
            crise=crisis, institution=mairie_a, type_implication="ACTEUR", utilisateur=user_mairie_a, actif=True,
        )
        assert "33390" not in crisis.zone_communes

        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        response = client.patch(
            reverse('implicationinstitution-detail', args=[implication.id]),
            {"type_implication": "IMPLIQUE"}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK, response.data
        crisis.refresh_from_db()
        assert "33390" in crisis.zone_communes


@pytest.mark.django_db
class TestProtectionRetraitZone:
    def _url(self, crisis):
        return reverse('crisis-detail', args=[crisis.id])

    def test_ne_peut_pas_retirer_la_contribution_dune_autre_collectivite(self, user_mairie_a, mairie_a, mairie_b, crisis):
        crisis.zone_communes = ["33390", "33200"]
        crisis.save(update_fields=['zone_communes'])
        ContributionZoneCommune.objects.create(crise=crisis, commune_code="33200", institution=mairie_b)

        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        response = client.patch(self._url(crisis), {"zone_communes": ["33390"]}, format='json')

        assert response.status_code == status.HTTP_403_FORBIDDEN
        crisis.refresh_from_db()
        assert "33200" in crisis.zone_communes

    def test_peut_retirer_sa_propre_contribution(self, user_mairie_a, mairie_a, crisis):
        crisis.zone_communes = ["33390"]
        crisis.save(update_fields=['zone_communes'])
        ContributionZoneCommune.objects.create(crise=crisis, commune_code="33390", institution=mairie_a)

        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        response = client.patch(self._url(crisis), {"zone_communes": []}, format='json')

        assert response.status_code == status.HTTP_200_OK, response.data
        crisis.refresh_from_db()
        assert crisis.zone_communes == []
        assert not ContributionZoneCommune.objects.filter(crise=crisis, commune_code="33390").exists()

    def test_peut_retirer_une_commune_sans_proprietaire_trace(self, user_mairie_a, crisis):
        crisis.zone_communes = ["12345"]
        crisis.save(update_fields=['zone_communes'])
        # Pas de ContributionZoneCommune pour "12345" — jamais tracée, librement retirable.

        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        response = client.patch(self._url(crisis), {"zone_communes": []}, format='json')
        assert response.status_code == status.HTTP_200_OK, response.data

    def test_administrateur_peut_retirer_nimporte_quelle_contribution(self, admin_user, mairie_b, crisis):
        crisis.zone_communes = ["33200"]
        crisis.save(update_fields=['zone_communes'])
        ContributionZoneCommune.objects.create(crise=crisis, commune_code="33200", institution=mairie_b)

        client = APIClient()
        client.force_authenticate(user=admin_user)
        response = client.patch(self._url(crisis), {"zone_communes": []}, format='json')
        assert response.status_code == status.HTTP_200_OK, response.data

    def test_ajout_manuel_de_sa_propre_commune_trace_la_provenance(self, user_mairie_a, mairie_a, crisis):
        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        response = client.patch(self._url(crisis), {"zone_communes": ["33390"]}, format='json')
        assert response.status_code == status.HTTP_200_OK, response.data
        contribution = ContributionZoneCommune.objects.get(crise=crisis, commune_code="33390")
        assert contribution.institution == mairie_a

    def test_ajout_manuel_dune_commune_tierce_ne_trace_aucun_proprietaire(self, user_mairie_a, crisis):
        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        response = client.patch(self._url(crisis), {"zone_communes": ["99999"]}, format='json')
        assert response.status_code == status.HTTP_200_OK, response.data
        contribution = ContributionZoneCommune.objects.get(crise=crisis, commune_code="99999")
        assert contribution.institution is None


@pytest.mark.django_db
class TestFusionnerZone:
    def _url(self, crisis):
        return reverse('crisis-fusionner-zone', args=[crisis.id])

    def test_sans_zone_existante_adopte_le_nouveau_trace(self, user_mairie_a, crisis):
        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        wkt = "POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0))"
        response = client.post(self._url(crisis), {"wkt": wkt}, format='json')
        assert response.status_code == status.HTTP_200_OK, response.data
        crisis.refresh_from_db()
        assert crisis.zone is not None

    def test_trace_chevauchant_fusionne_en_un_seul_polygone(self, user_mairie_a, crisis):
        crisis.zone = "POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0))"
        crisis.save(update_fields=['zone'])
        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        wkt = "POLYGON ((1 1, 1 3, 3 3, 3 1, 1 1))"
        response = client.post(self._url(crisis), {"wkt": wkt}, format='json')
        assert response.status_code == status.HTTP_200_OK, response.data
        crisis.refresh_from_db()
        assert crisis.zone.geom_type == 'Polygon'
        # Le point (0.5, 0.5) était dans l'ancienne zone, (2.5, 2.5) dans le nouveau tracé —
        # les deux doivent être couverts par la zone fusionnée.
        from django.contrib.gis.geos import Point
        assert crisis.zone.contains(Point(0.5, 0.5))
        assert crisis.zone.contains(Point(2.5, 2.5))

    def test_trace_disjoint_refuse_avec_un_message_clair(self, user_mairie_a, crisis):
        crisis.zone = "POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0))"
        crisis.save(update_fields=['zone'])
        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        wkt = "POLYGON ((10 10, 10 12, 12 12, 12 10, 10 10))"
        response = client.post(self._url(crisis), {"wkt": wkt}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "fusionner" in response.data['detail']
        crisis.refresh_from_db()
        assert crisis.zone.geom_type == 'Polygon'
        from django.contrib.gis.geos import Point
        assert crisis.zone.contains(Point(0.5, 0.5))

    def test_wkt_invalide_refuse(self, user_mairie_a, crisis):
        client = APIClient()
        client.force_authenticate(user=user_mairie_a)
        response = client.post(self._url(crisis), {"wkt": "PAS_DU_WKT"}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_refuse_a_un_non_institutionnel(self, create_user, crisis):
        simple = create_user(username="simple-zone@test.fr", email="simple-zone@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=simple)
        response = client.post(self._url(crisis), {"wkt": "POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0))"}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN
