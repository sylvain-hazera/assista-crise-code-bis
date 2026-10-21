"""Consultation globale + export CSV de la main courante (AuditLogViewSet, mode "browse" —
sans ?objet_type=&objet_id=). La main courante GÉNÉRALE (toutes institutions confondues) n'est
visible que du super-admin Django (`is_superuser`) ; un acteur institutionnel non super-admin ne
voit que les AuditLog de SA PROPRE institution (`request.user.institution`), jamais celles d'une
institution tierce. Le mode "fiche précise" existant (avec objet_type+objet_id) n'est pas
touché — voir test_vue_mairie et consorts pour ce comportement historique."""
import csv
import io

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import AuditAction, AuditLog, Crisis, Institution, InstitutionType


def _make_log(utilisateur=None, action_code="CREATION", objet_type="Crisis", commentaire="", institution=None):
    action, _ = AuditAction.objects.get_or_create(code=action_code, defaults={"libelle": action_code})
    return AuditLog.objects.create(
        utilisateur=utilisateur, action=action, objet_type=objet_type,
        commentaire=commentaire, environment="PROD", institution=institution,
    )


def _make_institution(nom="Institution test"):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "MAIRIE"})
    return Institution.objects.create(nom=nom, type=itype)


@pytest.mark.django_db
class TestAuditLogBrowseMode:

    def test_non_superuser_without_institution_gets_empty_list(self, create_user):
        Crisis.objects.create(name="Une crise", type="INONDATION", location="POINT (5.72 45.18)")
        user = create_user(username="regul-browse@test.fr", email="regul-browse@test.fr", type="REGULATEUR")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('auditlog-list'))
        assert response.status_code == 200
        assert response.data == []

    def test_superuser_sees_everything_paginated(self, create_user):
        _make_log()
        admin = create_user(username="admin-browse@test.fr", email="admin-browse@test.fr", type="ADMIN", is_superuser=True)
        client = APIClient()
        client.force_authenticate(user=admin)

        # Sans ?page= : comportement non paginé, mais toujours restreint au super-admin.
        response = client.get(reverse('auditlog-list'))
        assert response.status_code == 200
        assert len(response.data) >= 1

        paginated = client.get(reverse('auditlog-list'), {"page": 1, "page_size": 5})
        # count_plafonne : voir MainCourantePagination -- sous le seuil, comptage exact (False).
        assert set(paginated.data.keys()) == {"count", "count_plafonne", "next", "previous", "results"}
        assert paginated.data["count_plafonne"] is False

    def test_institutional_actor_only_sees_own_institution(self, create_user):
        """Un acteur institutionnel (non super-admin) ne doit voir QUE les actes rattachés à sa
        propre institution — jamais ceux d'une institution tierce, ni les actes sans institution
        (formulaire public anonyme, par exemple)."""
        mon_institution = _make_institution("Ma mairie")
        autre_institution = _make_institution("Autre mairie")
        _make_log(commentaire="Chez moi", institution=mon_institution)
        _make_log(commentaire="Chez l'autre", institution=autre_institution)
        _make_log(commentaire="Sans institution", institution=None)

        user = create_user(
            username="aut-locale@test.fr", email="aut-locale@test.fr", type="AUT_LOCALE",
            institution=mon_institution,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('auditlog-list'))

        assert response.status_code == 200
        commentaires = [e["commentaire"] for e in response.data]
        assert commentaires == ["Chez moi"]

    def test_filter_by_action(self, create_user):
        _make_log(action_code="CREATION")
        _make_log(action_code="SUPPRESSION")
        admin = create_user(username="admin-filter-action@test.fr", email="admin-filter-action@test.fr", type="ADMIN", is_superuser=True)
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get(reverse('auditlog-list'), {"action": "CREATION", "objet_type": "Crisis"})
        assert response.status_code == 200
        assert len(response.data) >= 1
        assert all(e["action_code"] == "CREATION" for e in response.data)

    def test_filter_by_utilisateur(self, create_user):
        admin = create_user(username="admin-filter-user@test.fr", email="admin-filter-user@test.fr", type="ADMIN", is_superuser=True)
        _make_log(utilisateur=admin)
        client = APIClient()
        client.force_authenticate(user=admin)

        matching = client.get(reverse('auditlog-list'), {"utilisateur": "admin-filter-user"})
        assert matching.status_code == 200
        assert len(matching.data) >= 1

        not_matching = client.get(reverse('auditlog-list'), {"utilisateur": "personne-inexistante-xyz"})
        assert not_matching.data == []

    def test_filter_by_utilisateur_ne_parcourt_pas_le_registre(self, create_user, django_assert_max_num_queries):
        """Le filtre « Utilisateur » doit déchiffrer les COMPTES, jamais les lignes de journal :
        la version précédente lisait l'email de chaque ligne du registre filtré, ce qui ne
        revenait plus du tout sur la table de production (2,5 M de lignes, > 60 s le
        21/10/2026). Le nombre de requêtes ne doit donc pas dépendre du volume du registre."""
        admin = create_user(username="admin-cout-user@test.fr", email="admin-cout-user@test.fr", type="ADMIN", is_superuser=True)
        autre = create_user(username="autre-cout-user@test.fr", email="autre-cout-user@test.fr", type="AUT_LOCALE")
        for _ in range(30):
            _make_log(utilisateur=admin)
            _make_log(utilisateur=autre)
        client = APIClient()
        client.force_authenticate(user=admin)

        with django_assert_max_num_queries(12):
            reponse = client.get(reverse('auditlog-list'), {"utilisateur": "admin-cout-user", "page": 1, "page_size": 10})

        assert reponse.status_code == 200
        assert reponse.data["count"] == 30
        assert all(e["utilisateur_email"] == "admin-cout-user@test.fr" for e in reponse.data["results"])


