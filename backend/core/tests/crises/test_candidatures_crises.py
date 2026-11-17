"""Candidater sur une crise depuis le tableau de bord, où qu'elle soit en France (17/11/2026).

Deux situations : « la crise touche ma commune », ou « ma commune peut aider » — et dans ce
cas dire avec quoi (centre d'accueil, point de regroupement des moyens, personnel…).
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core.models import (
    Besoin, ContactInstitution, Crisis, ImplicationInstitution, Institution, InstitutionType,
    Notification,
)


@pytest.fixture
def crise(db):
    return Crisis.objects.create(
        name="Crue de l'Ondaine", type="INONDATION", location="POINT (4.3 45.4)",
        zone_communes=["42095"],
    )


def _mairie(create_user, code, nom=None):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom=nom or f"Mairie {code}", type=itype, commune_code=code)
    user = create_user(username=f"a{code}@cand.fr", email=f"a{code}@cand.fr", type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return mairie, user, client


def _aider(client, crise, **corps):
    return client.post(reverse("crisis-proposer-aide", args=[str(crise.id)]), corps, format="json")


@pytest.mark.django_db
class TestToutesLesCrises:

    def test_une_commune_lointaine_voit_la_crise_et_sa_propre_situation(self, create_user, crise):
        _, _, client = _mairie(create_user, "29019", "Mairie de Brest")
        Crisis.objects.create(name="Crise close", type="AUTRE", location="POINT (2 48)",
                              end_date="2026-01-01T00:00:00Z")

        reponse = client.get(reverse("crisis-candidatures"))

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["institution"]["nom"] == "Mairie de Brest"
        (ligne,) = reponse.data["crises"]                      # la crise close n'y est pas
        assert ligne["name"] == "Crue de l'Ondaine"
        assert ligne["situation"] == {"impliquee": False, "acteur": None, "dans_la_zone": False}
        assert {a["code"] for a in reponse.data["aides"]} >= {
            "CENTRE_ACCUEIL", "POINT_REGROUPEMENT", "PERSONNEL"}

    def test_la_situation_suit_les_declarations(self, create_user, crise):
        mairie, user, client = _mairie(create_user, "42095")
        ImplicationInstitution.objects.create(
            crise=crise, institution=mairie, type_implication="IMPLIQUE", utilisateur=user, actif=True)
        ligne = client.get(reverse("crisis-candidatures")).data["crises"][0]
        assert ligne["situation"] == {"impliquee": True, "acteur": None, "dans_la_zone": True}

    def test_reserve_aux_comptes_institutionnels(self, create_user, crise):
        citoyen = create_user(username="c@cand.fr", email="c@cand.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=citoyen)
        assert client.get(reverse("crisis-candidatures")).status_code == 403


@pytest.mark.django_db
class TestMaCommunePeutAider:

    def test_elle_dit_avec_quoi_et_vient_en_renfort(self, create_user, crise):
        """Pas sinistrée : la zone ne bouge pas, et la commune d'accueil doit donner son accord."""
        voisine, _, client = _mairie(create_user, "42218")

        reponse = _aider(client, crise, aides=["PERSONNEL", "CENTRE_ACCUEIL"],
                         message="Gymnase de 80 places dès ce soir.")

        assert reponse.status_code == 201, reponse.data
        assert reponse.data["statut"] == "EN_ATTENTE"
        assert reponse.data["renfort"] is True
        assert reponse.data["aides_proposees"] == ["CENTRE_ACCUEIL", "PERSONNEL"]   # ordre du catalogue
        assert reponse.data["aides_libelles"][0] == "Ouvrir un centre d'accueil des civils"
        crise.refresh_from_db()
        assert crise.zone_communes == ["42095"]

    def test_la_commune_sinistree_est_prevenue_de_ce_qui_est_propose(self, create_user, crise):
        sinistree, maire, _ = _mairie(create_user, "42095")
        ImplicationInstitution.objects.create(
            crise=crise, institution=sinistree, type_implication="IMPLIQUE", utilisateur=maire, actif=True)
        _, _, client = _mairie(create_user, "42218")

        _aider(client, crise, aides=["POINT_REGROUPEMENT"])

        notification = Notification.objects.filter(utilisateur=maire).latest("date_creation")
        assert "Point de regroupement des moyens" in str(notification.details)

    def test_une_aide_inconnue_est_refusee(self, create_user, crise):
        _, _, client = _mairie(create_user, "42218")
        assert _aider(client, crise, aides=["HELICOPTERE"]).status_code == 400
        assert not ImplicationInstitution.objects.filter(crise=crise).exists()

    def test_sans_aide_ni_besoin_la_proposition_reste_refusee(self, create_user, crise):
        _, _, client = _mairie(create_user, "42218")
        assert _aider(client, crise, themes=[], aides=[]).status_code == 400

    def test_l_ancien_geste_par_besoins_n_a_pas_change(self, create_user, crise):
        _, _, client = _mairie(create_user, "42218")
        besoin = Besoin.objects.create(nom="Hébergement candidature")
        reponse = _aider(client, crise, themes=[str(besoin.id)])
        assert (reponse.data["statut"], reponse.data["renfort"]) == ("VALIDEE", False)
