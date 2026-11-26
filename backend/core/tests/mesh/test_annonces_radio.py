"""Signalements du public sur la carte et par radio, marqueurs d'une manifestation et d'un canal
d'équipe émis par le central, interventions annoncées par radio et « @PC MAJ » (26/11/2026)."""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from core import annonces_radio as ar
from core import marqueurs_terrain as mt
from core.models import (
    Besoin, CanalMeshCore, CanalMeshtastic, Crisis, DirectionMessageMesh, Dossier, Information, InformationType,
    Institution, InstitutionType, Manifestation, MarqueurTerrain, MessageCanalMeshCore, MessageCanalMeshtastic,
    Notification,
)
from core.tests.mesh.test_marqueurs_terrain import _client, scene  # noqa: F401 (fixture)

SORTANT = DirectionMessageMesh.SORTANT


@pytest.fixture(autouse=True)
def _cache_vide():
    cache.clear()
    yield
    cache.clear()


def _signalement(type_, crise=None, commune_code=None, environment="PROD", titre="Route de Bègles", lieu=(-0.57, 44.85)):
    itype, _ = InformationType.objects.get_or_create(type=type_)
    return Information.objects.create(
        title=titre, information_type=itype, environment=environment, crisis=crise, commune_code=commune_code,
        first_name_information="Paul", last_name_information="Durand", email_information="paul@test.fr",
        phone_information="0611223344", location=Point(*lieu, srid=4326),
    )


def _sortants(canal):
    modele = MessageCanalMeshtastic if isinstance(canal, CanalMeshtastic) else MessageCanalMeshCore
    return list(modele.objects.filter(canal=canal, direction=SORTANT).order_by("date_creation", "pk")
                .values_list("contenu", flat=True))


