import pytest
from django.contrib.gis.geos import Point
from rest_framework.test import APIClient

from core.models import (
    Besoin, Competence, ContactInstitution, Crisis, Institution, InstitutionType,
    PointOperationnel, PointType, RoleOperationnel, User,
)


@pytest.mark.django_db
class TestWizardEquipeFlow:
    """Reproduit bout en bout, côté API, le flux du wizard de démarrage de crise pour une
    équipe tout juste créée — création via nouvelle_equipe_nom sur le point, puis PATCH
    themes/competences/communes + definir-mission + inviter-membre depuis le récap (voir
    crise-demarrage.component.ts:enregistrerEquipe). Écrit après un bug rapporté le 2026-09-15
    où rien de tout ça n'apparaissait sur la fiche équipe : ce test confirme que l'API elle-même
    persiste correctement chaque appel — la cause était une résolution frontend ambiguë de
    "mon institution" (via le compte connecté, en cache) au lieu de l'institution RÉELLE de
    l'équipe tout juste créée (relue via l'équipe elle-même)."""

    def test_wizard_equipe_flow_end_to_end(self):
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE_WIZARD", defaults={"libelle": "Mairie"})
        inst = Institution.objects.create(nom="Mairie Wizard", type=itype, commune_code="38185", commune_nom="Grenoble")
        user = User.objects.create_user(
            username="wizard@test.fr", email="wizard@test.fr", password="Test1234!",
            type="AUT_LOCALE", institution=inst,
        )
        ContactInstitution.objects.create(institution=inst, utilisateur=user, actif=True)

        crise = Crisis.objects.create(name="Crise wizard", location=Point(1.0, 1.0, srid=4326))
        ptype = PointType.objects.filter(code="CELLULE_CRISE").first()
        point = PointOperationnel.objects.create(nom="Mairie", type=ptype, crise=crise)

        client = APIClient()
        client.force_authenticate(user=user)

        # Étape "Équipes" du wizard : création d'une équipe à la volée sur le point.
        r_point = client.patch(f"/api/points-operationnels/{point.id}/", {"nouvelle_equipe_nom": "EquipeWizard"}, format="json")
        assert r_point.status_code == 200, r_point.data
        equipe_id = r_point.data.get("equipe")
        assert equipe_id

        besoin = Besoin.objects.create(nom="Hébergement wizard")
        competence = Competence.objects.create(nom="Secourisme wizard")
        role, _ = RoleOperationnel.objects.get_or_create(code="REGULATEUR_WIZARD", defaults={"libelle": "Régulateur"})

        # Étape "Récap" : le formulaire inline enregistrerEquipe() combine un PATCH
        # (thèmes/spécialité/zone) et deux actions dédiées (mission, invitation).
        r_patch = client.patch(f"/api/teams/{equipe_id}/", {
            "theme_ids": [str(besoin.id)], "competence_ids": [str(competence.id)], "communes": ["38185"],
        }, format="json")
        assert r_patch.status_code == 200, r_patch.data

        r_mission = client.post(f"/api/teams/{equipe_id}/definir-mission/", {
            "titre": "Accueillir les personnes évacuées", "crise_id": str(crise.id),
        }, format="json")
        assert r_mission.status_code == 200, r_mission.data

        r_invite = client.post(f"/api/teams/{equipe_id}/inviter-membre/", {
            "first_name": "Jean", "last_name": "Dupont", "email": "jean.dupont@test.fr",
            "phone_number": "0600000000", "role_code": role.code,
        }, format="json")
        assert r_invite.status_code == 201, r_invite.data

        r_commune = client.get(f"/api/crises/{crise.id}/commune/")
        assert r_commune.status_code == 200, r_commune.data
        assert "commune_code" in r_commune.data

        r_final = client.get(f"/api/teams/{equipe_id}/")
        assert r_final.status_code == 200
        assert len(r_final.data.get("member_ids", [])) == 1
        assert str(besoin.id) in [str(x) for x in r_final.data.get("theme_ids", [])]
        assert str(competence.id) in [str(x) for x in r_final.data.get("competence_ids", [])]
        assert r_final.data.get("communes") == ["38185"]
        assert r_final.data.get("mission_active_titre") == "Accueillir les personnes évacuées"
        assert r_final.data.get("assigned_crisis_ids") == [crise.id]
