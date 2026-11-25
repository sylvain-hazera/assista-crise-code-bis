"""Canal radio et indicatif par défaut de chaque équipe (25/11/2026) : créés d'office,
personnalisables (nom et clé de la structure, ou reprise d'un canal de sa passerelle), clé
jamais montrée sur le site, donnée aux seules radios des membres."""
import base64
import importlib

import pytest
from django.apps import apps as django_apps
from django.urls import reverse
from rest_framework.test import APIClient

from core import radio_equipe as re_
from core.models import (
    CanalMeshCore, CanalMeshCoreDetecte, CanalMeshtastic, CompagnonMeshCore, CompagnonMeshtastic,
    ContactInstitution, Institution, InstitutionType, ProvisionCanalMeshCore, Team,
)
from core.views import _canaux_meshcore_du_compagnon

CLE_ADRASEC = "00112233445566778899aabbccddeeff"


@pytest.fixture(autouse=True)
def _canaux_d_equipe_automatiques(settings):
    settings.CANAUX_EQUIPE_AUTO = True


@pytest.fixture
def adrasec(db):
    itype, _ = InstitutionType.objects.get_or_create(code="ASSOCIATION", defaults={"libelle": "Association"})
    return Institution.objects.create(nom="ADRASEC 42", type=itype)


@pytest.fixture
def admin(create_user):
    client = APIClient()
    client.force_authenticate(user=create_user(username="admin-radio@test.fr", email="admin-radio@test.fr", type="ADMIN"))
    return client


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
class TestParDefaut:
    def test_une_equipe_creee_recoit_indicatif_unique_et_deux_canaux(self, adrasec):
        alpha = Team.objects.create(name="Équipe Alpha", institution=adrasec)
        alpha2 = Team.objects.create(name="Alpha", institution=adrasec)
        alpha.refresh_from_db(); alpha2.refresh_from_db()
        assert alpha.indicatif == "ALPHA" and alpha2.indicatif == "ALPHA2"
        assert alpha.canal_meshtastic.nom == "AC-ALPHA" and alpha.canal_meshcore.nom == "AC-ALPHA"
        assert len(alpha.canal_meshtastic.psk_hex) == 32 and len(alpha.canal_meshcore.cle_partagee_hex) == 32
        assert alpha.canal_meshtastic.psk_hex != alpha2.canal_meshtastic.psk_hex
        assert not alpha.canal_meshcore.sur_passerelle

    def test_cle_chiffree_en_base(self, adrasec):
        from django.db import connection
        equipe = Team.objects.create(name="Bravo", institution=adrasec)
        cle = equipe.canal_meshcore.cle_partagee_hex
        with connection.cursor() as c:
            c.execute("select cle_partagee_hex from core_canalmeshcore where id = %s", [equipe.canal_meshcore.id])
            brut = c.fetchone()[0]
        assert cle not in brut

    def test_indicatif_en_double_refuse(self, admin, adrasec):
        Team.objects.create(name="Alpha", institution=adrasec)
        bravo = Team.objects.create(name="Bravo", institution=adrasec)
        reponse = admin.patch(reverse("team-detail", args=[bravo.id]), {"indicatif": "alpha"}, format="json")
        assert reponse.status_code == 400 and "Alpha" in str(reponse.data["indicatif"])

    def test_changer_l_indicatif_renomme_le_canal_par_defaut_pas_le_personnalise(self, admin, adrasec):
        equipe = Team.objects.create(name="Charlie", institution=adrasec)
        re_.personnaliser(equipe, re_.MESHCORE, "ADRA42", CLE_ADRASEC)
        reponse = admin.patch(reverse("team-detail", args=[equipe.id]), {"indicatif": "CH1"}, format="json")
        assert reponse.status_code == 200, reponse.data
        equipe = Team.objects.get(pk=equipe.pk)
        assert equipe.canal_meshtastic.nom == "AC-CH1"
        assert equipe.canal_meshcore.nom == "ADRA42"

    def test_equipe_desactivee_canal_par_defaut_inactif(self, adrasec):
        equipe = Team.objects.create(name="Delta", institution=adrasec)
        equipe.actif = False
        equipe.save()
        assert not CanalMeshtastic.objects.get(equipe=equipe).actif

    def test_passerelle_n_installe_pas_un_canal_par_defaut_mais_le_decode(self, admin, adrasec):
        compagnon = CompagnonMeshCore.objects.create(nom="Bureau", principal=True)
        equipe = Team.objects.create(name="Echo", institution=adrasec)
        ancien = Team.objects.create(name="Vieille").canal_meshcore   # un ancien canal, déjà sur les passerelles
        CanalMeshCore.objects.filter(pk=ancien.pk).update(nom="Équipe Ancienne", sur_passerelle=True, personnalise=True)
        a_installer = set(_canaux_meshcore_du_compagnon(compagnon).values_list("id", flat=True))
        assert equipe.canal_meshcore.id not in a_installer and ancien.id in a_installer
        decode = admin.get(reverse("compagnonmeshcore-canaux-pour-decodage-logiciel", args=[compagnon.id]))
        assert str(equipe.canal_meshcore.id) in {c["id"] for c in decode.data}


