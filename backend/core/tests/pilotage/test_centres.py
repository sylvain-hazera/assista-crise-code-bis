"""Onglet Centres du pilotage (23/11/2026) : accueil (CARE), transit, regroupement des moyens."""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    AuditLog, Crisis, DeclarationSecurite, Institution, InstitutionType, MaterielCatalogue, MaterielPoint,
    PointOperationnel, PointType, RegistrePresence, Team, UserRole,
)


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def scene(db, create_user):
    t, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie de Voreppe", type=t, actif=True)
    autre = Institution.objects.create(nom="Mairie d'ailleurs", type=t, actif=True)
    crise = Crisis.objects.create(name="Crue", type="INONDATION", location=Point(5.6, 45.3, srid=4326))
    hebergement, _ = PointType.objects.get_or_create(code="HEBERGEMENT", defaults={"libelle": "Centre d'accueil des personnes"})
    transit, _ = PointType.objects.get_or_create(code="TRANSIT", defaults={"libelle": "Point de transit"})
    distribution, _ = PointType.objects.get_or_create(code="DISTRIBUTION", defaults={"libelle": "Distribution"})
    equipe = Team.objects.create(name="Gymnase", institution=mairie)
    gymnase = PointOperationnel.objects.create(nom="Gymnase", type=hebergement, crise=crise, equipe=equipe,
                                               capacite_accueil=10, date_ouverture=timezone.now(), actif=True)
    PointOperationnel.objects.create(nom="Parking", type=transit, crise=crise, actif=True)
    PointOperationnel.objects.create(nom="Distribution", type=distribution, crise=crise, actif=True)
    RegistrePresence.objects.create(point=gymnase, type_personne="EVACUE", nombre=7, nom="Famille Durand")
    RegistrePresence.objects.create(point=gymnase, type_personne="INTERVENANT", nombre=2)
    parti = RegistrePresence.objects.create(point=gymnase, type_personne="EVACUE", nombre=3)
    parti.date_depart = timezone.now()
    parti.save()
    eau, _ = MaterielCatalogue.objects.get_or_create(nom="Eau (pack)")
    MaterielPoint.objects.create(point=gymnase, item=eau, niveau_stock="FAIBLE")
    DeclarationSecurite.objects.create(crise=crise, situation="BESOIN_CENTRE", nombre_adultes=2, nombre_enfants=1)
    maire = create_user(username="maire-centre@test.fr", email="maire-centre@test.fr", type=UserRole.LOCAL_AUTHORITY)
    maire.institution = mairie
    maire.save()
    etranger = create_user(username="autre-centre@test.fr", email="autre-centre@test.fr", type=UserRole.LOCAL_AUTHORITY)
    etranger.institution = autre
    etranger.save()
    return {"crise": crise, "gymnase": gymnase, "maire": maire, "etranger": etranger}


@pytest.mark.django_db
class TestCentres:
    def test_la_liste_et_ses_agregats(self, scene):
        r = _client(scene["maire"]).get(reverse("pilotage-centres"), {"crise": str(scene["crise"].id)})
        assert r.status_code == 200, r.data
        assert [c["nom"] for c in r.data["centres"]] == ["Gymnase", "Parking"]     # pas la distribution
        g = r.data["centres"][0]
        assert g["etat"] == "OUVERT" and r.data["centres"][1]["etat"] == "PREVU"
        assert g["occupation"]["presents"] == 9 and g["occupation"]["taux"] == 0.9 and g["occupation"]["presque_plein"]
        assert g["occupation"]["arrivees_24h"] == 12 and g["occupation"]["departs_24h"] == 3
        assert g["manques"] == [{"article": "Eau (pack)", "niveau": "FAIBLE"}]
        assert g["peut_gerer"] and r.data["alertes"] == 1
        assert r.data["orientation"]["cherchent_un_centre"] == {"declarations": 1, "personnes": 3}

    def test_le_nom_des_accueillis_seulement_pour_qui_gere(self, scene):
        url = reverse("pilotage-centre", args=[scene["gymnase"].id])
        noms = [l["nom"] for l in _client(scene["maire"]).get(url).data["registre"]]
        assert "Famille Durand" in noms
        r = _client(scene["etranger"]).get(url)
        assert r.status_code == 200 and not r.data["peut_gerer"]
        assert all(l["nom"] is None for l in r.data["registre"])

    def test_la_cellule_de_la_mairie_enregistre_une_arrivee_et_une_sortie(self, scene):
        client = _client(scene["maire"])
        r = client.post(reverse("registrepresence-list"), {"point": str(scene["gymnase"].id), "type_personne": "EVACUE", "nombre": 1}, format="json")
        assert r.status_code == 201, r.data
        assert client.post(reverse("registrepresence-sortie", args=[r.data["id"]])).status_code in (200, 201)
        r = _client(scene["etranger"]).post(reverse("registrepresence-list"),
                                            {"point": str(scene["gymnase"].id), "type_personne": "EVACUE", "nombre": 1}, format="json")
        assert r.status_code == 403

    def test_ouvrir_fermer_et_capacite(self, scene):
        url = reverse("pilotage-centre-etat", args=[scene["gymnase"].id])
        assert _client(scene["etranger"]).post(url, {"geste": "fermer"}, format="json").status_code == 403
        r = _client(scene["maire"]).post(url, {"geste": "fermer", "capacite": 40}, format="json")
        assert r.status_code == 200 and r.data["etat"] == "FERME" and r.data["occupation"]["capacite"] == 40
        assert AuditLog.objects.filter(objet_type="PointOperationnel", objet_id=scene["gymnase"].id).exists()
        r = _client(scene["maire"]).post(url, {"geste": "ouvrir"}, format="json")
        assert r.data["etat"] == "OUVERT"

    def test_reserve_au_poste_de_commandement(self, scene, create_user):
        citoyen = create_user(username="cit-centre@test.fr", email="cit-centre@test.fr", type=UserRole.SIMPLE_USER)
        assert _client(citoyen).get(reverse("pilotage-centres"), {"crise": str(scene["crise"].id)}).status_code == 403
