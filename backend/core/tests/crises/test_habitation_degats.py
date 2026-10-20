"""Référencement des dégâts (demande utilisateur du 20/10/2026) : relevés successifs des surfaces
et de la valeur, valeurs foncières DVF indicatives, export CSV des adresses impactées d'une crise."""
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.urls import reverse
from rest_framework.test import APIClient

from core import dvf
from core.models import Crisis, Habitation, HabitationHistorique

ENTETE_DVF = (
    "id_mutation,date_mutation,nature_mutation,valeur_fonciere,id_parcelle,type_local,surface_reelle_bati\n"
)
CSV_DVF = ENTETE_DVF + (
    "M1,2024-03-01,Vente,200000,99001000AB0001,Maison,100\n"          # 2 000 €/m²
    "M1,2024-03-01,Vente,200000,99001000AB0001,Dépendance,\n"          # dépendance admise
    "M2,2024-05-01,Vente,300000,99001000AB0002,Maison,100\n"          # 3 000 €/m²
    "M3,2024-06-01,Vente,150000,99001000AB0003,Appartement,50\n"      # 3 000 €/m²
    "M4,2024-07-01,Vente,500000,99001000AB0004,Maison,100\n"          # vente groupée : exclue
    "M4,2024-07-01,Vente,500000,99001000AB0005,Maison,90\n"
    "M5,2024-08-01,Vente,1,99001000AB0006,Maison,100\n"               # prix symbolique : exclu
    "M6,2024-09-01,Echange,250000,99001000AB0007,Maison,100\n"        # pas une vente : exclue
)


@pytest.fixture(autouse=True)
def vider_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def admin_client(create_user):
    admin = create_user(username="admin-degats@test.fr", email="admin-degats@test.fr", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=admin)
    return client


@pytest.fixture
def crise():
    return Crisis.objects.create(name="Crue test", type="INONDATION", location="POINT (5.0 45.0)")


def _habitation(crise, **champs):
    return Habitation.objects.create(
        adresse=champs.pop("adresse", "1 rue Test"), commune_code="99001", crise=crise,
        location=Point(5.0, 45.0, srid=4326), environment="PROD", **champs,
    )


def _telecharger_simule(code_commune, annee):
    return CSV_DVF if annee == 2024 else None


@pytest.mark.django_db
class TestReleve:

    def test_releves_successifs_gardes_dans_l_historique(self, admin_client, crise):
        h = _habitation(crise)
        url = reverse("habitation-releve", args=[h.id])

        r1 = admin_client.post(url, {"surface_habitable_totale": 120, "surface_habitable_impactee": 40}, format="json")
        r2 = admin_client.post(url, {"surface_habitable_impactee": 80, "valeur_estimee": "240000",
                                     "valeur_source": "DVF médiane communale"}, format="json")

        assert r1.status_code == 200 and r2.status_code == 200, (r1.data, r2.data)
        h.refresh_from_db()
        assert h.surface_habitable_totale == 120 and h.surface_habitable_impactee == 80
        assert h.valeur_source == "DVF médiane communale"
        releves = list(HabitationHistorique.objects.filter(habitation=h).order_by("date_creation")
                       .values_list("commentaire", flat=True))
        assert len(releves) == 2
        assert "40 m² impactés sur 120 m²" in releves[0]
        assert "80 m² impactés sur 120 m²" in releves[1] and "240 000 €" in releves[1]

    def test_surface_impactee_superieure_a_la_totale_refusee(self, admin_client, crise):
        h = _habitation(crise, surface_non_habitable_totale=20)
        r = admin_client.post(reverse("habitation-releve", args=[h.id]),
                              {"surface_non_habitable_impactee": 30}, format="json")
        assert r.status_code == 400
        assert "dépasse" in r.data["error"]

    def test_valeur_manuelle_par_defaut(self, admin_client, crise):
        h = _habitation(crise)
        admin_client.post(reverse("habitation-releve", args=[h.id]), {"valeur_estimee": 150000}, format="json")
        h.refresh_from_db()
        assert h.valeur_source == "Saisie manuelle"

    def test_valeur_negative_refusee(self, admin_client, crise):
        h = _habitation(crise)
        r = admin_client.post(reverse("habitation-releve", args=[h.id]), {"surface_habitable_totale": -5}, format="json")
        assert r.status_code == 400

    def test_anonyme_refuse(self, crise):
        h = _habitation(crise)
        r = APIClient().post(reverse("habitation-releve", args=[h.id]), {"surface_habitable_totale": 50}, format="json")
        assert r.status_code == 401


