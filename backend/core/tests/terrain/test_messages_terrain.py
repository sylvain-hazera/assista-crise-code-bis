"""Messages de terrain en un geste, par les données ou par radio (22/11/2026)."""
from unittest import mock

import pytest
from django.contrib.gis.geos import Point
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from core import messages_terrain as mt
from core.models import Crisis, Institution, InstitutionType, MessageTerrain, Mission, Team, User


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.fixture
def terrain(db):
    itype, _ = InstitutionType.objects.get_or_create(code="mairie", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie essai", type=itype, commune_code="42186")
    benevole = User.objects.create_user(username="benevole-t@test.fr", email="benevole-t@test.fr", password="x", type="UTIL_SIMPLE",
                                        first_name="Léa", last_name="Martin")
    chef = User.objects.create_user(username="chef-t@test.fr", email="chef-t@test.fr", password="x", type="SECOURS")
    tiers = User.objects.create_user(username="tiers-t@test.fr", email="tiers-t@test.fr", password="x", type="UTIL_SIMPLE")
    equipe = Team.objects.create(name="Équipe Gier", institution=mairie, leader=chef, environment="PROD")
    equipe.members.add(benevole)
    crise = Crisis.objects.create(name="Crue", type="INONDATION", location=Point(4.6, 45.5, srid=4326))
    mission = Mission.objects.create(titre="Évacuation", crise=crise, institution=mairie, statut="EN_COURS", environment="PROD")
    mission.equipes.add(equipe)
    return dict(benevole=benevole, chef=chef, tiers=tiers, equipe=equipe, mission=mission, crise=crise)


def _envoyer(u, mission, type_, **extra):
    with mock.patch("core.notifications_application.prevenir"):
        return _client(u).post(reverse("messageterrain-list"),
                               {"mission": str(mission.id), "type": type_, "identifiant_client": extra.pop("ident", "a1b2c3"), **extra},
                               format="json")


@pytest.mark.django_db
def test_un_benevole_de_l_equipe_declare_son_arrivee(terrain):
    r = _envoyer(terrain["benevole"], terrain["mission"], "ARRIVE")
    assert r.status_code == 201, r.data
    m = MessageTerrain.objects.get()
    assert (m.type, m.equipe, m.crise, m.canal) == ("ARRIVE", terrain["equipe"], terrain["crise"], "DONNEES")
    statuts = _client(terrain["chef"]).get(reverse("messageterrain-statuts"), {"mission": str(terrain["mission"].id)}).data
    assert statuts[0]["statut"] == "Sur place" and statuts[0]["auteur_nom"] == "Léa Martin"


@pytest.mark.django_db
def test_un_tiers_ne_peut_ni_ecrire_ni_lire(terrain):
    assert _envoyer(terrain["tiers"], terrain["mission"], "ARRIVE").status_code == 403
    r = _client(terrain["tiers"]).get(reverse("messageterrain-list"), {"mission": str(terrain["mission"].id)})
    assert r.status_code == 403


@pytest.mark.django_db
def test_les_dix_types_et_le_motif_obligatoire_des_secours(terrain):
    for n, type_ in enumerate(MessageTerrain.Type.values):
        extra = {"texte": "chute, cheville"} if type_ in ("PREMIERS_SECOURS", "SITUATION") else {}
        if type_ == "RENFORT":
            extra["nombre"] = 3
        assert _envoyer(terrain["benevole"], terrain["mission"], type_, ident=f"id{n:04d}", **extra).status_code == 201, type_
    r = _envoyer(terrain["benevole"], terrain["mission"], "PREMIERS_SECOURS", ident="sansmot")
    assert r.status_code == 400 and "motif" in r.data["error"]


@pytest.mark.django_db
def test_secours_et_danger_alertent_aussitot_le_chef_et_la_mairie(terrain):
    mairie_agent = User.objects.create_user(username="agent-t@test.fr", email="agent-t@test.fr", password="x",
                                            type="AUT_LOCALE", institution=terrain["mission"].institution,
                                            is_active=True)
    r = _envoyer(terrain["benevole"], terrain["mission"], "PREMIERS_SECOURS", texte="malaise d'un habitant",
                 latitude=45.5, longitude=4.6)
    assert r.status_code == 201 and r.data["prioritaire"] is True
    mairie_agent.refresh_from_db()
    assert (mairie_agent.is_active, mairie_agent.institution_id, mairie_agent.type) == (True, terrain["mission"].institution_id, "AUT_LOCALE")
    (courriel,) = mail.outbox
    assert set(courriel.to) == {"chef-t@test.fr", mairie_agent.email}
    assert "malaise d'un habitant" in courriel.body and "45.5, 4.6" in courriel.body


@pytest.mark.django_db
def test_un_message_recu_par_radio_puis_par_les_donnees_n_est_enregistre_qu_une_fois(terrain):
    benevole, mission = terrain["benevole"], terrain["mission"]
    texte = f"Léa: ⚑ARR {mission.id.hex[:6]}.{benevole.id.hex[:6]}.a1b2c3 Arrivé sur les lieux"
    m = mt.depuis_radio(texte, "MESHCORE")
    assert m is not None and m.canal == "MESHCORE" and m.auteur == benevole and m.mission == mission
    r = _envoyer(benevole, mission, "ARRIVE", ident="a1b2c3")
    assert r.status_code == 200
    assert MessageTerrain.objects.count() == 1 and MessageTerrain.objects.get().canaux_recus == ["MESHCORE", "DONNEES"]


def test_lecture_des_etiquettes():
    lu = mt.lire_etiquette("⚑PS 3f2a9c.9c1e0b.a1b2c3 Premiers secours : chute")
    assert lu == {"type": "PREMIERS_SECOURS", "mission6": "3f2a9c", "auteur6": "9c1e0b", "ident": "a1b2c3",
                  "dossier6": None, "texte": "Premiers secours : chute"}
    assert mt.lire_etiquette("Bonjour à tous") is None
    assert mt.lire_etiquette("⚑XYZ 3f2a9c.9c1e0b.a1b2c3") is None


@pytest.mark.django_db
def test_un_inconnu_par_radio_est_ignore(terrain):
    texte = f"⚑ARR {terrain['mission'].id.hex[:6]}.ffffff.a1b2c3 Arrivé"
    assert mt.depuis_radio(texte, "MESHTASTIC") is None and not MessageTerrain.objects.exists()


@pytest.mark.django_db
def test_le_message_radio_entrant_d_un_canal_meshcore_est_reconnu(terrain):
    from core.models import CanalMeshCore
    admin = User.objects.create_user(username="pont-t@test.fr", email="pont-t@test.fr", password="x", type="ADMIN")
    canal = CanalMeshCore.objects.create(nom="Equipe Gier", environment="PROD")
    benevole, mission = terrain["benevole"], terrain["mission"]
    with mock.patch("core.notifications_application.prevenir"):
        r = _client(admin).post(reverse("messagecanalmeshcore-list"), {
            "canal": canal.id, "direction": "ENTRANT",
            "contenu": f"Léa: ⚑FIN {mission.id.hex[:6]}.{benevole.id.hex[:6]}.c0ffee Intervention terminée"}, format="json")
    assert r.status_code in (200, 201), r.data
    assert MessageTerrain.objects.filter(type="TERMINEE", canal="MESHCORE").exists()


@pytest.mark.django_db
def test_en_formation_l_alerte_ne_part_qu_a_l_auteur(terrain):
    mission = terrain["mission"]
    mission.environment = "DEMO"
    mission.save(update_fields=["environment"])
    sans_role = _client(terrain["benevole"]).post(reverse("messageterrain-list"), {
        "mission": str(mission.id), "type": "ARRIVE", "identifiant_client": "s4n5r0"}, format="json", HTTP_X_ENVIRONMENT="DEMO")
    assert sans_role.status_code == 403
    terrain["benevole"].demo_role = "UTIL_SIMPLE"
    terrain["benevole"].save(update_fields=["demo_role"])
    with mock.patch("core.notifications_application.prevenir") as dm:
        r = _client(terrain["benevole"]).post(reverse("messageterrain-list"), {
            "mission": str(mission.id), "type": "DANGER", "texte": "toit instable", "identifiant_client": "d3m0d3"},
            format="json", HTTP_X_ENVIRONMENT="DEMO")
    assert r.status_code == 201, r.data
    (courriel,) = mail.outbox
    assert courriel.to == ["benevole-t@test.fr"] and courriel.subject.startswith("[assista-crise] [DEMO]")
    assert {c.args[0] for c in dm.call_args_list} <= {terrain["benevole"]}
    assert MessageTerrain.objects.get().environment == "DEMO"


@pytest.mark.django_db
def test_le_message_porte_son_dossier_par_les_donnees_et_par_radio(terrain):
    from core.models import Dossier
    benevole, mission = terrain["benevole"], terrain["mission"]
    dossier = Dossier.objects.create(numero="D-42", titre="Cave inondée", crise=terrain["crise"], equipe=terrain["equipe"], mission=mission)
    # Par les données, le dossier seul suffit : la mission s'en déduit.
    with mock.patch("core.notifications_application.prevenir"):
        r = _client(benevole).post(reverse("messageterrain-list"), {"dossier": str(dossier.id), "type": "ARRIVE",
                                                                    "identifiant_client": "aaaaa1"}, format="json")
    assert r.status_code == 201, r.data
    assert (r.data["dossier_numero"], r.data["mission"]) == ("D-42", mission.id)
    # Par radio, le quatrième groupe de l'étiquette désigne le dossier.
    texte = f"⚑FIN {mission.id.hex[:6]}.{benevole.id.hex[:6]}.bbbbb2.{dossier.id.hex[:6]} Intervention terminée"
    m = mt.depuis_radio(texte, "MESHCORE")
    assert m.dossier == dossier and m.type == "TERMINEE"
    # Un dossier d'une autre équipe : refusé.
    autre = Dossier.objects.create(numero="D-43", crise=terrain["crise"])
    r = _client(benevole).post(reverse("messageterrain-list"), {"dossier": str(autre.id), "type": "ARRIVE",
                                                                "identifiant_client": "ccccc3"}, format="json")
    assert r.status_code == 403


@pytest.mark.django_db
def test_le_pilotage_voit_le_terrain_et_prend_en_compte_le_danger(terrain):
    """23/11/2026 : terrain en direct dans le pilotage ; une alerte Danger reste en tête tant
    que le poste de commandement ne l'a pas prise en compte."""
    _envoyer(terrain["benevole"], terrain["mission"], "ARRIVE", ident="aaaaa1")
    _envoyer(terrain["benevole"], terrain["mission"], "DANGER", ident="aaaaa2", texte="Mur fissuré")
    pc = User.objects.create_user(username="pc-t@test.fr", email="pc-t@test.fr", password="x", type="AUT_LOCALE")
    vue = _client(pc).get(reverse("messageterrain-crise"), {"crise": str(terrain["crise"].id)}).data
    assert [a["type"] for a in vue["alertes"]] == ["DANGER"]
    assert vue["statuts"][0]["statut"] == "Danger signalé" and len(vue["derniers"]) == 2
    alerte = vue["alertes"][0]["id"]
    r = _client(pc).post(reverse("messageterrain-prendre-en-compte", args=[alerte]))
    assert r.status_code == 200 and r.data["pris_en_compte_le"]
    assert _client(pc).get(reverse("messageterrain-crise"), {"crise": str(terrain["crise"].id)}).data["alertes"] == []
    # Un bénévole n'a ni la vue du poste de commandement, ni la prise en compte.
    assert _client(terrain["benevole"]).get(reverse("messageterrain-crise"), {"crise": str(terrain["crise"].id)}).status_code == 403
    assert _client(terrain["benevole"]).post(reverse("messageterrain-prendre-en-compte", args=[alerte])).status_code == 403
