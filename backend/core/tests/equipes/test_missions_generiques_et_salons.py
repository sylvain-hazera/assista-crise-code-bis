"""Deux demandes de Sylvain du 16/11/2026.

1. « Une institution = un canal pour ses cadres, un pour ses intervenants ; une équipe = un
   canal ; une mission = un canal » -- et rattraper le retard : ces salons existent d'office,
   pour ce qui se crée comme pour ce qui existait déjà (core/salons_matrix.py). Un salon ne
   naît que s'il y a quelqu'un à y mettre (décision du 11/11/2026, gardée).
2. Une mission d'intérêt général (garde du feu) n'est pas la réponse à un appel à l'aide : c'est
   l'institution qui la demande. Elle doit pourtant pouvoir ouvrir des dossiers -- génériques,
   sans demandeur -- parce que c'est le dossier qui porte le chat, les photos et la traçabilité.

Aucun test ne parle au serveur Matrix : seules les lignes côté Django sont en jeu.
"""
from io import StringIO

import pytest
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APIClient

from core import salons_matrix
from core.models import (
    Commune, ContactInstitution, Crisis, Dossier, DossierHistorique, Institution, InstitutionType,
    Mission, SalonMatrixEquipe, SalonMatrixInstitution, SalonMatrixMission, Team,
)

PROD = {"HTTP_X_ENVIRONMENT": "PROD"}


@pytest.fixture
def communes(db):
    Commune.objects.create(code="42218", nom="Saint-Étienne", departement_code="42", epci_code="244200770",
                           region_code="84", centre_latitude=45.44, centre_longitude=4.39)
    Commune.objects.create(code="59350", nom="Lille", departement_code="59", epci_code="200093201",
                           region_code="32", centre_latitude=50.63, centre_longitude=3.06)


def _institution(nom, commune_code):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom=nom, type=itype, commune_code=commune_code, environment="PROD")


def _cadre(create_user, institution, email):
    utilisateur = create_user(username=email, email=email, type="AUT_LOCALE")
    utilisateur.institution = institution
    utilisateur.save()
    ContactInstitution.objects.create(utilisateur=utilisateur, institution=institution, actif=True)
    return utilisateur


@pytest.fixture
def mairie(communes):
    return _institution("Mairie de Saint-Étienne", "42218")


@pytest.fixture
def cadre(create_user, mairie):
    return _cadre(create_user, mairie, "cadre@saint-etienne.fr")


@pytest.fixture
def equipe(mairie):
    return Team.objects.create(name="Réserve communale", institution=mairie, environment="PROD")


@pytest.fixture
def crise(db):
    return Crisis.objects.create(name="Risque d'incendie", type="INCENDIE", location=Point(4.39, 45.44, srid=4326))


def _client(utilisateur):
    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.mark.django_db