@pytest.mark.django_db
class TestSignalements:
    def test_route_barree_devient_un_marqueur_emis_par_radio(self, scene, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            info = _signalement("Route barrée", crise=scene["crise"])
        m = MarqueurTerrain.objects.get()
        assert (m.genre, m.source, m.signalement_id, m.crise) == ("ROUTE_COUPEE", "SIGNALEMENT", info.id, scene["crise"])
        assert m.note == "Signalement · Route barrée · Route de Bègles"
        # Émis sur le canal de crise des deux protocoles, sans rien sur la personne.
        for canal in (scene["mt"], scene["mc"]):
            (texte,) = _sortants(canal)
            # Par radio, l'essentiel seulement : le type, pas le titre (le détail reste en IP).
            assert texte == "S:⛔:0:44.85000,-0.57000:Route barrée"
            assert not any(x in texte for x in ("Paul", "Durand", "0611", "paul@"))
        assert mt.nom_auteur(m) == "Signalement du public"
        assert Notification.objects.filter(utilisateur=scene["regulateur"]).exists()

    def test_arbre_et_danger_et_information(self, scene, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            _signalement("Arbre sur la chaussée", crise=scene["crise"], titre="Arbre sur la chaussée", lieu=(-0.50, 44.80))
            _signalement("Danger imminent", crise=scene["crise"], titre="Fil électrique", lieu=(-0.51, 44.81))
            _signalement("Information utile", crise=scene["crise"], titre="Pharmacie ouverte", lieu=(-0.52, 44.82))
        par_genre = {m.genre: m for m in MarqueurTerrain.objects.all()}
        assert par_genre["ROUTE_COUPEE"].note == "Signalement · Arbre sur la chaussée"
        assert par_genre["DANGER"].emoji == "⚠️"
        assert par_genre["INFO"].emoji == "ℹ️" and mt.libelle(par_genre["INFO"]) == "Information"
        # Une information ne dérange pas la régulation.
        assert not [n for n in Notification.objects.all() if "Information" in n.titre]

    def test_crise_trouvee_par_la_commune(self, scene, django_capture_on_commit_callbacks):
        scene["crise"].zone_communes = ["33039"]
        scene["crise"].save()
        with django_capture_on_commit_callbacks(execute=True):
            _signalement("Route barrée", commune_code="33039")
            _signalement("Route barrée", commune_code="75056", lieu=(2.35, 48.85))
            _signalement("Route barrée", commune_code="33039", environment="DEMO", lieu=(-0.40, 44.70))
        assert [m.crise for m in MarqueurTerrain.objects.all()] == [scene["crise"]]

    def test_crise_close_rien(self, scene, django_capture_on_commit_callbacks):
        scene["crise"].end_date = timezone.now()
        scene["crise"].save()
        with django_capture_on_commit_callbacks(execute=True):
            _signalement("Route barrée", crise=scene["crise"])
        assert not MarqueurTerrain.objects.exists()

    def test_signalement_desactive_retire_le_marqueur(self, scene, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            info = _signalement("Danger imminent", crise=scene["crise"])
        with django_capture_on_commit_callbacks(execute=True):
            info.actif = False
            info.save(update_fields=["actif"])
        assert MarqueurTerrain.objects.get().actif is False

    def test_visible_sur_la_carte_de_l_application(self, scene, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            _signalement("Route barrée", crise=scene["crise"])
        data = _client(scene["lea"]).get(reverse("marqueurs_terrain")).data
        assert [(d["source"], d["genre"]) for d in data] == [("SIGNALEMENT", "ROUTE_COUPEE")]
        assert data[0]["signalement"]

    def test_commande_pour_les_anciens(self, scene):
        _signalement("Route barrée", crise=scene["crise"])        # hors on_commit : pas posé
        assert not MarqueurTerrain.objects.exists()
        call_command("marqueurs_des_signalements")
        assert not MarqueurTerrain.objects.exists()
        call_command("marqueurs_des_signalements", "--poser")
        call_command("marqueurs_des_signalements", "--poser")
        assert MarqueurTerrain.objects.count() == 1


@pytest.mark.django_db
class TestDiffusion:
    def test_marqueur_de_manifestation_sur_le_canal_de_l_organisateur(self, scene):
        itype, _ = InstitutionType.objects.get_or_create(code="ASSO", defaults={"libelle": "Association"})
        asso = Institution.objects.create(nom="Secouristes d'essai", type=itype)
        canal = CanalMeshCore.objects.create(nom="#secouristes", institution=asso)
        maintenant = timezone.now()
        manif = Manifestation.objects.create(institution=asso, titre="Course", statut="PUBLIEE",
                                             debut=maintenant, fin=maintenant + datetime.timedelta(hours=3))
        mt.enregistrer("PROD", "🆘", 44.9, -0.5, "malaise", manifestation=manif, source="APPLICATION",
                       diffuser_radio=True, prevenir=False)
        (texte,) = _sortants(canal)
        assert mt.lire(texte)["genre"] == "SECOURS"

    def test_marqueur_entendu_sur_un_canal_d_equipe_rediffuse_sur_la_crise(self, scene):
        canal = CanalMeshCore.objects.create(nom="AC-ALPHA", equipe=scene["alpha"])
        r = scene["pont"].post(reverse("messagecanalmeshcore-list"), {
            "canal": str(canal.id), "direction": "ENTRANT", "contenu": "Léa: S:🔥:0:44.86000,-0.56000"}, format="json")
        assert r.status_code == 201, r.data
        for c in (scene["mt"], scene["mc"]):
            assert [mt.lire(t)["genre"] for t in _sortants(c)] == ["FEU"]

    def test_sur_le_canal_de_crise_pas_de_double_emission(self, scene):
        r = scene["pont"].post(reverse("messagecanalmeshcore-list"), {
            "canal": str(scene["mc"].id), "direction": "ENTRANT", "contenu": "Léa: S:🔥:0:44.86000,-0.56000"}, format="json")
        assert r.status_code == 201, r.data
        assert _sortants(scene["mc"]) == []                 # pas renvoyé sur le canal d'où il vient
        assert len(_sortants(scene["mt"])) == 1             # un seul relais vers l'autre protocole


class TestNoteRadio:
    def test_route_garde_son_sens_et_quelques_mots(self):
        m = MarqueurTerrain(emoji="⛔", note="1 sens · arbre tombé en travers de la chaussée après la tempête",
                            source="APPLICATION", location=Point(-0.57, 44.85))
        assert mt.note_radio(m) == "1 sens · arbre tombé en travers de la…"
        assert len(mt.note_radio(m)) <= len("1 sens · ") + mt.NOTE_RADIO_MAX

    def test_signalement_son_type_seul(self):
        m = MarqueurTerrain(emoji="⚠️", note="Signalement · Danger imminent · Fil électrique au sol",
                            source="SIGNALEMENT", location=Point(-0.57, 44.85))
        assert mt.texte_radio(m) == "S:⚠️:0:44.85000,-0.57000:Danger imminent"


class TestFormatAnnonce:
    def test_ecrire_et_relire(self):
        texte = ar.ecrire("D-0123", "Pompage", "Talence", 44.8, -0.59)
        assert texte == "📋 D-0123 · Pompage · Talence · 44.80000,-0.59000"
        assert ar.lire("Passerelle: " + texte) == {"numero": "D-0123", "nature": "Pompage", "commune": "Talence",
                                                  "latitude": 44.8, "longitude": -0.59}

    def test_sans_position_ni_commune(self):
        texte = ar.ecrire("D-9", "Pompage")
        assert texte == "📋 D-9 · Pompage · -"
        assert ar.lire(texte)["commune"] == "" and ar.lire(texte)["latitude"] is None

    def test_le_separateur_saisi_ne_casse_pas_la_ligne(self):
        lu = ar.lire(ar.ecrire("D-1", "Eau · potable", "Saint-Jean"))
        assert (lu["nature"], lu["commune"]) == ("Eau - potable", "Saint-Jean")

    def test_court_sur_la_radio(self):
        assert len(ar.ecrire("D-00001", "x" * 200, "y" * 200, 44.8, -0.59).encode()) <= 150

    def test_autre_chose_n_en_est_pas(self):
        assert ar.lire("bonjour") is None
        assert ar.lire("S:🔥:0:44.8,-0.5") is None

    def test_demande_maj(self):
        assert ar.est_demande_maj("@PC MAJ") and ar.est_demande_maj("Léa: @pc maj")
        assert not ar.est_demande_maj("@PC majeur problème") and not ar.est_demande_maj("MAJ")


@pytest.fixture
def equipe_radio(scene):
    alpha = scene["alpha"]
    mc = CanalMeshCore.objects.create(nom="AC-ALPHA", equipe=alpha, environment="PROD")
    mtc = CanalMeshtastic.objects.create(nom="AC-ALPHA", equipe=alpha, psk_hex="11" * 16, environment="PROD")
    info = _signalement("Danger imminent", crise=scene["crise"], titre="Mur fissuré chez M. Durand")
    besoin, _ = Besoin.objects.get_or_create(nom="Pompage")
    dossier = Dossier.objects.create(numero="D-0042", crise=scene["crise"], titre="Cave de M. Durand", description="",
                                     besoin=besoin, information=info, environment="PROD")
    return {"mc": mc, "mt": mtc, "dossier": dossier, "alpha": alpha}


@pytest.mark.django_db
class TestAnnonces:
    def test_dossier_confie_annonce_sur_le_canal_de_l_equipe(self, scene, equipe_radio, django_capture_on_commit_callbacks):
        from core.views import populate_dossier_participants_and_notify

        with django_capture_on_commit_callbacks(execute=True):
            populate_dossier_participants_and_notify(equipe_radio["dossier"], equipe=equipe_radio["alpha"])
        for canal in (equipe_radio["mc"], equipe_radio["mt"]):
            (texte,) = _sortants(canal)
            lu = ar.lire(texte)
            # La grande famille, pas le besoin (« Pompage ») ni la compétence.
            assert (lu["numero"], lu["nature"], lu["latitude"]) == ("D-0042", "Danger imminent", 44.85)
            assert "Durand" not in texte and "0611" not in texte

    def test_dossier_clos_pas_annonce(self, scene, equipe_radio):
        d = equipe_radio["dossier"]
        d.statut = "CLOTURE"
        assert ar.annoncer(d, equipe_radio["alpha"]) == 0

    def test_equipe_sans_canal(self, scene, equipe_radio):
        from core.models import Team
        assert ar.annoncer(equipe_radio["dossier"], Team.objects.create(name="Sans radio")) == 0

    def _maj(self, scene, canal, url="messagecanalmeshcore-list", qui="Léa"):
        r = scene["pont"].post(reverse(url), {"canal": str(canal.id), "direction": "ENTRANT",
                                              "contenu": f"{qui}: @PC MAJ"}, format="json")
        assert r.status_code == 201, r.data

    def test_pc_maj_rend_dossiers_et_marqueurs(self, scene, equipe_radio):
        d = equipe_radio["dossier"]
        d.equipe = equipe_radio["alpha"]
        d.save()
        mt.enregistrer("PROD", "⛔", 44.85, -0.57, "2 sens", crise=scene["crise"], source="SITE", prevenir=False)
        mt.enregistrer("PROD", "🆘", 44.86, -0.57, "", crise=scene["crise"], source="SITE", prevenir=False)
        self._maj(scene, equipe_radio["mc"])
        textes = _sortants(equipe_radio["mc"])
        assert ar.lire(textes[0])["numero"] == "D-0042"
        assert [mt.lire(t)["genre"] for t in textes[1:]] == ["SECOURS", "ROUTE_COUPEE_2S"]
        # Une fois par tranche de 10 minutes et par canal (un autre émetteur : pas un doublon).
        self._maj(scene, equipe_radio["mc"], qui="Max")
        assert len(_sortants(equipe_radio["mc"])) == 3

    def test_pc_maj_sans_rien(self, scene, equipe_radio):
        self._maj(scene, equipe_radio["mc"])
        textes = _sortants(equipe_radio["mc"])
        assert textes == ["PC: rien en cours pour ce canal."] and ar.lire(textes[0]) is None
