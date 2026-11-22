"""Périmètre et acte des plans de prévention, relevés au Géoportail de l'urbanisme (18/11/2026).

Les objets simulés reprennent la forme réelle de la couche `wfs_sup:assiette_sup_s`, relevée à
la main sur une commune : aucune requête ne part pendant les essais."""
import pytest
from django.contrib.gis.geos import Point, Polygon

from core import couches_carto, geoportail_urbanisme as gpu, zonages_officiels
from core.models import Institution, InstitutionType, ServitudePPR

CONTOUR = Polygon(((4.58, 45.50), (4.66, 45.50), (4.66, 45.55), (4.58, 45.55), (4.58, 45.50)), srid=4326)


def _objet(nom, fichier, coins, categorie="pm1"):
    return {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[[list(c) for c in coins]]]},
            "properties": {"suptype": categorie, "nomsuplitt": nom, "typeass": "Enveloppe des zonages réglementaires",
                           "fichier": fichier, "partition": "130010622_SUP_42_PM1", "gpu_doc_id": "98c521eb", "idass": "PM1-1-" + fichier}}


DANS = ((4.60, 45.51), (4.63, 45.51), (4.63, 45.53), (4.60, 45.53), (4.60, 45.51))
HORS = ((4.90, 45.90), (4.95, 45.90), (4.95, 45.95), (4.90, 45.95), (4.90, 45.90))     # dans le rectangle d'un voisin, pas chez nous


@pytest.fixture
def interroger(monkeypatch):
    monkeypatch.setattr(zonages_officiels, "_attendre_son_tour", lambda: None)
    demandes = []

    def _interroger(categorie, emprise):
        demandes.append((categorie, tuple(round(x, 2) for x in emprise)))
        return [_objet("PPRNPI du Gier", "PM1_gier_20171108_act.pdf", DANS), _objet("PPR d'ailleurs", "ailleurs.pdf", HORS)] \
            if categorie == "pm1" else []
    return demandes, _interroger


@pytest.mark.django_db
class TestReleve:

    def test_on_garde_le_perimetre_et_l_adresse_de_l_acte_de_ce_qui_touche_la_commune(self, interroger):
        demandes, faux = interroger
        bilan = gpu.relever("42186", "PROD", interroger=faux, contour=CONTOUR)
        assert bilan == {"releves": 1, "erreurs": {}}
        # Les deux catégories sont demandées sur l'emprise de la commune.
        assert demandes == [("pm1", (4.58, 45.5, 4.66, 45.55)), ("pm3", (4.58, 45.5, 4.66, 45.55))]
        (plan,) = ServitudePPR.objects.all()
        assert plan.nom == "PPRNPI du Gier"
        assert plan.url_acte == "https://data.geopf.fr/annexes/gpu/documents/130010622_SUP_42_PM1/98c521eb/PM1_gier_20171108_act.pdf"

    def test_refaire_le_releve_remplace_sans_doubler(self, interroger):
        _, faux = interroger
        gpu.relever("42186", "PROD", interroger=faux, contour=CONTOUR)
        gpu.relever("42186", "PROD", interroger=faux, contour=CONTOUR)
        assert ServitudePPR.objects.count() == 1

    def test_une_panne_garde_ce_qu_on_avait(self, interroger):
        _, faux = interroger
        gpu.relever("42186", "PROD", interroger=faux, contour=CONTOUR)

        def en_panne(categorie, emprise):
            raise OSError("le service ne répond pas")
        bilan = gpu.relever("42186", "PROD", interroger=en_panne, contour=CONTOUR)
        assert set(bilan["erreurs"]) == {"pm1", "pm3"} and ServitudePPR.objects.count() == 1

    def test_on_sait_dire_quel_plan_couvre_un_point(self, interroger):
        _, faux = interroger
        gpu.relever("42186", "PROD", interroger=faux, contour=CONTOUR)
        assert gpu.plans_au_point(Point(4.61, 45.52, srid=4326), "42186", "PROD") == ["PPRNPI du Gier"]
        assert gpu.plans_au_point(Point(4.65, 45.54, srid=4326), "42186", "PROD") == []

    def test_le_perimetre_est_une_couche_cartographique_avec_son_acte(self, interroger):
        _, faux = interroger
        gpu.relever("42186", "PROD", interroger=faux, contour=CONTOUR)
        itype, _c = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        mairie = Institution.objects.create(nom="Mairie du périmètre", type=itype, commune_code="42186")
        couche = couches_carto.exporter("perimetres-ppr", mairie, "PROD")
        (objet,) = couche["features"]
        assert objet["geometry"]["type"] == "MultiPolygon" and objet["properties"]["nom"] == "PPRNPI du Gier"
        assert objet["properties"]["acte"].endswith("PM1_gier_20171108_act.pdf")

    def test_sans_contour_rien_n_est_efface(self, interroger, monkeypatch):
        _, faux = interroger
        gpu.relever("42186", "PROD", interroger=faux, contour=CONTOUR)
        monkeypatch.setattr(gpu, "contour_de_la_commune", lambda code: None)
        assert "contour" in gpu.relever("42186", "PROD", interroger=faux)["erreurs"] and ServitudePPR.objects.count() == 1