class TestSalonsDOffice:

    def test_une_mission_recoit_son_salon_quand_une_equipe_lui_est_affectee(self, equipe):
        mission = Mission.objects.create(titre="Garde du feu", environment="PROD")
        # Sans équipe, il n'y a personne à réunir : pas de salon vide.
        assert not SalonMatrixMission.objects.filter(mission=mission).exists()

        mission.equipes.add(equipe)

        assert SalonMatrixMission.objects.filter(mission=mission).count() == 1
        # … et une seconde équipe n'en crée pas un second.
        autre = Team.objects.create(name="Renfort", institution=equipe.institution, environment="PROD")
        autre.missions.add(mission)                     # par l'autre bout de la relation
        assert SalonMatrixMission.objects.filter(mission=mission).count() == 1

    def test_affecter_par_l_equipe_cree_aussi_le_salon(self, equipe):
        mission = Mission.objects.create(titre="Ronde", environment="PROD")

        equipe.missions.add(mission)

        assert SalonMatrixMission.objects.filter(mission=mission).exists()

    def test_une_equipe_creee_hors_de_l_ecran_n_a_pas_de_salon_tant_qu_elle_est_vide(self, equipe):
        """Décision du 11/11/2026, gardée : l'arborescence de coordination ferait 254 salons
        presque tous vides. Les équipes créées depuis l'écran ont déjà les leurs (13/11/2026)."""
        assert not SalonMatrixEquipe.objects.filter(equipe=equipe).exists()
        assert salons_matrix.assurer_salons_equipe(equipe) == 0

    def test_une_institution_recoit_ses_salons_a_son_premier_membre(self, mairie, create_user):
        """Cadres et intervenants, pas le salon d'annonces. Et rien tant que personne n'y est
        rattaché : des centaines de mairies importées sans compte n'ont pas à avoir de salon."""
        assert SalonMatrixInstitution.objects.filter(institution=mairie).count() == 0

        _cadre(create_user, mairie, "premier@saint-etienne.fr")

        assert sorted(SalonMatrixInstitution.objects.filter(institution=mairie).values_list("type", flat=True)) == [
            "BENEVOLES", "PERMANENTS"]

    def test_la_zone_de_demonstration_garde_ses_salons_a_la_demande(self, mairie, cadre):
        equipe = Team.objects.create(name="Équipe fictive", institution=mairie, environment="DEMO")
        equipe.members.add(cadre)
        mission = Mission.objects.create(titre="Exercice", environment="DEMO")
        mission.equipes.add(equipe)

        assert salons_matrix.assurer_salons_equipe(equipe) == 0
        assert not SalonMatrixMission.objects.filter(mission=mission).exists()

    def test_le_rattrapage_cree_ce_qui_manque_a_l_existant_une_seule_fois(self, mairie, cadre, equipe):
        equipe.members.add(cadre)
        Mission.objects.create(titre="Garde du feu", environment="PROD").equipes.add(equipe)
        Mission.objects.create(titre="Sans équipe", environment="PROD")
        terminee = Mission.objects.create(titre="Ancienne", environment="PROD", statut=Mission.Statut.TERMINEE)
        terminee.equipes.add(equipe)
        inactive = Team.objects.create(name="Dissoute", institution=mairie, environment="PROD", actif=False)
        inactive.members.add(cadre)
        vide = Team.objects.create(name="Vide", institution=mairie, environment="PROD")
        # L'existant d'avant la règle : aucun salon.
        SalonMatrixEquipe.objects.all().delete()
        SalonMatrixInstitution.objects.all().delete()
        SalonMatrixMission.objects.all().delete()

        assert salons_matrix.rattraper() == {"institutions": 2, "equipes": 2, "missions": 1}
        assert salons_matrix.rattraper() == {"institutions": 0, "equipes": 0, "missions": 0}
        # Ni une mission terminée ou sans équipe, ni une équipe dissoute ou vide ne reçoivent de salon.
        assert not SalonMatrixMission.objects.filter(mission=terminee).exists()
        assert SalonMatrixMission.objects.count() == 1
        assert not SalonMatrixEquipe.objects.filter(equipe__in=[inactive, vide]).exists()

    def test_la_commande_sait_compter_sans_rien_creer(self, mairie, cadre, equipe):
        equipe.members.add(cadre)
        SalonMatrixEquipe.objects.all().delete()
        sortie = StringIO()

        call_command("rattraper_salons_matrix", "--simulation", stdout=sortie)

        assert "à créer : 0 d'institution, 2 d'équipe, 0 de mission" in sortie.getvalue()
        assert SalonMatrixEquipe.objects.count() == 0
        call_command("rattraper_salons_matrix", stdout=sortie)
        assert SalonMatrixEquipe.objects.count() == 2

    def test_un_salon_impossible_a_creer_n_empeche_pas_d_affecter_l_equipe(self, equipe, monkeypatch):
        def panne(_mission):
            raise RuntimeError("base indisponible")

        monkeypatch.setattr(salons_matrix, "assurer_salon_mission", panne)
        mission = Mission.objects.create(titre="Garde du feu", environment="PROD")

        mission.equipes.add(equipe)

        assert list(mission.equipes.all()) == [equipe]


