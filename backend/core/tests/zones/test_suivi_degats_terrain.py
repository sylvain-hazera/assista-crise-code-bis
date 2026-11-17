"""Le suivi des dégâts sert pour tout sinistre (feu, vent, eau…) et se fait sur le terrain :
l'agent pointe la maison devant laquelle il se trouve, sans créer de doublon, puis dit ce qu'il
constate — jusqu'à « détruite »."""
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core import rattachement_adresses
from core.models import (
    AdresseSimuleeInondation, Crisis, Dossier, Habitation, HabitationHistorique, NatureDegatsHabitation,
    PersonneVulnerable, StatutEvaluationHabitation,
)

COMMUNE = "33333"


@pytest.fixture
def client(create_user):
    admin = create_user(username="admin-terrain@test.fr", email="admin-terrain@test.fr", type="ADMIN")
    c = APIClient()
    c.force_authenticate(user=admin)
    return c


@pytest.fixture
def feu(db):
    return Crisis.objects.create(name="Feu de la Teste", type="INCENDIE", location=Point(-1.14, 44.63, srid=4326))


def _adresse_trouvee(distance=8):
    return {"features": [{"properties": {"label": "14 Allée des Pins 33260 La Teste-de-Buch", "id": "33529_0140_00014",
                                          "city": "La Teste-de-Buch", "distance": distance}}]}


@pytest.mark.django_db
class TestPointerUneMaison:
    def _pointer(self, client, crise, lat=44.63, lon=-1.14, **extra):
        return client.post(reverse("habitation-pointer"), {"crise": str(crise.id), "latitude": lat, "longitude": lon, **extra}, format="json")

    def test_cree_la_maison_a_la_position_du_telephone_avec_son_adresse(self, client, feu):
        with patch("core.views.commune_code_from_point", return_value=COMMUNE), \
             patch("core.views_adresses._interroger", return_value=_adresse_trouvee()):
            reponse = self._pointer(client, feu)

        assert reponse.status_code == 201, reponse.data
        assert reponse.data["existante"] is False and reponse.data["adresse"] == "14 Allée des Pins 33260 La Teste-de-Buch"
        maison = Habitation.objects.get()
        assert maison.ban_id == "33529_0140_00014" and maison.commune_code == COMMUNE and maison.crise_id == feu.id
        assert round(maison.location.y, 5) == 44.63 and round(maison.location.x, 5) == -1.14
        assert HabitationHistorique.objects.get(habitation=maison).evenement == "Habitation pointée sur le terrain"

    def test_ne_double_pas_une_maison_deja_referencee(self, client, feu):
        deja = Habitation.objects.create(crise=feu, adresse="14 Allée des Pins", commune_code=COMMUNE,
                                         ban_id="33529_0140_00014", location=Point(-1.1401, 44.6301, srid=4326))
        with patch("core.views.commune_code_from_point", return_value=COMMUNE), \
             patch("core.views_adresses._interroger", return_value=_adresse_trouvee()):
            meme_adresse = self._pointer(client, feu, lat=44.6310)                       # autre point, même adresse nationale
        with patch("core.views.commune_code_from_point", return_value=COMMUNE), \
             patch("core.views_adresses._interroger", return_value=None):
            a_cote = self._pointer(client, feu, lat=44.63015, lon=-1.14012)              # à quelques mètres, sans adresse trouvée

        assert meme_adresse.status_code == 200 and meme_adresse.data["existante"] is True and meme_adresse.data["id"] == str(deja.id)
        assert a_cote.data["existante"] is True and Habitation.objects.count() == 1

    def test_sans_adresse_proche_la_maison_est_quand_meme_pointee(self, client, feu):
        """Une grange, un lieu-dit : pas de numéro. Et l'adresse d'un voisin à 200 m n'est pas la sienne."""
        with patch("core.views.commune_code_from_point", return_value=COMMUNE), \
             patch("core.views_adresses._interroger", return_value=_adresse_trouvee(distance=200)):
            reponse = self._pointer(client, feu)

        assert reponse.status_code == 201 and reponse.data["adresse"].startswith("Sans adresse — 44.63000")
        assert Habitation.objects.get().ban_id is None
        with patch("core.views.commune_code_from_point", return_value=COMMUNE):
            saisie = self._pointer(client, feu, lat=44.70, adresse="Grange du Pré, lieu-dit Les Landes")
        assert saisie.data["adresse"] == "Grange du Pré, lieu-dit Les Landes"

    def test_refuse_sans_crise_sans_position_et_sans_connexion(self, client, feu):
        assert client.post(reverse("habitation-pointer"), {"latitude": 44.6, "longitude": -1.1}, format="json").status_code == 400
        assert client.post(reverse("habitation-pointer"), {"crise": str(feu.id)}, format="json").status_code == 400
        assert APIClient().post(reverse("habitation-pointer"), {"crise": str(feu.id), "latitude": 44.6, "longitude": -1.1},
                                format="json").status_code in (401, 403)


