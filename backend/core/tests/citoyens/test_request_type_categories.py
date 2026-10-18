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
            "Télécommunication", "Pompage", "Cuve / citerne mobile",
            "Bulldozer à lame", "Broyeur", "Déchaumeur", "Cover crop", "Manitou",
        }

    def test_generic_engin_tracte_replaced_by_named_engins(self):
        """"Engin/machine tracté(e)" (0095, générique) remplacé par les entrées précises listées
        ci-dessus (0097), cohérence avec la liste à cocher côté offres (MaterielCatalogue)."""
        assert not RequestType.objects.filter(type="Engin/machine tracté(e)").exists()
        assert not Besoin.objects.filter(nom="Engin/machine tracté(e)").exists()

    def test_cuve_renamed_to_cuve_citerne_mobile(self):
        """Anciennement "Cuve" (0042) — même ligne (pas de doublon), renommée pour préciser
        qu'elle sert aussi bien à l'eau qu'au carburant (voir 0095)."""
        assert not RequestType.objects.filter(type="Cuve").exists()
        cuve = RequestType.objects.get(type="Cuve / citerne mobile")
        assert cuve.parent.type == "Matériel"
        assert "eau" in cuve.description.lower() and "carburant" in cuve.description.lower()
        assert not Besoin.objects.filter(nom="Cuve").exists()
        assert Besoin.objects.filter(nom="Cuve / citerne mobile").exists()

    def test_transport_has_animaux_child(self):
        transport = RequestType.objects.get(type="Transport")
        children = set(transport.sous_categories.values_list('type', flat=True))
        assert "Transport d'animaux" in children

    def test_interpretariat_has_expected_children(self):
        parent = RequestType.objects.get(type="Interprétariat / traduction")
        children = set(parent.sous_categories.values_list('type', flat=True))
        assert children == {"Anglais", "Français", "Espagnol", "Italien"}

    def test_leaf_categories_have_matching_besoin_mapping(self):
        """Chaque nouvelle sous-catégorie doit être routable : un Besoin du même nom, relié
        via RequestTypeBesoin, sinon l'auto-affectation (perform_create) ne trouve jamais de
        compétence et le dossier reste sans équipe."""
        for nom in ["Groupe électrogène", "Pompage", "Anglais", "Espagnol",
                    "Cuve / citerne mobile", "Bulldozer à lame", "Manitou", "Transport d'animaux"]:
            request_type = RequestType.objects.get(type=nom)
            besoin = Besoin.objects.get(nom=nom)
            assert RequestTypeBesoin.objects.filter(request_type=request_type, besoin=besoin).exists()

    def test_water_and_childcare_not_added(self):
        """Décision explicite de l'utilisateur : eau potable et garde d'enfants écartées."""
        assert not RequestType.objects.filter(type__icontains="Eau potable").exists()
        assert not RequestType.objects.filter(type__icontains="Garde d'enfants").exists()