@pytest.mark.django_db
class TestSalonDeMissionPourLePont:

    def test_le_salon_reunit_les_equipes_de_la_mission_sans_doublon(self, mairie, cadre, equipe, create_user):
        chef = create_user(username="chef@test.fr", email="chef@test.fr")
        equipier = create_user(username="equipier@test.fr", email="equipier@test.fr")
        renfort = create_user(username="renfort@test.fr", email="renfort@test.fr")
        parti = create_user(username="parti@test.fr", email="parti@test.fr", is_active=False)
        equipe.leader = chef
        equipe.save()
        equipe.members.add(chef, equipier, parti)
        autre = Team.objects.create(name="Renfort voisin", institution=mairie, environment="PROD")
        autre.members.add(renfort, equipier)             # le même équipier dans les deux équipes
        mission = Mission.objects.create(titre="Garde du feu", environment="PROD", institution=mairie)
        mission.equipes.add(equipe, autre)

        salons = _client(cadre).get(reverse("salonmatrixmission-list"), **PROD).data
        salon = next(s for s in (salons["results"] if isinstance(salons, dict) else salons)
                     if s["mission"] == mission.id)

        assert sorted(m["nom"] for m in salon["membres"]) == sorted(
            m["nom"] for m in salon["membres"] if m["id"] in {str(chef.id), str(equipier.id), str(renfort.id)})
        assert len(salon["membres"]) == 3
        assert salon["mission_titre"] == "Garde du feu"
        assert "commandée par Mairie de Saint-Étienne" in salon["sujet_salon"]

    def test_une_mission_terminee_n_est_plus_servie_au_pont(self, cadre, equipe):
        Mission.objects.create(titre="Close", environment="PROD", statut=Mission.Statut.EN_COURS).equipes.add(equipe)
        assert SalonMatrixMission.objects.filter(mission__titre="Close").exists()
        Mission.objects.filter(titre="Close").update(statut=Mission.Statut.TERMINEE)

        salons = _client(cadre).get(reverse("salonmatrixmission-list"), **PROD).data
        titres = [s["mission_titre"] for s in (salons["results"] if isinstance(salons, dict) else salons)]

        assert "Close" not in titres

    def test_le_pont_rapporte_l_identifiant_du_salon_cree(self, cadre, equipe):
        mission = Mission.objects.create(titre="Garde du feu", environment="PROD")
        mission.equipes.add(equipe)
        salon = mission.salon_matrix

        reponse = _client(cadre).patch(reverse("salonmatrixmission-detail", args=[salon.id]),
                                       {"room_id": "!abc:matrix.test"}, format="json", **PROD)

        assert reponse.status_code == 200
        salon.refresh_from_db()
        assert salon.room_id == "!abc:matrix.test" and salon.derniere_synchronisation is not None