@pytest.mark.django_db
class TestMainCourantePagination:
    """Comptage et navigation d'un registre volumineux -- voir core/pagination.py
    (MainCourantePagination). Le seuil est abaissé dans ces tests pour déclencher le mode estimé
    sans avoir à fabriquer 10 000 lignes."""

    @pytest.fixture
    def admin_client(self, create_user):
        admin = create_user(username="admin-pagin@test.fr", email="admin-pagin@test.fr", type="ADMIN", is_superuser=True)
        client = APIClient()
        client.force_authenticate(user=admin)
        return client

    def test_comptage_exact_sous_le_seuil(self, admin_client):
        for _ in range(7):
            _make_log()

        reponse = admin_client.get(reverse('auditlog-list'), {"page": 1, "page_size": 3})

        assert reponse.data["count"] == 7 and reponse.data["count_plafonne"] is False
        assert len(reponse.data["results"]) == 3
        assert reponse.data["next"] is not None and reponse.data["previous"] is None

    def test_au_dela_du_seuil_le_total_est_plafonne(self, admin_client, monkeypatch):
        from core.pagination import MainCourantePagination
        monkeypatch.setattr(MainCourantePagination, "SEUIL_COMPTAGE_EXACT", 2)
        for _ in range(6):
            _make_log()

        reponse = admin_client.get(reverse('auditlog-list'), {"page": 1, "page_size": 2})

        # « plus de 2 », jamais un chiffre inventé : le total vaut exactement le plafond.
        assert reponse.data["count_plafonne"] is True
        assert reponse.data["count"] == 2
        assert len(reponse.data["results"]) == 2

    def test_la_navigation_ne_depend_pas_du_total(self, admin_client, monkeypatch):
        """Avec un total estimé, « page suivante » doit rester exact : il vient d'une ligne lue
        en plus, pas d'une division du total."""
        from core.pagination import MainCourantePagination
        monkeypatch.setattr(MainCourantePagination, "SEUIL_COMPTAGE_EXACT", 1)
        for _ in range(5):
            _make_log()

        derniere = admin_client.get(reverse('auditlog-list'), {"page": 3, "page_size": 2})
        assert len(derniere.data["results"]) == 1
        assert derniere.data["next"] is None          # plus rien après, malgré un total plafonné
        assert derniere.data["previous"] is not None

        au_dela = admin_client.get(reverse('auditlog-list'), {"page": 4, "page_size": 2})
        assert au_dela.data["results"] == [] and au_dela.data["next"] is None

    def test_sans_page_la_reponse_reste_un_tableau_brut(self, admin_client):
        """Opt-in hérité d'OptionalPageNumberPagination : le widget d'historique par fiche et
        les autres appelants existants ne passent pas ?page= et attendent un tableau."""
        _make_log()
        reponse = admin_client.get(reverse('auditlog-list'))
        assert isinstance(reponse.data, list)


