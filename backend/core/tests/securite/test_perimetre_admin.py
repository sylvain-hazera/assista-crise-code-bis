"""Ce qu'un administrateur REGARDE : son institution, une autre, ou toute la plateforme
(sélecteur de la barre du haut, en-tête X-Perimetre). Voir core/perimetre_admin.py.

Signalé par Sylvain le 15/11/2026 : « avec mon compte admin je vois des institutions qui ne sont
pas les miennes, pas mon secteur ». Ce qui est vérifié ici :
- sans l'en-tête, rien ne change (ponts, mobile, scripts) ;
- avec lui, les LISTES se réduisent à l'institution regardée ;
- aucun DROIT n'est retiré : un objet précis reste accessible ;
- l'en-tête n'élargit jamais ce que voit un compte qui n'est pas administrateur.
"""
import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from core import perimetre_admin
from core.models import (
    Commune, ContactInstitution, Institution, InstitutionType, Mission, Team,
)

PROD = {"HTTP_X_ENVIRONMENT": "PROD"}


@pytest.fixture
def communes(db):
    return {
        "saint_etienne": Commune.objects.create(
            code="42218", nom="Saint-Étienne", departement_code="42", epci_code="244200770",
            region_code="84", centre_latitude=45.44, centre_longitude=4.39),
        "lille": Commune.objects.create(
            code="59350", nom="Lille", departement_code="59", epci_code="200093201",
            region_code="32", centre_latitude=50.63, centre_longitude=3.06),
    }


def _institution(nom, commune_code, type_code="MAIRIE"):
    itype, _ = InstitutionType.objects.get_or_create(code=type_code, defaults={"libelle": type_code})
    return Institution.objects.create(nom=nom, type=itype, commune_code=commune_code, environment="PROD")


@pytest.fixture
def monde(create_user, communes):
    """Deux mairies, chacune avec une équipe, une mission et un cadre ; un administrateur
    rattaché à la première."""
    ici = _institution("Mairie de Saint-Étienne", "42218")
    ailleurs = _institution("Mairie de Lille", "59350")
    equipe_ici = Team.objects.create(name="Réserve stéphanoise", institution=ici, environment="PROD")
    equipe_ailleurs = Team.objects.create(name="Réserve lilloise", institution=ailleurs, environment="PROD")
    mission_ici = Mission.objects.create(titre="Garde du feu", environment="PROD")
    mission_ici.equipes.add(equipe_ici)
    mission_ailleurs = Mission.objects.create(titre="Ravitaillement", environment="PROD")
    mission_ailleurs.equipes.add(equipe_ailleurs)

    admin = create_user(username="admin@test.fr", email="admin@test.fr", type="ADMIN")
    admin.institution = ici
    admin.save()
    ContactInstitution.objects.create(utilisateur=admin, institution=ici, actif=True)
    cadre_ailleurs = create_user(username="cadre@lille.fr", email="cadre@lille.fr", type="AUT_LOCALE")
    cadre_ailleurs.institution = ailleurs
    cadre_ailleurs.save()
    ContactInstitution.objects.create(utilisateur=cadre_ailleurs, institution=ailleurs, actif=True)
    return {"ici": ici, "ailleurs": ailleurs, "equipe_ici": equipe_ici, "equipe_ailleurs": equipe_ailleurs,
            "mission_ici": mission_ici, "mission_ailleurs": mission_ailleurs,
            "admin": admin, "cadre_ailleurs": cadre_ailleurs}


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


def _noms(reponse, champ="name"):
    lignes = reponse.data["results"] if isinstance(reponse.data, dict) and "results" in reponse.data else reponse.data
    return sorted(ligne[champ] for ligne in lignes)


