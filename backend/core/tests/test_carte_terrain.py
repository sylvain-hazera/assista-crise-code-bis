"""Le périmètre de la carte de l'application (27/11/2026) : la crise en cours de l'équipe d'abord,
sinon les crises de la commune, sinon rien."""
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.models import (
    ContactInstitution, Crisis, ImplicationInstitution, Institution, InstitutionType, Mission, StatutImplication, Team,
)


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def monde(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie de Floirac (essai)", type=itype, commune_code="33167")
    lea = create_user(username="lea-carte@test.fr", email="lea-carte@test.fr", type="VOLUNTEER")
    ContactInstitution.objects.create(institution=mairie, utilisateur=lea, actif=True)
    crue = Crisis.objects.create(name="Crue (essai)", location=Point(-0.53, 44.83), environment="PROD")
    feu = Crisis.objects.create(name="Feu (essai)", location=Point(-0.6, 44.7), environment="PROD", zone_communes=["33167"])
    loin = Crisis.objects.create(name="Tempête lointaine (essai)", location=Point(5.7, 45.2), environment="PROD")
    close = Crisis.objects.create(name="Close (essai)", location=Point(-0.53, 44.83), environment="PROD", end_date=timezone.now())
    ImplicationInstitution.objects.create(crise=crue, institution=mairie, actif=True, statut=StatutImplication.VALIDEE, environment="PROD")
    ImplicationInstitution.objects.create(crise=close, institution=mairie, actif=True, statut=StatutImplication.VALIDEE, environment="PROD")
    return {"lea": lea, "crue": crue, "feu": feu, "loin": loin, "close": close}


@pytest.mark.django_db
class TestPerimetre:
    def test_sans_engagement_les_crises_ouvertes_de_sa_commune(self, monde):
        r = _client(monde["lea"]).get(reverse("carte_terrain_perimetre"))
        assert r.status_code == 200
        assert r.data["raison"] == "commune"
        # Par implication (crue) et par zone (feu) ; ni la lointaine, ni la close.
        assert {c["nom"] for c in r.data["crises"]} == {"Crue (essai)", "Feu (essai)"}
        assert r.data["crises"][0]["latitude"] is not None

    def test_l_engagement_passe_avant_la_commune(self, monde):
        equipe = Team.objects.create(name="Alpha carte")
        equipe.members.add(monde["lea"])
        mission = Mission.objects.create(titre="Renfort", crise=monde["loin"], statut="EN_COURS", environment="PROD")
        mission.equipes.add(equipe)
        r = _client(monde["lea"]).get(reverse("carte_terrain_perimetre"))
        assert r.data["raison"] == "engagement"
        assert [c["nom"] for c in r.data["crises"]] == ["Tempête lointaine (essai)"]

    def test_mission_terminee_ne_compte_pas(self, monde):
        equipe = Team.objects.create(name="Bravo carte")
        equipe.members.add(monde["lea"])
        mission = Mission.objects.create(titre="Fini", crise=monde["loin"], statut="TERMINEE", environment="PROD")
        mission.equipes.add(equipe)
        assert _client(monde["lea"]).get(reverse("carte_terrain_perimetre")).data["raison"] == "commune"

    def test_sans_rattachement_rien(self, monde, create_user):
        seul = create_user(username="seul-carte@test.fr", email="seul-carte@test.fr", type="VOLUNTEER")
        r = _client(seul).get(reverse("carte_terrain_perimetre"))
        assert r.data == {"raison": "aucune", "crises": []}

    def test_la_formation_reste_a_part(self, monde):
        r = _client(monde["lea"]).get(reverse("carte_terrain_perimetre"), HTTP_X_ENVIRONMENT="DEMO")
        assert r.data["crises"] == []