@pytest.mark.django_db
class TestDvf:

    def test_prix_median_communal(self):
        with patch.object(dvf, "_telecharger", side_effect=_telecharger_simule):
            resultat = dvf.prix_commune("99001")
        assert resultat["erreur"] is None
        assert resultat["annees"] == [2024]
        assert resultat["maison"] == {"prix_m2_median": 2500, "nb_ventes": 2}
        assert resultat["appartement"] == {"prix_m2_median": 3000, "nb_ventes": 1}
        assert resultat["ensemble"]["nb_ventes"] == 3

    def test_estimation_habitation_et_ventes_de_la_parcelle(self, admin_client, crise):
        h = _habitation(crise, surface_habitable_totale=80, parcelle_cadastrale="99001000AB0002")
        with patch.object(dvf, "_telecharger", side_effect=_telecharger_simule):
            r = admin_client.get(reverse("habitation-dvf", args=[h.id]))
        assert r.status_code == 200
        assert r.data["valeur_indicative"] == 200000          # 80 m² × 2 500 €/m²
        assert r.data["ventes_parcelle"] == [{"date": "2024-05-01", "type": "Maison", "valeur": 300000.0, "surface": 100.0}]

    def test_sans_surface_pas_d_estimation(self, admin_client, crise):
        h = _habitation(crise)
        with patch.object(dvf, "_telecharger", side_effect=_telecharger_simule):
            r = admin_client.get(reverse("habitation-dvf", args=[h.id]))
        assert r.data["valeur_indicative"] is None
        assert r.data["maison"]["prix_m2_median"] == 2500

    def test_commune_non_couverte(self, admin_client):
        with patch.object(dvf, "_telecharger", return_value=None):
            r = admin_client.get(reverse("habitation-prix-dvf"), {"commune_code": "67482"})
        assert r.status_code == 200
        assert r.data["erreur"]


@pytest.mark.django_db
class TestExportCsv:

    def test_seules_les_adresses_impactees(self, admin_client, crise):
        _habitation(crise, adresse="1 rue Touchée", statut_evaluation="DEGATS_FORTS")
        _habitation(crise, adresse="2 rue Sèche", statut_evaluation="PAS_DE_DEGATS")
        _habitation(crise, adresse="3 rue Mesurée", surface_habitable_totale=100, surface_habitable_impactee=12.5)
        autre_crise = Crisis.objects.create(name="Autre", type="INONDATION", location="POINT (5.0 45.0)")
        _habitation(autre_crise, adresse="4 rue Ailleurs", statut_evaluation="DEGATS_FORTS")

        r = admin_client.get(reverse("habitation-export-csv"), {"crise": str(crise.id)})

        assert r.status_code == 200
        assert r["Content-Type"].startswith("text/csv")
        texte = r.content.decode("utf-8-sig")
        assert "1 rue Touchée" in texte and "3 rue Mesurée" in texte
        assert "2 rue Sèche" not in texte and "4 rue Ailleurs" not in texte
        assert "12,5" in texte   # virgule décimale pour le tableur

    def test_toutes_les_adresses(self, admin_client, crise):
        _habitation(crise, adresse="2 rue Sèche", statut_evaluation="PAS_DE_DEGATS")
        r = admin_client.get(reverse("habitation-export-csv"), {"crise": str(crise.id), "toutes": "1"})
        assert "2 rue Sèche" in r.content.decode("utf-8-sig")

    def test_crise_obligatoire(self, admin_client):
        assert admin_client.get(reverse("habitation-export-csv")).status_code == 400

    def test_sans_delegation_refuse(self, create_user, crise):
        _habitation(crise, statut_evaluation="DEGATS_FORTS")
        simple = create_user(username="simple-degats@test.fr", email="simple-degats@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=simple)
        assert client.get(reverse("habitation-export-csv"), {"crise": str(crise.id)}).status_code == 403
