import pytest

from core.models import Besoin, RequestType, RequestTypeBesoin


@pytest.mark.django_db
class TestRequestTypeCategorySeed:

    def test_new_top_level_categories_exist(self):
        noms = {"Accompagnement administratif", "Soutien aux animaux",
                "Hébergement d'urgence pour animaux", "Interprétariat / traduction"}
        for nom in noms:
            rt = RequestType.objects.get(type=nom)
            assert rt.parent is None

    def test_materiel_has_expected_children(self):
        materiel = RequestType.objects.get(type="Matériel")
        children = set(materiel.sous_categories.values_list('type', flat=True))
        assert children == {
            "Groupe électrogène", "Starlink / connexion satellite",
            "Télécommunication", "Pompage", "Cuve",
        }

    def test_interpretariat_has_expected_children(self):
        parent = RequestType.objects.get(type="Interprétariat / traduction")
        children = set(parent.sous_categories.values_list('type', flat=True))
        assert children == {"Anglais", "Français", "Espagnol", "Italien"}

    def test_leaf_categories_have_matching_besoin_mapping(self):
        """Chaque nouvelle sous-catégorie doit être routable : un Besoin du même nom, relié
        via RequestTypeBesoin, sinon l'auto-affectation (perform_create) ne trouve jamais de
        compétence et le dossier reste sans équipe."""
        for nom in ["Groupe électrogène", "Pompage", "Anglais", "Espagnol"]:
            request_type = RequestType.objects.get(type=nom)
            besoin = Besoin.objects.get(nom=nom)
            assert RequestTypeBesoin.objects.filter(request_type=request_type, besoin=besoin).exists()

    def test_water_and_childcare_not_added(self):
        """Décision explicite de l'utilisateur : eau potable et garde d'enfants écartées."""
        assert not RequestType.objects.filter(type__icontains="Eau potable").exists()
        assert not RequestType.objects.filter(type__icontains="Garde d'enfants").exists()