def _sup(categorie, coins, nom="", fichier=""):
    return {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[[list(c) for c in coins]]]},
            "properties": {"suptype": categorie, "nomass": nom, "typeass": "Zone de protection", "fichier": fichier,
                           "partition": "444619258_SUP_R75_I4", "gpu_doc_id": "c444"}}


@pytest.mark.django_db
class TestServitudesEtZonesDuPLU:
    """22/11/2026 : toutes les servitudes, et les zones du PLU, en plus des plans de prévention."""

    def test_toutes_les_servitudes_sauf_les_ppr_releves_a_part(self, interroger, monkeypatch):
        _, faux = interroger
        gpu.relever("42186", "PROD", interroger=faux, contour=CONTOUR)
        bilan = gpu.relever_servitudes("42186", "PROD", CONTOUR, interroger=lambda emprise: {
            "numberMatched": 3, "features": [_sup("i4", DANS, "I4_ligne_ass", "I4_act.pdf"), _sup("ac1", DANS), _sup("i4", HORS)]})
        assert bilan == {"releves": 2, "erreurs": {}}
        assert sorted(ServitudePPR.objects.values_list("categorie", flat=True)) == ["ac1", "i4", "pm1"]
        # Les écrans des plans de prévention ne voient que les plans de prévention.
        assert [p["nom"] for p in gpu.etat("42186", "PROD")] == ["PPRNPI du Gier"]
        assert gpu.plans_au_point(Point(4.61, 45.52, srid=4326), "42186", "PROD") == ["PPRNPI du Gier"]
        # Rejouer remplace, sans toucher aux plans de prévention.
        gpu.relever_servitudes("42186", "PROD", CONTOUR, interroger=lambda emprise: {"features": [_sup("t1", DANS)]})
        assert sorted(ServitudePPR.objects.values_list("categorie", flat=True)) == ["pm1", "t1"]

    def test_couches_servitudes_et_zones(self):
        gpu.relever_servitudes("42186", "PROD", CONTOUR, interroger=lambda emprise: {"features": [_sup("i4", DANS)]})
        zone = {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[[list(c) for c in DANS]]]},
                "properties": {"typezone": "U", "libelle": "UP24", "libelong": "Zones de projet", "urlfic": "https://exemple.fr/r.pdf"}}
        hors = dict(zone, geometry={"type": "MultiPolygon", "coordinates": [[[list(c) for c in HORS]]]})
        bilan = gpu.relever_zones("42186", "PROD", CONTOUR, interroger=lambda emprise: {"numberMatched": 2, "features": [zone, hors]})
        assert bilan == {"releves": 1, "erreurs": {}}
        itype, _c = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        mairie = Institution.objects.create(nom="Mairie", type=itype, commune_code="42186")
        (s,) = couches_carto.exporter("servitudes", mairie, "PROD")["features"]
        assert s["properties"]["categorie"] == "Lignes électriques"
        (z,) = couches_carto.exporter("zones-urbanisme", mairie, "PROD")["features"]
        assert z["properties"]["type"] == "U" and z["properties"]["reglement"] == "https://exemple.fr/r.pdf"
        assert couches_carto.exporter("perimetres-ppr", mairie, "PROD")["features"] == []

    def test_liste_tronquee_et_panne_signalees(self):
        bilan = gpu.relever_zones("42186", "PROD", CONTOUR, interroger=lambda e: {"numberMatched": 5000, "features": []})
        assert "incomplet" in bilan["erreurs"]

        def en_panne(emprise):
            raise OSError("muet")
        assert "servitudes" in gpu.relever_servitudes("42186", "PROD", CONTOUR, interroger=en_panne)["erreurs"]