@pytest.mark.django_db
class TestAuditLogExport:

    def test_export_without_institution_returns_empty_csv(self, create_user):
        """Contrairement à avant (403 pour tout non-admin), un acteur institutionnel sans
        institution obtient désormais un CSV vide — même logique que la consultation (voir
        test_non_superuser_without_institution_gets_empty_list), pas une erreur."""
        user = create_user(username="regul-export@test.fr", email="regul-export@test.fr", type="REGULATEUR")
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('auditlog-export'))
        assert response.status_code == 200
        content = b"".join(response.streaming_content).decode("utf-8")
        rows = list(csv.reader(io.StringIO(content), delimiter=';'))
        assert len(rows) == 1  # en-tête seul

    def test_export_scoped_to_own_institution(self, create_user):
        mon_institution = _make_institution("Ma mairie export")
        autre_institution = _make_institution("Autre mairie export")
        _make_log(commentaire="Chez moi", institution=mon_institution)
        _make_log(commentaire="Chez l'autre", institution=autre_institution)

        user = create_user(
            username="aut-locale-export@test.fr", email="aut-locale-export@test.fr", type="AUT_LOCALE",
            institution=mon_institution,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        response = client.get(reverse('auditlog-export'))
        content = b"".join(response.streaming_content).decode("utf-8")
        rows = list(csv.reader(io.StringIO(content), delimiter=';'))
        # L'export lui-même écrit une ligne EXPORT (institution = celle de l'utilisateur, donc
        # incluse dans son propre résultat, générée après le count() mais avant la
        # consommation paresseuse du générateur) — on ne vérifie donc pas une égalité stricte.
        commentaires = [row[8] for row in rows[1:]]
        assert "Chez moi" in commentaires
        assert "Chez l'autre" not in commentaires

    def test_export_returns_readable_csv(self, create_user):
        Crisis.objects.create(name="Crise export", type="INONDATION", location="POINT (5.72 45.18)")
        admin = create_user(username="admin-export@test.fr", email="admin-export@test.fr", type="ADMIN", is_superuser=True)
        client = APIClient()
        client.force_authenticate(user=admin)

        response = client.get(reverse('auditlog-export'))
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert "main-courante-" in response["Content-Disposition"]

        content = b"".join(response.streaming_content).decode("utf-8")
        reader = csv.reader(io.StringIO(content), delimiter=';')
        rows = list(reader)
        assert rows[0] == [
            "Date", "Heure", "Utilisateur", "Institution", "Adresse IP", "Action",
            "Type d'objet", "ID objet", "Commentaire", "Succès", "Environnement", "Navigateur",
        ]
        assert len(rows) > 1

    def test_export_itself_is_logged(self, create_user):
        admin = create_user(username="admin-export-log@test.fr", email="admin-export-log@test.fr", type="ADMIN", is_superuser=True)
        client = APIClient()
        client.force_authenticate(user=admin)

        before = AuditLog.objects.filter(action__code="EXPORT", objet_type="AuditLog").count()
        response = client.get(reverse('auditlog-export'))
        list(response.streaming_content)  # force la génération (StreamingHttpResponse est paresseux)
        after = AuditLog.objects.filter(action__code="EXPORT", objet_type="AuditLog").count()
        assert after == before + 1
