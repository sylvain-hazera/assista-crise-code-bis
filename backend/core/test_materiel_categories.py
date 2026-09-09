"""Catégorisation du catalogue matériel (MaterielCatalogueCategorie, 9 nouvelles valeurs pour
le stock de centre) et filtrage par type de centre (PointType.categories_materiel_exclues) —
voir migration 0132/0133. Le mécanisme est une liste d'EXCLUSION (pas d'autorisation) :
vérifie qu'elle est bien exposée en lecture via l'API PointType, et que sa valeur par défaut
(liste vide) ne restreint rien."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import MaterielCatalogue, PointType


@pytest.mark.django_db
class TestMaterielCatalogueCategorieExposee:

    def test_categorie_accepte_les_nouvelles_valeurs(self, db):
        item = MaterielCatalogue.objects.create(nom="Test brouette", categorie="DEBLAI_MANUTENTION")
        item.full_clean()
        assert item.categorie == "DEBLAI_MANUTENTION"


@pytest.mark.django_db
class TestPointTypeCategoriesExclues:

    def test_categories_exclues_par_defaut_vide(self, db):
        point_type = PointType.objects.create(code="TEST_DEFAUT", libelle="Type test")
        assert point_type.categories_materiel_exclues == []

    def test_hebergement_seede_exclut_deblai_manutention(self, db):
        # Posé par la migration de données 0133 sur le PointType HEBERGEMENT déjà seedé
        # (0026) : un centre d'accueil des personnes n'affiche pas les engins de déblaiement.
        hebergement = PointType.objects.get(code="HEBERGEMENT")
        assert "DEBLAI_MANUTENTION" in hebergement.categories_materiel_exclues

    def test_categories_exclues_exposees_par_l_api(self, create_user, db):
        point_type = PointType.objects.create(
            code="TEST_API", libelle="Type test API", categories_materiel_exclues=["POMPAGE"],
        )
        user = create_user(username="pt-api@test.fr", email="pt-api@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse("pointtype-detail", args=[point_type.id]))

        assert response.status_code == 200
        assert response.data["categories_materiel_exclues"] == ["POMPAGE"]
