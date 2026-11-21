"""Qui peut écrire un rattachement (ContactInstitution) — 21/11/2026.

Constaté en refaisant le manuel de Réserve Résilience : un simple bénévole rattaché à son
association pouvait se cocher « Bureau » (et obtenir l'annuaire complet, les candidatures, les
clés d'envoi), ou désactiver le rattachement de n'importe quel membre du bureau."""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import ContactInstitution, Institution, InstitutionType


@pytest.fixture
def asso(db):
    itype, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
    return Institution.objects.create(nom="Association test droits", type=itype)


def _membre(create_user, asso, email, type_="UTIL_SIMPLE", bureau=False):
    u = create_user(username=email, email=email, type=type_)
    c = ContactInstitution.objects.create(institution=asso, utilisateur=u, actif=True, membre_bureau=bureau)
    return u, c


def _client(u):
    c = APIClient(); c.force_authenticate(user=u); return c


@pytest.mark.django_db
class TestDroitsEcritureRattachements:

    def test_un_benevole_ne_peut_pas_se_cocher_bureau(self, create_user, asso):
        _membre(create_user, asso, "pres@test.fr", "AUT_LOCALE", bureau=True)
        benevole, contact = _membre(create_user, asso, "benevole@test.fr")
        r = _client(benevole).patch(reverse("contactinstitution-detail", args=[contact.id]), {"membre_bureau": True}, format="json")
        assert r.status_code == 403
        contact.refresh_from_db()
        assert contact.membre_bureau is False

    def test_un_benevole_ne_peut_pas_desactiver_ni_supprimer_un_autre_membre(self, create_user, asso):
        _, presidente = _membre(create_user, asso, "pres2@test.fr", "AUT_LOCALE", bureau=True)
        benevole, _ = _membre(create_user, asso, "benevole2@test.fr")
        client = _client(benevole)
        assert client.patch(reverse("contactinstitution-detail", args=[presidente.id]), {"actif": False}, format="json").status_code == 403
        assert client.delete(reverse("contactinstitution-detail", args=[presidente.id])).status_code == 403
        presidente.refresh_from_db()
        assert presidente.actif

    def test_un_agent_ne_touche_ni_au_bureau_ni_a_un_membre_du_bureau(self, create_user, asso):
        _, presidente = _membre(create_user, asso, "pres3@test.fr", "AUT_LOCALE", bureau=True)
        agent, _ = _membre(create_user, asso, "agent@test.fr", "AUT_LOCALE")
        _, collegue = _membre(create_user, asso, "collegue@test.fr", "AUT_LOCALE")
        client = _client(agent)
        assert client.patch(reverse("contactinstitution-detail", args=[collegue.id]), {"membre_bureau": True}, format="json").status_code == 403
        assert client.patch(reverse("contactinstitution-detail", args=[presidente.id]), {"actif": False}, format="json").status_code == 403
        # Mais il gère un collègue ordinaire.
        assert client.patch(reverse("contactinstitution-detail", args=[collegue.id]), {"fonction": "Logisticien"}, format="json").status_code == 200

    def test_le_bureau_designe_le_bureau(self, create_user, asso):
        presidente, _ = _membre(create_user, asso, "pres4@test.fr", "AUT_LOCALE", bureau=True)
        _, tresorier = _membre(create_user, asso, "tresorier@test.fr")
        r = _client(presidente).patch(reverse("contactinstitution-detail", args=[tresorier.id]), {"membre_bureau": True}, format="json")
        assert r.status_code == 200
        tresorier.refresh_from_db()
        assert tresorier.membre_bureau

    def test_une_institution_sans_bureau_peut_s_en_donner_un(self, create_user, asso):
        agent, contact = _membre(create_user, asso, "fondateur@test.fr", "AUT_LOCALE")
        assert _client(agent).patch(reverse("contactinstitution-detail", args=[contact.id]), {"membre_bureau": True}, format="json").status_code == 200

    def test_on_peut_toujours_quitter_une_institution(self, create_user, asso):
        benevole, contact = _membre(create_user, asso, "partant@test.fr")
        assert _client(benevole).patch(reverse("contactinstitution-detail", args=[contact.id]), {"actif": False}, format="json").status_code == 200

    def test_un_compte_hors_institution_ne_peut_pas_y_rattacher_quelqu_un(self, create_user, asso):
        etranger = create_user(username="etranger@test.fr", email="etranger@test.fr", type="AUT_LOCALE")
        cible = create_user(username="cible@test.fr", email="cible@test.fr")
        r = _client(etranger).post(reverse("contactinstitution-list"),
                                   {"institution": str(asso.id), "utilisateur": str(cible.id), "actif": True}, format="json")
        assert r.status_code == 403