@pytest.mark.django_db
class TestLeChoix:

    def _requete(self, utilisateur, perimetre=None):
        from rest_framework.test import APIRequestFactory

        entetes = dict(PROD)
        if perimetre is not None:
            entetes["HTTP_X_PERIMETRE"] = perimetre
        requete = APIRequestFactory().get("/", **entetes)
        requete.user = utilisateur
        return requete

    def test_sans_en_tete_un_administrateur_voit_tout_comme_avant(self, monde):
        requete = self._requete(monde["admin"])

        assert perimetre_admin.admin_voit_tout(requete) is True
        assert perimetre_admin.institutions_visibles(requete) is None

    def test_mienne_designe_son_institution_active(self, monde):
        requete = self._requete(monde["admin"], "MIENNE")

        assert perimetre_admin.admin_voit_tout(requete) is False
        assert perimetre_admin.institution_regardee(requete) == monde["ici"]
        assert perimetre_admin.institutions_visibles(requete) == [monde["ici"].id]

    def test_un_administrateur_sans_institution_n_a_rien_a_quoi_se_restreindre(self, create_user, db):
        seul = create_user(username="seul@test.fr", email="seul@test.fr", type="ADMIN")

        assert perimetre_admin.admin_voit_tout(self._requete(seul, "MIENNE")) is True

    def test_il_peut_regarder_n_importe_quelle_institution(self, monde):
        requete = self._requete(monde["admin"], str(monde["ailleurs"].id))

        assert perimetre_admin.institution_regardee(requete) == monde["ailleurs"]
        assert perimetre_admin.institutions_visibles(requete) == [monde["ailleurs"].id]

    def test_un_perimetre_qui_ne_designe_rien_est_refuse(self, monde):
        from rest_framework.exceptions import ValidationError

        for valeur in ("n'importe quoi", "00000000-0000-0000-0000-000000000000"):
            with pytest.raises(ValidationError):
                perimetre_admin.admin_voit_tout(self._requete(monde["admin"], valeur))

    def test_l_en_tete_n_elargit_jamais_un_autre_compte(self, monde):
        """LE test de sécurité de ce module : un cadre qui écrit « TOUT », ou l'identifiant
        d'une autre institution, continue de ne voir que la sienne."""
        for valeur in ("TOUT", str(monde["ici"].id)):
            requete = self._requete(monde["cadre_ailleurs"], valeur)

            assert perimetre_admin.admin_voit_tout(requete) is False
            assert perimetre_admin.admin_sans_filtre(requete) is False
            assert perimetre_admin.institution_regardee(requete) == monde["ailleurs"]
            assert perimetre_admin.institutions_visibles(requete) == [monde["ailleurs"].id]


@pytest.mark.django_db
class TestLesListes:

    def test_les_equipes_suivent_le_perimetre_choisi(self, monde):
        client = _client(monde["admin"])
        adresse = reverse("team-list")

        assert _noms(client.get(adresse, **PROD)) == ["Réserve lilloise", "Réserve stéphanoise"]
        assert _noms(client.get(adresse, HTTP_X_PERIMETRE="TOUT", **PROD)) == ["Réserve lilloise", "Réserve stéphanoise"]
        assert _noms(client.get(adresse, HTTP_X_PERIMETRE="MIENNE", **PROD)) == ["Réserve stéphanoise"]
        assert _noms(client.get(adresse, HTTP_X_PERIMETRE=str(monde["ailleurs"].id), **PROD)) == ["Réserve lilloise"]

    def test_les_missions_aussi(self, monde):
        client = _client(monde["admin"])
        adresse = reverse("mission-list")

        assert _noms(client.get(adresse, **PROD), "titre") == ["Garde du feu", "Ravitaillement"]
        assert _noms(client.get(adresse, HTTP_X_PERIMETRE="MIENNE", **PROD), "titre") == ["Garde du feu"]
        assert _noms(client.get(adresse, HTTP_X_PERIMETRE=str(monde["ailleurs"].id), **PROD), "titre") == ["Ravitaillement"]

    def test_les_institutions_et_les_comptes_aussi(self, monde):
        client = _client(monde["admin"])

        institutions = client.get(reverse("institution-list"), HTTP_X_PERIMETRE="MIENNE", **PROD)
        assert _noms(institutions, "nom") == ["Mairie de Saint-Étienne"]
        comptes = client.get(reverse("user-list"), HTTP_X_PERIMETRE="MIENNE", **PROD)
        assert _noms(comptes, "email") == ["admin@test.fr"]
        tous = client.get(reverse("user-list"), HTTP_X_PERIMETRE="TOUT", **PROD)
        assert {"admin@test.fr", "cadre@lille.fr"} <= set(_noms(tous, "email"))

    def test_le_selecteur_ne_retire_aucun_droit(self, monde):
        """Les listes se réduisent ; un objet précis reste accessible à l'administrateur."""
        client = _client(monde["admin"])

        equipe = client.get(reverse("team-detail", args=[monde["equipe_ailleurs"].id]), HTTP_X_PERIMETRE="MIENNE", **PROD)
        mission = client.get(reverse("mission-detail", args=[monde["mission_ailleurs"].id]), HTTP_X_PERIMETRE="MIENNE", **PROD)
        compte = client.get(reverse("user-detail", args=[monde["cadre_ailleurs"].id]), HTTP_X_PERIMETRE="MIENNE", **PROD)

        assert (equipe.status_code, mission.status_code, compte.status_code) == (200, 200, 200)

    def test_un_perimetre_invalide_est_dit_et_non_devine(self, monde):
        reponse = _client(monde["admin"]).get(reverse("team-list"), HTTP_X_PERIMETRE="n'importe quoi", **PROD)

        assert reponse.status_code == 400