@pytest.mark.django_db
class TestPersonnaliser:
    @pytest.fixture
    def scene(self, create_user, adrasec):
        chef = create_user(username="chef@adrasec.fr", email="chef@adrasec.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=adrasec, utilisateur=chef, actif=True)
        equipe = Team.objects.create(name="Radio", institution=adrasec, leader=chef)
        membre = create_user(username="membre@adrasec.fr", email="membre@adrasec.fr", type="VOLUNTEER")
        equipe.members.add(membre)
        return {"equipe": equipe, "chef": _client(chef), "membre": _client(membre)}

    def _post(self, client, equipe, **donnees):
        return client.post(reverse("team-canal-radio", args=[equipe.id]), donnees, format="json")

    @pytest.mark.parametrize("saisie", [
        CLE_ADRASEC,
        base64.b64encode(bytes.fromhex(CLE_ADRASEC)).decode(),
        base64.b64encode(bytes.fromhex(CLE_ADRASEC)).decode().rstrip("="),
    ])
    def test_cle_de_la_structure_hex_ou_base64(self, scene, saisie):
        reponse = self._post(scene["chef"], scene["equipe"], protocole="MESHTASTIC", nom="ADRA42", cle=saisie)
        assert reponse.status_code == 200, reponse.data
        canal = CanalMeshtastic.objects.get(equipe=scene["equipe"])
        assert canal.psk_hex == CLE_ADRASEC and canal.cle_fournie and canal.personnalise
        assert CLE_ADRASEC not in str(reponse.data)
        assert reponse.data["canaux_radio"]["meshtastic"]["empreinte"] == re_.empreinte(CLE_ADRASEC)

    def test_lien_de_canal_meshtastic(self, scene):
        # ChannelSet { settings { psk: <16 octets>, name: "ADRA42" } }
        psk = bytes.fromhex(CLE_ADRASEC)
        reglages = b"\x12" + bytes([len(psk)]) + psk + b"\x1a\x06ADRA42"
        lien = "https://meshtastic.org/e/#" + base64.urlsafe_b64encode(b"\x0a" + bytes([len(reglages)]) + reglages).decode().rstrip("=")
        reponse = self._post(scene["chef"], scene["equipe"], protocole="MESHTASTIC", nom="ADRA42", cle=lien)
        assert reponse.status_code == 200, reponse.data
        assert CanalMeshtastic.objects.get(equipe=scene["equipe"]).psk_hex == CLE_ADRASEC

    def test_cle_publique_meshtastic_refusee_sauf_en_clair(self, scene):
        assert self._post(scene["chef"], scene["equipe"], protocole="MESHTASTIC", nom="ADRA42", cle="AQ==").status_code == 400
        assert self._post(scene["chef"], scene["equipe"], protocole="MESHTASTIC", nom="ADRA42", cle="AQ==",
                          en_clair=True).status_code == 200

    def test_longueur_fausse_et_nom_trop_long_refuses(self, scene):
        assert self._post(scene["chef"], scene["equipe"], protocole="MESHCORE", nom="ADRA", cle="00" * 8).status_code == 400
        assert self._post(scene["chef"], scene["equipe"], protocole="MESHTASTIC", nom="ADRASEC Loire 42").status_code == 400

    def test_nom_d_une_autre_equipe_refuse(self, scene, adrasec):
        autre = Team.objects.create(name="Autre", institution=adrasec)
        re_.personnaliser(autre, re_.MESHCORE, "ADRA42", CLE_ADRASEC)
        reponse = self._post(scene["chef"], scene["equipe"], protocole="MESHCORE", nom="adra42")
        assert reponse.status_code == 400 and "autre équipe" in reponse.data["error"]

    def test_meshcore_public_diese_sans_cle(self, scene):
        assert self._post(scene["chef"], scene["equipe"], protocole="MESHCORE", nom="#adrasec42").status_code == 200
        canal = CanalMeshCore.objects.get(equipe=scene["equipe"])
        assert canal.cle_partagee_hex == CanalMeshCore.derive_cle_publique("#adrasec42")

    def test_nom_seul_cle_generee(self, scene):
        assert self._post(scene["chef"], scene["equipe"], protocole="MESHCORE", nom="Radio42").status_code == 200
        canal = CanalMeshCore.objects.get(equipe=scene["equipe"])
        assert canal.personnalise and not canal.cle_fournie and len(canal.cle_partagee_hex) == 32

    def test_regeneration_impossible_sur_une_cle_fournie(self, scene, admin):
        self._post(scene["chef"], scene["equipe"], protocole="MESHCORE", nom="ADRA42", cle=CLE_ADRASEC)
        reponse = admin.post(reverse("team-provisionner-canal-meshcore", args=[scene["equipe"].id]), {"regenerer": True}, format="json")
        assert reponse.status_code == 400
        assert CanalMeshCore.objects.get(equipe=scene["equipe"]).cle_partagee_hex == CLE_ADRASEC

    def test_retour_au_defaut(self, scene):
        self._post(scene["chef"], scene["equipe"], protocole="MESHCORE", nom="ADRA42", cle=CLE_ADRASEC)
        reponse = scene["chef"].delete(reverse("team-canal-radio", args=[scene["equipe"].id]) + "?protocole=MESHCORE")
        assert reponse.status_code == 200, reponse.data
        canal = CanalMeshCore.objects.get(equipe=scene["equipe"])
        assert canal.nom == "AC-RADIO" and not canal.personnalise and canal.cle_partagee_hex != CLE_ADRASEC

    def test_un_membre_ne_personnalise_pas_mais_lit_ses_cles(self, scene):
        assert self._post(scene["membre"], scene["equipe"], protocole="MESHCORE", nom="X1").status_code == 403
        self._post(scene["chef"], scene["equipe"], protocole="MESHCORE", nom="ADRA42", cle=CLE_ADRASEC)
        [entree] = scene["membre"].get(reverse("team-mes-canaux-radio")).data
        assert entree["indicatif"] == "RADIO" and entree["meshcore"] == {
            "nom": "ADRA42", "cle_hex": CLE_ADRASEC, "version": re_.version(CanalMeshCore.objects.get(equipe=scene["equipe"]))}
        assert entree["meshtastic"]["nom"] == "AC-RADIO" and len(entree["meshtastic"]["psk_hex"]) == 32

    def test_la_liste_des_equipes_ne_donne_jamais_la_cle(self, scene):
        self._post(scene["chef"], scene["equipe"], protocole="MESHCORE", nom="ADRA42", cle=CLE_ADRASEC)
        donnees = scene["chef"].get(reverse("team-mes-equipes")).data
        assert CLE_ADRASEC not in str(donnees)
        assert donnees[0]["canaux_radio"]["meshcore"]["cle_fournie"] is True

    def test_un_non_membre_n_a_aucun_canal(self, create_user, scene):
        intrus = _client(create_user(username="intrus@x.fr", email="intrus@x.fr", type="VOLUNTEER"))
        assert intrus.get(reverse("team-mes-canaux-radio")).data == []


@pytest.mark.django_db
class TestReprendre:
    @pytest.fixture
    def scene(self, create_user, adrasec):
        chef = create_user(username="chef2@adrasec.fr", email="chef2@adrasec.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=adrasec, utilisateur=chef, actif=True)
        equipe = Team.objects.create(name="Relais", institution=adrasec, leader=chef)
        radio_mc = CompagnonMeshCore.objects.create(nom="Passerelle ADRASEC", institution=adrasec)
        radio_mt = CompagnonMeshtastic.objects.create(nom="Passerelle MT ADRASEC", node_num=42, institution=adrasec)
        interne = CanalMeshCore.objects.create(nom="ADRA-INT", institution=adrasec, cle_partagee_hex=CLE_ADRASEC)
        ProvisionCanalMeshCore.objects.create(canal=interne, compagnon=radio_mc, canal_idx=3)
        public = CanalMeshCore.objects.create(nom="Public", cle_partagee_hex=CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT)
        ProvisionCanalMeshCore.objects.create(canal=public, compagnon=radio_mc, canal_idx=0)
        mt_interne = CanalMeshtastic.objects.create(nom="ADRAMT", psk_hex=CLE_ADRASEC, compagnon=radio_mt, institution=adrasec)
        CanalMeshtastic.objects.create(nom="Fr_EMCOM", psk_hex=CLE_ADRASEC, compagnon=radio_mt)
        CanalMeshCoreDetecte.objects.create(compagnon=radio_mc, chan_hash="ab")
        return {"equipe": equipe, "chef": _client(chef), "interne": interne, "mt_interne": mt_interne, "radio_mc": radio_mc}

    def test_liste_sans_cle_ni_canaux_communs(self, scene):
        donnees = scene["chef"].get(reverse("team-canaux-passerelle", args=[scene["equipe"].id])).data
        assert sorted(c["nom"] for c in donnees["canaux"]) == ["ADRA-INT", "ADRAMT"]
        assert donnees["entendus_sans_cle"] == 1
        assert CLE_ADRASEC not in str(donnees)

    def test_reprendre_puis_revenir_au_defaut(self, scene):
        url = reverse("team-canal-radio", args=[scene["equipe"].id])
        reponse = scene["chef"].post(url, {"protocole": "MESHCORE", "reprendre": str(scene["interne"].id)}, format="json")
        assert reponse.status_code == 200, reponse.data
        interne = CanalMeshCore.objects.get(pk=scene["interne"].pk)
        assert interne.equipe_id == scene["equipe"].pk and interne.repris and interne.sur_passerelle
        assert not CanalMeshCore.objects.filter(nom="AC-RELAIS").exists()
        assert interne.provisions.count() == 1                       # rien à réinstaller sur la passerelle

        scene["chef"].delete(url + "?protocole=MESHCORE")
        interne.refresh_from_db()
        assert interne.equipe_id is None and interne.actif           # rendu à l'entité
        assert CanalMeshCore.objects.get(equipe=scene["equipe"]).nom == "AC-RELAIS"

    def test_reprendre_un_canal_meshtastic(self, scene):
        reponse = scene["chef"].post(reverse("team-canal-radio", args=[scene["equipe"].id]),
                                     {"protocole": "MESHTASTIC", "reprendre": str(scene["mt_interne"].id)}, format="json")
        assert reponse.status_code == 200, reponse.data
        assert CanalMeshtastic.objects.get(equipe=scene["equipe"]).nom == "ADRAMT"

    def test_une_autre_institution_ne_reprend_pas(self, create_user, scene):
        itype, _ = InstitutionType.objects.get_or_create(code="COMMUNE", defaults={"libelle": "Commune"})
        voisine = Institution.objects.create(nom="Mairie voisine", type=itype)
        chef = create_user(username="chef@voisine.fr", email="chef@voisine.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=voisine, utilisateur=chef, actif=True)
        equipe = Team.objects.create(name="Voisins", institution=voisine, leader=chef)
        reponse = _client(chef).post(reverse("team-canal-radio", args=[equipe.id]),
                                     {"protocole": "MESHCORE", "reprendre": str(scene["interne"].id)}, format="json")
        assert reponse.status_code == 400
        assert CanalMeshCore.objects.get(pk=scene["interne"].pk).equipe_id is None


@pytest.mark.django_db
def test_migration_donne_indicatif_et_canaux_aux_equipes_existantes(adrasec):
    from django.db.models.signals import post_save
    from core.radio_equipe import equipe_enregistree

    post_save.disconnect(equipe_enregistree, sender=Team, dispatch_uid="radio_equipe_defaut")
    try:
        ancienne = Team.objects.create(name="Pompiers volontaires", institution=adrasec)
        vieille = Team.objects.create(name="Vieille")
        legacy = CanalMeshCore.objects.create(nom="Équipe Vieille", equipe=vieille, cle_partagee_hex=CLE_ADRASEC)
    finally:
        post_save.connect(equipe_enregistree, sender=Team, dispatch_uid="radio_equipe_defaut")
    migration = importlib.import_module("core.migrations.0390_canal_radio_equipe")
    migration.donner_indicatifs_et_canaux(django_apps, None)
    ancienne = Team.objects.get(pk=ancienne.pk)
    assert ancienne.indicatif == "POMPIE"
    assert ancienne.canal_meshtastic.nom == "AC-POMPIE" and ancienne.canal_meshcore.nom == "AC-POMPIE"
    legacy.refresh_from_db()
    assert legacy.nom == "Équipe Vieille" and legacy.sur_passerelle and legacy.personnalise
