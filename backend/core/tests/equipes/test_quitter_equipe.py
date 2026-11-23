"""Quitter une équipe sans rien supprimer (23/11/2026)."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import AuditLog, Mission, Team, UserRole


@pytest.mark.django_db
def test_quitter_l_equipe_garde_l_equipe_et_ses_missions(create_user):
    moi = create_user(username="quitte@test.fr", email="quitte@test.fr", type=UserRole.SIMPLE_USER)
    autre = create_user(username="reste@test.fr", email="reste@test.fr", type=UserRole.SIMPLE_USER)
    equipe = Team.objects.create(name="Voirie", leader=moi)
    equipe.members.add(moi, autre)
    mission = Mission.objects.create(titre="Points de transit")
    mission.equipes.add(equipe)
    client = APIClient()
    client.force_authenticate(user=moi)

    r = client.post(reverse("team-quitter", args=[equipe.id]))

    assert r.status_code == 200 and set(r.data["roles"]) == {"membre", "chef d'équipe"}
    equipe.refresh_from_db()
    assert list(equipe.members.all()) == [autre] and equipe.leader is None
    assert Mission.objects.filter(pk=mission.pk, equipes=equipe).exists()
    assert AuditLog.objects.filter(objet_type="Team", objet_id=equipe.id).exists()
    assert client.post(reverse("team-quitter", args=[equipe.id])).status_code == 400
    # Et la mission n'est plus dans les miennes.
    donnees = client.get(reverse("mission-list")).data
    liste = donnees.get("results", []) if isinstance(donnees, dict) else donnees
    assert str(mission.id) not in {str(m["id"]) for m in liste}
