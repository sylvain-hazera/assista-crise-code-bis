import pytest
from django.urls import reverse
from rest_framework import status

from core.models import Notification


@pytest.mark.django_db
class TestNotificationResume:
    """Endpoint léger (compteur + horodatage) destiné à un polling fréquent côté frontend, voir
    NotificationViewSet.resume — jamais la liste complète, pour rester bon marché même appelé
    toutes les quelques secondes par plusieurs onglets."""

    def test_aucune_notification_donne_zero_et_date_nulle(self, authenticated_client):
        client, _ = authenticated_client
        response = client.get(reverse('notification-resume'))
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count_non_lues"] == 0
        assert response.data["derniere_notification_le"] is None

    def test_compte_uniquement_les_non_lues(self, authenticated_client):
        client, user = authenticated_client
        Notification.objects.create(utilisateur=user, titre="A", message="a", lu=True)
        Notification.objects.create(utilisateur=user, titre="B", message="b", lu=False)
        Notification.objects.create(utilisateur=user, titre="C", message="c", lu=False)

        response = client.get(reverse('notification-resume'))
        assert response.data["count_non_lues"] == 2

    def test_derniere_notification_le_meme_si_deja_lue(self, authenticated_client):
        """La date de la plus récente notification doit refléter TOUTE notification, même déjà
        lue (ex: lue depuis un autre onglet) — sinon le polling ne détecterait jamais ce
        changement d'état côté serveur."""
        client, user = authenticated_client
        Notification.objects.create(utilisateur=user, titre="A", message="a", lu=True)

        response = client.get(reverse('notification-resume'))
        assert response.data["count_non_lues"] == 0
        assert response.data["derniere_notification_le"] is not None

    def test_ne_compte_pas_les_notifications_d_un_autre_utilisateur(self, authenticated_client, create_user):
        client, _ = authenticated_client
        autre = create_user(username="autre@test.fr", email="autre@test.fr")
        Notification.objects.create(utilisateur=autre, titre="Pas pour moi", message="x", lu=False)

        response = client.get(reverse('notification-resume'))
        assert response.data["count_non_lues"] == 0
        assert response.data["derniere_notification_le"] is None

    def test_anonyme_refuse(self, api_client):
        response = api_client.get(reverse('notification-resume'))
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
