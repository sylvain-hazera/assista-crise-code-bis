"""Radios des intervenants (25/11/2026, vision d'Olivier F4GLD) : emplacements d'urgence 5-6-7
(crise, équipe, commune), lien de canal Meshtastic (QR code) et nœuds dédiés d'équipe."""
import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from rest_framework.test import APIClient

from core import radio_equipe as re_
from core.models import (
    CompagnonMeshtastic, ContactInstitution, Crisis, Institution, InstitutionType, MeshtasticConnexionType,
    NoeudEquipe, TacheAdminMeshtastic, Team,
)


@pytest.fixture(autouse=True)
def _canaux_d_equipe_automatiques(settings):
    settings.CANAUX_EQUIPE_AUTO = True


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def scene(db, create_user):
    itype, _ = InstitutionType.objects.get_or_create(code="COMMUNE", defaults={"libelle": "Commune"})
    mairie = Institution.objects.create(nom="Mairie de Rive-de-Gier", type=itype)
    chef = create_user(username="chef@rive.fr", email="chef@rive.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=mairie, utilisateur=chef, actif=True)
    membre = create_user(username="membre@rive.fr", email="membre@rive.fr", type="VOLUNTEER")
    intrus = create_user(username="intrus@rive.fr", email="intrus@rive.fr", type="VOLUNTEER")
    equipe = Team.objects.create(name="Alpha", institution=mairie, leader=chef)
    equipe.members.add(membre)
    return {"mairie": mairie, "equipe": equipe, "chef": _client(chef), "membre": _client(membre),
            "intrus": _client(intrus), "chef_user": chef}


@pytest.mark.django_db
class TestPlanUrgence:
    def test_hors_crise_equipe_puis_commune(self, scene):
        plan = scene["membre"].get(reverse("team-plan-urgence", args=[scene["equipe"].id])).data
        assert [e["role"] for e in plan["meshtastic"]] == ["equipe", "commune"]
        assert plan["meshtastic"][0]["nom"] == "AC-ALPH" and len(plan["meshtastic"][0]["cle_hex"]) == 32
        assert plan["crise"] is None

    def test_en_crise_crise_equipe_commune_dans_cet_ordre(self, scene):
        crise = Crisis.objects.create(name="Crue du Gier", type="INONDATION", location=Point(4.6, 45.5, srid=4326))
        scene["equipe"].assigned_crises.add(crise)
        plan = scene["membre"].get(reverse("team-plan-urgence", args=[scene["equipe"].id])).data
        assert [e["role"] for e in plan["meshtastic"]] == ["crise", "equipe", "commune"]
        assert [e["role"] for e in plan["meshcore"]][:2] == ["crise", "equipe"]
        assert plan["nom_crise"] == "Crue du Gier"

    def test_reserve_aux_membres(self, scene):
        assert scene["intrus"].get(reverse("team-plan-urgence", args=[scene["equipe"].id])).status_code == 403


@pytest.mark.django_db
class TestLienDeCanal:
    def test_aller_retour_avec_le_lecteur_et_mode_ajouter(self):
        lien = re_.lien_meshtastic([("AC-ALPH", "ab" * 16), ("Rive", "01")])
        assert lien.startswith("https://meshtastic.org/e/?add=true#")
        assert re_.lire_lien_meshtastic(lien) == [("AC-ALPH", bytes.fromhex("ab" * 16)), ("Rive", b"\x01")]

    def test_lien_de_l_equipe_reserve_aux_gestionnaires(self, scene):
        url = reverse("team-lien-canaux", args=[scene["equipe"].id])
        assert scene["membre"].get(url).status_code == 403
        donnees = scene["chef"].get(url).data
        noms = [n for n, _ in re_.lire_lien_meshtastic(donnees["meshtastic_lien"])]
        assert noms[0] == "AC-ALPH"

    def test_lien_de_la_crise_clefs_publiques(self, scene):
        crise = Crisis.objects.create(name="Crue", type="INONDATION", location=Point(4.6, 45.5, srid=4326))
        scene["equipe"].assigned_crises.add(crise)
        reponse = scene["membre"].get(reverse("radio-lien-crise") + f"?crise={crise.id}")
        assert reponse.status_code == 200, reponse.data
        [(nom, cle)] = re_.lire_lien_meshtastic(reponse.data["meshtastic_lien"])
        assert cle == b"\x01"                                  # clé publique par défaut
        assert scene["intrus"].get(reverse("radio-lien-crise") + f"?crise={crise.id}").status_code == 403


@pytest.mark.django_db
class TestNoeudsDedies:
    def test_enregistrer_configurer_confier(self, scene):
        url = reverse("team-noeuds", args=[scene["equipe"].id])
        reponse = scene["chef"].post(url, {"protocole": "MESHTASTIC", "identifiant": "!A1B2C3D4", "nom": "ALPH-1",
                                           "configure": True}, format="json")
        assert reponse.status_code == 200, reponse.data
        [noeud] = reponse.data["noeuds"]
        assert noeud["identifiant"] == "a1b2c3d4" and noeud["a_jour"] and noeud["moyen_configuration"] == "BLUETOOTH"
        detail = reverse("team-noeud", args=[scene["equipe"].id, noeud["id"]])
        confie = scene["chef"].patch(detail, {"confie_a": str(scene["chef_user"].id)}, format="json").data
        assert confie["etat"] == "CONFIE"

    def test_un_noeud_ne_sert_qu_a_une_equipe(self, scene):
        autre = Team.objects.create(name="Bravo", institution=scene["mairie"], leader=scene["chef_user"])
        scene["chef"].post(reverse("team-noeuds", args=[scene["equipe"].id]), {"protocole": "MESHCORE", "identifiant": "ab" * 32}, format="json")
        reponse = scene["chef"].post(reverse("team-noeuds", args=[autre.id]), {"protocole": "MESHCORE", "identifiant": "ab" * 32}, format="json")
        assert reponse.status_code == 400 and "Alpha" in reponse.data["error"]

    def test_un_membre_ne_gere_pas_les_noeuds(self, scene):
        assert scene["membre"].get(reverse("team-noeuds", args=[scene["equipe"].id])).status_code == 403

    def test_configurer_a_distance_sans_cle_dans_la_tache(self, scene, create_user):
        CompagnonMeshtastic.objects.create(nom="Passerelle Rive", node_num=7, institution=scene["mairie"],
                                           connexion_type=MeshtasticConnexionType.TCP, tcp_host="10.0.0.2")
        noeud = NoeudEquipe.objects.create(equipe=scene["equipe"], protocole="MESHTASTIC", identifiant="a1b2c3d4")
        reponse = scene["chef"].post(reverse("team-configurer-noeud-a-distance", args=[scene["equipe"].id, noeud.id]))
        assert reponse.status_code == 200, reponse.data
        taches = list(TacheAdminMeshtastic.objects.filter(node_num_cible=0xA1B2C3D4).order_by("date_creation"))
        assert [t.parametres["index"] for t in taches] == [6, 7]          # hors crise : équipe, commune
        cle_equipe = scene["equipe"].canal_meshtastic.psk_hex
        assert all(cle_equipe not in str(t.parametres) for t in taches)

        # Le pont, lui, reçoit la clé au moment de prendre la tâche.
        pont = APIClient()
        pont.force_authenticate(user=create_user(username="pont@x.fr", email="pont@x.fr", type="ADMIN"))
        prises = pont.post(reverse("tacheadminmeshtastic-prendre"), {"compagnon": str(taches[0].compagnon_id)}, format="json").data
        assert {t["parametres"]["psk_hex"] for t in prises} >= {cle_equipe}
        TacheAdminMeshtastic.objects.update(statut="EN_ATTENTE")
        assert all(cle_equipe not in str(t.parametres) for t in TacheAdminMeshtastic.objects.all())

    def test_ecrire_un_canal_interdit_par_l_api_generique(self, create_user):
        admin = APIClient()
        admin.force_authenticate(user=create_user(username="adm@x.fr", email="adm@x.fr", type="ADMIN"))
        compagnon = CompagnonMeshtastic.objects.create(nom="P", node_num=8, connexion_type=MeshtasticConnexionType.TCP, tcp_host="h")
        reponse = admin.post(reverse("tacheadminmeshtastic-list"), {"compagnon": str(compagnon.id), "node_num_cible": 5,
                                                                    "type_tache": "DEFINIR_CANAL", "parametres": {"index": 5}}, format="json")
        assert reponse.status_code == 400
