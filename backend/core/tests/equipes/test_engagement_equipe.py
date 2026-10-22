"""Démarrer l'engagement / mettre au repos (page Cellule de crise) -- 22/10/2026 : l'engagement
était bien enregistré mais TeamSerializer n'exposait pas engagement_debut, la réponse ne le
contenait donc pas et le bouton semblait sans effet."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import Team


@pytest.mark.django_db
def test_demarrer_puis_mettre_au_repos_renvoie_engagement_debut(create_user):
    admin = create_user(username="admin-engagement@test.fr", email="admin-engagement@test.fr", type="ADMIN")
    equipe = Team.objects.create(name="Équipe engagement")
    client = APIClient()
    client.force_authenticate(user=admin)

    reponse = client.post(reverse('team-demarrer-engagement', args=[equipe.id]))
    assert reponse.status_code == 200
    assert reponse.data['engagement_debut'] is not None

    reponse = client.post(reverse('team-mettre-au-repos', args=[equipe.id]))
    assert reponse.status_code == 200
    assert reponse.data['engagement_debut'] is None


@pytest.mark.django_db
def test_engagement_debut_non_modifiable_par_simple_mise_a_jour(create_user):
    admin = create_user(username="admin-engagement2@test.fr", email="admin-engagement2@test.fr", type="ADMIN")
    equipe = Team.objects.create(name="Équipe engagement 2")
    client = APIClient()
    client.force_authenticate(user=admin)

    client.patch(reverse('team-detail', args=[equipe.id]), {"engagement_debut": "2026-01-01T00:00:00Z"}, format='json')

    equipe.refresh_from_db()
    assert equipe.engagement_debut is None