@pytest.mark.django_db
class TestMissionDInteretGeneral:

    def _mission(self, client, **champs):
        corps = {"titre": "Garde du feu", "description": "Surveillance du massif", "interet_general": True}
        corps.update(champs)
        return client.post(reverse("mission-list"), corps, format="json", **PROD)

    def test_la_mission_est_rattachee_a_l_institution_qui_la_commande(self, cadre, mairie):
        reponse = self._mission(_client(cadre))

        assert reponse.status_code == 201
        assert reponse.data["institution"] == mairie.id and reponse.data["institution_nom"] == "Mairie de Saint-Étienne"
        assert reponse.data["interet_general"] is True and reponse.data["dossiers_generiques"] == []
        assert reponse.data["salon_matrix"] is None                 # pas d'équipe : pas encore de salon

    def test_une_mission_creee_avec_son_equipe_a_aussitot_son_salon(self, cadre, equipe, crise):
        client = _client(cadre)
        mission = self._mission(client, crise=str(crise.id), equipe_ids=[str(equipe.id)]).data

        relue = client.get(reverse("mission-detail", args=[mission["id"]]), **PROD).data

        assert relue["salon_matrix"]["pret"] is False               # créé, pas encore côté Matrix

    def test_on_ne_cree_pas_une_mission_au_nom_d_une_autre_institution(self, cadre, mairie, communes):
        lille = _institution("Mairie de Lille", "59350")

        reponse = self._mission(_client(cadre), institution=str(lille.id))

        assert reponse.status_code == 201 and reponse.data["institution"] == mairie.id

    def test_un_dossier_generique_s_ouvre_a_la_demande_au_nom_de_l_institution(self, cadre, mairie, equipe, crise):
        client = _client(cadre)
        mission = self._mission(client, crise=str(crise.id), equipe_ids=[str(equipe.id)]).data

        reponse = client.post(reverse("mission-ouvrir-dossier", args=[mission["id"]]),
                              {"description": "Garde du samedi 14 juillet, col de la République"}, format="json", **PROD)

        assert reponse.status_code == 201
        dossier = Dossier.objects.get(pk=reponse.data["id"])
        assert dossier.generique is True and dossier.institution_demandeuse == mairie
        assert str(dossier.mission_id) == mission["id"] and dossier.equipe == equipe and dossier.crise == crise
        # Ni demande, ni signalement : personne n'a appelé à l'aide.
        assert dossier.demande is None and dossier.information is None
        assert dossier.titre == "Garde du feu"                      # l'intitulé générique de la mission
        assert reponse.data["institution_demandeuse_nom"] == "Mairie de Saint-Étienne"
        historique = DossierHistorique.objects.get(dossier=dossier, evenement="Création")
        assert "à la demande de Mairie de Saint-Étienne" in historique.commentaire and historique.auteur == cadre

    def test_on_peut_en_ouvrir_plusieurs_un_par_jour_de_garde(self, cadre, equipe, crise):
        client = _client(cadre)
        mission = self._mission(client, crise=str(crise.id), equipe_ids=[str(equipe.id)]).data
        adresse = reverse("mission-ouvrir-dossier", args=[mission["id"]])

        client.post(adresse, {"description": "Samedi", "titre": "Garde du feu — samedi"}, format="json", **PROD)
        client.post(adresse, {"description": "Dimanche", "titre": "Garde du feu — dimanche"}, format="json", **PROD)

        relue = client.get(reverse("mission-detail", args=[mission["id"]]), **PROD).data
        assert sorted(d["titre"] for d in relue["dossiers_generiques"]) == ["Garde du feu — dimanche", "Garde du feu — samedi"]

    def test_une_mission_ordinaire_n_ouvre_pas_de_dossier_generique(self, cadre, equipe, crise):
        client = _client(cadre)
        mission = self._mission(client, interet_general=False, crise=str(crise.id), equipe_ids=[str(equipe.id)]).data

        reponse = client.post(reverse("mission-ouvrir-dossier", args=[mission["id"]]),
                              {"description": "x"}, format="json", **PROD)

        assert reponse.status_code == 400 and "intérêt général" in reponse.data["error"]

    def test_il_faut_dire_ce_que_couvre_le_dossier_et_a_quelle_equipe_il_va(self, cadre, mairie, equipe, crise):
        client = _client(cadre)
        autre = Team.objects.create(name="Équipe sans rapport", institution=mairie, environment="PROD")
        mission = self._mission(client, crise=str(crise.id), equipe_ids=[str(equipe.id)]).data
        adresse = reverse("mission-ouvrir-dossier", args=[mission["id"]])

        assert client.post(adresse, {"description": "  "}, format="json", **PROD).status_code == 400
        hors_mission = client.post(adresse, {"description": "x", "equipe_id": str(autre.id)}, format="json", **PROD)
        assert hors_mission.status_code == 400 and "pas affectée" in hors_mission.data["error"]

    def test_sans_crise_sur_la_mission_il_faut_en_designer_une(self, cadre, equipe, crise):
        """Limite connue : un dossier appartient toujours à une crise."""
        client = _client(cadre)
        mission = self._mission(client, equipe_ids=[str(equipe.id)]).data
        adresse = reverse("mission-ouvrir-dossier", args=[mission["id"]])

        sans = client.post(adresse, {"description": "Ronde"}, format="json", **PROD)
        avec = client.post(adresse, {"description": "Ronde", "crise_id": str(crise.id)}, format="json", **PROD)

        assert sans.status_code == 400 and sans.data["choix_requis"] == "crise"
        assert avec.status_code == 201 and Dossier.objects.get(pk=avec.data["id"]).crise == crise

    def test_une_autre_institution_n_ouvre_pas_de_dossier_sur_cette_mission(self, cadre, equipe, crise, create_user, communes):
        mission = self._mission(_client(cadre), crise=str(crise.id), equipe_ids=[str(equipe.id)]).data
        voisin = _cadre(create_user, _institution("Mairie de Lille", "59350"), "cadre@lille.fr")

        reponse = _client(voisin).post(reverse("mission-ouvrir-dossier", args=[mission["id"]]),
                                       {"description": "x"}, format="json", **PROD)

        assert reponse.status_code == 403 and Dossier.objects.count() == 0

    def test_un_dossier_ne_devient_pas_generique_apres_coup(self, cadre, equipe, crise):
        """Ni la qualité de générique ni l'institution demandeuse ne se modifient par l'API."""
        client = _client(cadre)
        mission = self._mission(client, crise=str(crise.id), equipe_ids=[str(equipe.id)]).data
        dossier = client.post(reverse("mission-ouvrir-dossier", args=[mission["id"]]),
                              {"description": "Garde"}, format="json", **PROD).data

        client.patch(reverse("dossier-detail", args=[dossier["id"]]),
                     {"generique": False, "institution_demandeuse": None}, format="json", **PROD)

        relu = Dossier.objects.get(pk=dossier["id"])
        assert relu.generique is True and relu.institution_demandeuse is not None