@pytest.mark.django_db
class TestLesAutresComptes:

    def test_un_cadre_ne_voit_que_les_missions_qui_le_concernent(self, monde):
        """Avant le 16/11/2026, tout acteur institutionnel listait toutes les missions de la
        plateforme."""
        client = _client(monde["cadre_ailleurs"])

        assert _noms(client.get(reverse("mission-list"), **PROD), "titre") == ["Ravitaillement"]
        # … et l'en-tête de l'administrateur ne lui ouvre rien.
        assert _noms(client.get(reverse("mission-list"), HTTP_X_PERIMETRE="TOUT", **PROD), "titre") == ["Ravitaillement"]
        assert _noms(client.get(reverse("team-list"), HTTP_X_PERIMETRE="TOUT", **PROD)) == ["Réserve lilloise"]

    def test_une_mission_tout_juste_creee_reste_visible_de_son_auteur(self, monde):
        Mission.objects.create(titre="Sans équipe ni crise", environment="PROD")

        titres = _noms(_client(monde["cadre_ailleurs"]).get(reverse("mission-list"), **PROD), "titre")

        assert "Sans équipe ni crise" in titres


@pytest.mark.django_db
class TestLeSelecteur:

    def test_un_administrateur_recoit_son_etat_et_toutes_les_institutions(self, monde):
        reponse = _client(monde["admin"]).get(reverse("perimetre_admin"), HTTP_X_PERIMETRE="MIENNE", **PROD).json()

        assert reponse["administrateur"] is True and reponse["mode"] == "INSTITUTION"
        assert reponse["institution"]["nom"] == "Mairie de Saint-Étienne"
        assert reponse["mienne"]["id"] == str(monde["ici"].id)
        # 23/11/2026 : sans recherche, aucune liste (elle était coupée à 500) ; le sélecteur
        # cherche. Même en regardant sa mairie, la recherche porte sur toute la plateforme :
        # sinon on ne pourrait plus en sortir.
        assert reponse["institutions"] == []
        cherche = _client(monde["admin"]).get(reverse("perimetre_admin"), {"q": "mairie"}, HTTP_X_PERIMETRE="MIENNE", **PROD).json()
        assert {"Mairie de Lille", "Mairie de Saint-Étienne"} <= {i["nom"] for i in cherche["institutions"]}

    def test_la_recherche_restreint_la_liste(self, monde):
        reponse = _client(monde["admin"]).get(reverse("perimetre_admin"), {"q": "lille"}, **PROD).json()

        assert [i["nom"] for i in reponse["institutions"]] == ["Mairie de Lille"]
        assert reponse["mode"] == "TOUT"

    def test_la_recherche_par_code_postal_et_le_code_affiche(self, monde):
        from core.models import Institution
        Institution.objects.filter(nom="Mairie de Lille").update(commune_code_postal="59000", commune_nom="Lille")
        reponse = _client(monde["admin"]).get(reverse("perimetre_admin"), {"q": "590"}, **PROD).json()
        assert [(i["nom"], i["code_postal"], i["commune"]) for i in reponse["institutions"]] == [("Mairie de Lille", "59000", "Lille")]

    def test_un_choix_qui_ne_designe_plus_rien_est_signale_sans_bloquer(self, monde):
        """Institution supprimée depuis : l'écran doit pouvoir revenir à « mon institution »."""
        reponse = _client(monde["admin"]).get(
            reverse("perimetre_admin"), HTTP_X_PERIMETRE="00000000-0000-0000-0000-000000000000", **PROD)

        assert reponse.status_code == 200 and reponse.json()["mode"] == "INVALIDE"
        assert reponse.json()["mienne"]["nom"] == "Mairie de Saint-Étienne"

    def test_un_autre_compte_ne_recoit_aucune_liste(self, monde):
        reponse = _client(monde["cadre_ailleurs"]).get(reverse("perimetre_admin"), HTTP_X_PERIMETRE="TOUT", **PROD).json()

        assert reponse["administrateur"] is False and reponse["institutions"] == []
        assert reponse["mienne"]["nom"] == "Mairie de Lille"
