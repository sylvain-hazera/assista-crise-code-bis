import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import RequestType


@pytest.mark.django_db
class TestRequestTypePublicAccess:

    def test_anonymous_can_list_request_types(self):
        """Régression : le formulaire public 'demander de l'aide' (request-help-form) n'a
        pas de garde d'authentification, mais RequestTypeViewSet renvoyait 401 à tout
        visiteur anonyme — d'où le menu 'Choisissez votre besoin' vide en pratique."""
        RequestType.objects.get_or_create(type="QA Transport Test")
        client = APIClient()

        response = client.get(reverse('requesttype-list'))

        assert response.status_code == status.HTTP_200_OK
        assert any(t["type"] == "QA Transport Test" for t in response.data)

    def test_inactive_request_type_hidden_from_list(self):
        """Même patron que OfferType.actif : un type désactivé (ex: 'Soins médicaux', voir
        migration 0085) reste en base (FK PROTECT depuis Request) mais disparaît du
        formulaire public."""
        RequestType.objects.get_or_create(type="QA Type Désactivé", defaults={"actif": False})
        client = APIClient()

        response = client.get(reverse('requesttype-list'))

        assert response.status_code == status.HTTP_200_OK
        assert not any(t["type"] == "QA Type Désactivé" for t in response.data)

    def test_assistance_immediate_migration_renames_in_place(self):
        """Migration 0086 : renomme le RequestType existant plutôt que d'en créer un nouveau
        (les Request existantes le référencent via une FK PROTECT). Pas de ligne seedée par une
        migration Django (seulement par entrypoint.sh, qui ne tourne pas pour les tests) : on
        exerce donc directement la fonction de migration sur une ligne créée ici. Import par
        importlib car un nom de module ne peut pas commencer par un chiffre en Python."""
        import importlib
        from django.apps import apps as live_apps
        migration = importlib.import_module("core.migrations.0086_rename_requesttype_assistance_immediate")

        original = RequestType.objects.create(type="Assistance immédiate")
        migration.rename(apps=live_apps, schema_editor=None)
        original.refresh_from_db()
        assert original.type == "Assistance à évacuation"

    def test_soins_medicaux_deactivation_migration(self):
        """Migration 0085 : désactivé plutôt que supprimé (FK PROTECT depuis Request)."""
        import importlib
        from django.apps import apps as live_apps
        migration = importlib.import_module("core.migrations.0085_deactivate_requesttype_soins_medicaux")

        soins = RequestType.objects.create(type="Soins médicaux")
        migration.deactivate(apps=live_apps, schema_editor=None)
        soins.refresh_from_db()
        assert soins.actif is False