@pytest.mark.django_db
class TestPointageDesIntervenants:
    """Un intervenant pointe, la commune valide : tant qu'elle ne l'a pas fait, le pointage
    n'est pas une habitation."""

    @pytest.fixture
    def terrain(self, feu, create_user):
        from core.models import Institution, InstitutionType, Mission, ModuleDegatsCrise, Team

        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        mairie = Institution.objects.create(nom="Mairie de La Teste", type=itype, commune_code=COMMUNE, commune_nom="La Teste-de-Buch")
        elue = create_user(username="elue-terrain@test.fr", email="elue-terrain@test.fr", type="AUT_LOCALE")
        elue.institution = mairie
        elue.save()
        ModuleDegatsCrise.objects.create(crise=feu, institution=mairie, actif=True)
        equipe = Team.objects.create(name="Reconnaissance", description="", color="#3b82f6", institution=mairie)
        Mission.objects.create(titre="Tournée des Pins", description="", crise=feu, institution=mairie).equipes.add(equipe)
        benevole = create_user(username="benevole-terrain@test.fr", email="benevole-terrain@test.fr", type="UTIL_SIMPLE")
        equipe.members.add(benevole)
        clients = {}
        for nom, compte in (("benevole", benevole), ("elue", elue)):
            clients[nom] = APIClient()
            clients[nom].force_authenticate(user=compte)
        return {"feu": feu, "equipe": equipe, "mairie": mairie, **clients}

    def _pointer(self, client, crise, lat=44.63, lon=-1.14, **extra):
        with patch("core.views.commune_code_from_point", return_value=COMMUNE), \
             patch("core.views_adresses._interroger", return_value=_adresse_trouvee()):
            return client.post(reverse("habitation-pointer"), {"crise": str(crise.id), "latitude": lat, "longitude": lon, **extra}, format="json")

    def test_le_pointage_dun_intervenant_attend_la_validation_de_la_commune(self, terrain):
        from core.models import PointageTerrain

        reponse = self._pointer(terrain["benevole"], terrain["feu"])

        assert reponse.status_code == 202, reponse.data
        assert reponse.data["a_valider"] is True and reponse.data["adresse"] == "14 Allée des Pins 33260 La Teste-de-Buch"
        assert Habitation.objects.count() == 0 and PointageTerrain.objects.count() == 1
        # Il dit ce qu'il constate ; revenir pointer la même maison ne double pas la proposition.
        constat = terrain["benevole"].post(f"/api/habitations/pointages/{reponse.data['id']}/constater/",
                                           {"statut_evaluation": "DETRUITE", "commentaire": "Toiture effondrée."}, format="json")
        assert constat.status_code == 200 and constat.data["nature_degats"] == "FEU"
        assert self._pointer(terrain["benevole"], terrain["feu"]).status_code == 200 and PointageTerrain.objects.count() == 1
        assert Habitation.objects.count() == 0 and not Dossier.objects.exists()

    def test_la_commune_valide_et_le_constat_devient_levaluation(self, terrain):
        pointage = self._pointer(terrain["benevole"], terrain["feu"], statut_evaluation="DEGATS_FORTS", commentaire="Façade noircie.").data
        liste = terrain["elue"].get("/api/habitations/pointages/", {"crise": str(terrain["feu"].id)}).data
        assert [p["id"] for p in liste] == [pointage["id"]] and liste[0]["peut_valider"] is True

        assert terrain["benevole"].post(f"/api/habitations/pointages/{pointage['id']}/valider/").status_code == 403
        reponse = terrain["elue"].post(f"/api/habitations/pointages/{pointage['id']}/valider/", {"statut_evaluation": "DETRUITE"}, format="json")

        assert reponse.status_code == 200, reponse.data
        maison = Habitation.objects.get()
        assert maison.statut_evaluation == "DETRUITE" and maison.nature_degats == "FEU" and maison.ban_id == "33529_0140_00014"
        assert maison.evalue_par.username == "elue-terrain@test.fr"
        assert "constat de terrain" in HabitationHistorique.objects.filter(habitation=maison).latest("date_creation").evenement
        assert maison.commentaires.get().commentaire == "Façade noircie." and Dossier.objects.filter(habitation=maison).exists()
        assert terrain["elue"].post(f"/api/habitations/pointages/{pointage['id']}/valider/").status_code == 409
        # L'intervenant retrouve son pointage, validé ; la commune n'a plus rien à valider.
        assert terrain["benevole"].get("/api/habitations/pointages/").data[0]["statut"] == "VALIDE"
        assert terrain["elue"].get("/api/habitations/pointages/").data == []

    def test_valider_complete_la_maison_deja_referencee_sans_la_doubler(self, terrain):
        deja = Habitation.objects.create(crise=terrain["feu"], adresse="14 Allée des Pins", commune_code=COMMUNE,
                                         ban_id="33529_0140_00014", location=Point(-1.1401, 44.6301, srid=4326))
        pointage = self._pointer(terrain["benevole"], terrain["feu"], statut_evaluation="DEGATS_FAIBLES").data
        assert pointage["existante"] is True

        terrain["elue"].post(f"/api/habitations/pointages/{pointage['id']}/valider/")

        deja.refresh_from_db()
        assert Habitation.objects.count() == 1 and deja.statut_evaluation == "DEGATS_FAIBLES"

    def test_un_pointage_refuse_ne_laisse_aucune_habitation(self, terrain):
        pointage = self._pointer(terrain["benevole"], terrain["feu"]).data

        reponse = terrain["elue"].post(f"/api/habitations/pointages/{pointage['id']}/refuser/", {"motif": "Hors périmètre du feu."}, format="json")

        assert reponse.data["statut"] == "REFUSE" and reponse.data["motif_refus"] == "Hors périmètre du feu."
        assert Habitation.objects.count() == 0
        assert terrain["benevole"].post(f"/api/habitations/pointages/{pointage['id']}/constater/", {"statut_evaluation": "DETRUITE"}, format="json").status_code == 409

    def test_qui_nintervient_pas_sur_la_crise_ne_pointe_pas(self, terrain, create_user):
        from core.models import ModuleDegatsCrise

        passant = create_user(username="passant-terrain@test.fr", email="passant-terrain@test.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=passant)
        assert self._pointer(client, terrain["feu"]).status_code == 403
        # Et sans suivi des dégâts activé par la commune, l'intervenant non plus.
        ModuleDegatsCrise.objects.update(actif=False)
        assert self._pointer(terrain["benevole"], terrain["feu"]).status_code == 403

    def test_le_personnel_de_la_commune_pointe_toujours_directement(self, terrain):
        reponse = self._pointer(terrain["elue"], terrain["feu"])

        assert reponse.status_code == 201 and Habitation.objects.count() == 1


@pytest.mark.django_db
class TestTousLesSinistres:
    def _maison(self, crise):
        return Habitation.objects.create(crise=crise, adresse="14 Allée des Pins", commune_code=COMMUNE,
                                         location=Point(-1.14, 44.63, srid=4326))

    def test_une_maison_detruite_par_le_feu_se_note_ainsi_et_ouvre_un_dossier(self, client, feu):
        maison = self._maison(feu)

        reponse = client.post(reverse("habitation-evaluer", args=[maison.id]), {"statut_evaluation": "DETRUITE"}, format="json")

        assert reponse.status_code == 200, reponse.data
        maison.refresh_from_db()
        assert maison.statut_evaluation == StatutEvaluationHabitation.DETRUITE
        assert maison.nature_degats == NatureDegatsHabitation.FEU          # proposée d'après le type de la crise
        assert "Détruite" in HabitationHistorique.objects.filter(habitation=maison).latest("date_creation").evenement
        assert Dossier.objects.filter(habitation=maison).exists()

    def test_la_cause_se_precise_maison_par_maison_et_tombe_sans_degats(self, client):
        orage = Crisis.objects.create(name="Orage du 12", type="CATASTROPHE_NATURELLE", location=Point(-1.14, 44.63, srid=4326))
        maison = self._maison(orage)
        url = reverse("habitation-evaluer", args=[maison.id])

        client.post(url, {"statut_evaluation": "DEGATS_FORTS", "nature_degats": "VENT"}, format="json")
        maison.refresh_from_db()
        assert maison.nature_degats == "VENT" and "Vent (tempête, tornade)" in maison.get_nature_degats_display()
        assert client.post(url, {"statut_evaluation": "DEGATS_FORTS", "nature_degats": "MARTIENS"}, format="json").status_code == 400
        client.post(url, {"statut_evaluation": "PAS_DE_DEGATS"}, format="json")
        maison.refresh_from_db()
        assert maison.nature_degats == ""

    def test_le_rapport_de_crise_dit_les_causes_et_compte_les_maisons_detruites(self, feu, create_user):
        from core import rapports_pdf
        from core.models import Institution, InstitutionType

        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        mairie = Institution.objects.create(nom="Mairie de La Teste", type=itype, commune_code=COMMUNE, commune_nom="La Teste-de-Buch")
        Habitation.objects.create(crise=feu, adresse="14 Allée des Pins", commune_code=COMMUNE,
                                  statut_evaluation="DETRUITE", nature_degats="FEU", surface_habitable_impactee=110)
        Habitation.objects.create(crise=feu, adresse="16 Allée des Pins", commune_code=COMMUNE,
                                  statut_evaluation="DEGATS_FAIBLES", nature_degats="FEU")

        resume = rapports_pdf.crise_resume(feu, mairie, "PROD", lambda u: "")

        assert dict(resume["degats"])["Détruite"]["nombre"] == 1 and dict(resume["degats"])["Détruite"]["habitable"] == 110.0
        assert resume["causes"] == [("Feu (incendie, feu de forêt)", 2)]
        assert rapports_pdf.generer("crise", resume, edite_par="Agent").startswith(b"%PDF")


@pytest.mark.django_db
class TestRattachementSansInondation:
    """Une commune touchée par le feu n'a pas de simulation d'inondation : ses adresses viennent
    alors des maisons référencées pour la crise, ou d'un relevé simple."""

    def _fiche(self, adresse, **champs):
        from core.models import Institution, InstitutionType
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        mairie, _ = Institution.objects.get_or_create(nom="Mairie de La Teste", defaults={"type": itype, "commune_code": COMMUNE})
        return PersonneVulnerable.objects.create(institution_declarante=mairie, commune_code=COMMUNE, nom="Dupont", prenom="Jeanne",
                                                 adresse=adresse, mode_consentement="VOLONTAIRE", **champs)

    def test_les_maisons_referencees_pour_la_crise_servent_dadresses_et_donnent_les_degats(self, feu):
        Habitation.objects.create(crise=feu, adresse="14 Allée des Pins, 33260 La Teste-de-Buch", commune_code=COMMUNE,
                                  ban_id="33529_0140_00014", location=Point(-1.14, 44.63, srid=4326),
                                  statut_evaluation="DETRUITE", nature_degats="FEU")
        fiche = self._fiche("14 allée des pins")

        releve = rattachement_adresses.Releve(COMMUNE, "PROD")

        assert releve.disponible and not AdresseSimuleeInondation.objects.exists()
        assert [a.ban_id for a in releve.chercher("14 pins")] == ["33529_0140_00014"]
        assert releve.propositions(fiche)[0]["exacte"] is True
        assert rattachement_adresses.degats_constates([fiche], releve, "PROD") == {fiche.id: "Détruite"}
        # Rien n'a été simulé : on ne dit pas « au sec », on ne dit rien de l'eau.
        from core.enjeux_exposes import seuils_du_registre
        assert seuils_du_registre([fiche], COMMUNE, "PROD") == {}

    def test_un_releve_simple_des_adresses_suffit_sans_rien_simuler(self):
        scan = {"adresses": [{"adresse": "3 Rue du Port, 33260 La Teste-de-Buch", "lon": -1.15, "lat": 44.64,
                              "parcelle_cadastrale": None, "ban_id": "33529_0200_00003"}],
                "voies_totales": 1, "voies_en_echec": 0, "erreur": None}
        with patch("core.habitations.scanner_ban_commune", return_value=scan) as appel:
            assert rattachement_adresses.relever_les_adresses(COMMUNE, "PROD") == 1
            assert rattachement_adresses.relever_les_adresses(COMMUNE, "PROD") == 0       # déjà relevé : rien n'est redemandé
        assert appel.call_count == 1
        ligne = AdresseSimuleeInondation.objects.get()
        assert ligne.altitude_metres is None and ligne.seuil_inondation_metres is None
        fiche = self._fiche("ailleurs", adresse_ban_id="33529_0200_00003")
        from core.enjeux_exposes import seuils_du_registre
        assert seuils_du_registre([fiche], COMMUNE, "PROD") == {}                        # relevé, mais pas simulé
        assert rattachement_adresses.Releve(COMMUNE, "PROD").adresse_de(fiche).ban_id == "33529_0200_00003"
