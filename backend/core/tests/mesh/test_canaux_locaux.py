"""Règle des passerelles locales Meshtastic, fixée par Sylvain le 14/11/2026.

1. une passerelle locale est isolée par défaut : elle ne réémet que sa crise et sa commune, et
   ce qu'elle entend n'est réémis par aucune autre passerelle ;
2. Fr_Balise et Fr_EMCOM d'office ;
3. un canal par crise et un par commune, annoncés sur Fr_EMCOM en local seulement ;
4. clé publique par défaut, avec un avertissement ;
5. mutualisation : le canal de crise est celui de la CRISE, partagé par les communes impliquées,
   et chaque passerelle locale l'émet de son côté.
"""
import pytest
from django.contrib.gis.geos import Point
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.canaux_locaux import (
    PSK_PUBLIQUE, annoncer, canal_commune, canal_crise, est_isolee, nom_canal_commune,
    nom_canal_crise, plan_canaux,
)
from core.models import (
    CanalMeshtastic, CompagnonMeshtastic, ContactInstitution, Crisis, DirectionMessageMesh,
    ImplicationInstitution, Institution, InstitutionType, MeshtasticConnexionType,
    MessageCanalMeshtastic, StatutImplication, StatutMessageMesh, Team, UserRole,
)
from core.relais_navigateur import ouvrir


def _mairie(nom):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom=nom, type=itype)


@pytest.fixture
def moissac(db):
    return _mairie("Mairie de Moissac")


@pytest.fixture
def voisine(db):
    return _mairie("Mairie de Castelsarrasin")


@pytest.fixture
def lointaine(db):
    return _mairie("Mairie de Brest")


@pytest.fixture
def crue(moissac, voisine):
    """Une crise où Moissac et sa voisine sont impliquées : c'est le cas de la mutualisation."""
    crise = Crisis.objects.create(name="Inondation Tarn", location=Point(1.09, 44.1), environment="PROD")
    for inst in (moissac, voisine):
        ImplicationInstitution.objects.create(crise=crise, institution=inst, actif=True,
                                              statut=StatutImplication.VALIDEE, environment="PROD")
    return crise


def _passerelle(institution, num, **kw):
    return CompagnonMeshtastic.objects.create(
        institution=institution, nom=f"Passerelle {institution.nom}", node_num=num,
        connexion_type=kw.pop("connexion_type", MeshtasticConnexionType.NAVIGATEUR),
        environment="PROD", **kw)


@pytest.fixture
def gw_moissac(moissac):
    return _passerelle(moissac, 0x1001)


@pytest.fixture
def gw_voisine(voisine):
    return _passerelle(voisine, 0x1002)


@pytest.fixture
def gw_lointaine(lointaine):
    return _passerelle(lointaine, 0x1003)


@pytest.fixture
def emcom(db):
    return CanalMeshtastic.objects.create(nom="Fr_EMCOM", psk_hex="aa" * 16, environment="PROD")


@pytest.fixture
def balise(db):
    return CanalMeshtastic.objects.create(nom="Fr_Balise", psk_hex="bb" * 16, environment="PROD")


def _sortant(canal, contenu, compagnon=None, age_minutes=0):
    m = MessageCanalMeshtastic.objects.create(
        canal=canal, compagnon=compagnon, direction=DirectionMessageMesh.SORTANT, contenu=contenu,
        statut=StatutMessageMesh.EN_ATTENTE, environment="PROD")
    if age_minutes:
        MessageCanalMeshtastic.objects.filter(pk=m.pk).update(
            date_creation=timezone.now() - timezone.timedelta(minutes=age_minutes))
    return m


def _client_pont():
    from django.contrib.auth import get_user_model
    pont = get_user_model().objects.create_user(
        username="pont-canaux@test.fr", email="pont-canaux@test.fr", password="x",
        type=UserRole.SIMPLE_USER)
    pont.compte_service_pont = True
    pont.save()
    c = APIClient()
    c.force_authenticate(user=pont)
    return c


def _file(client, compagnon, canal=None):
    params = {"compagnon": str(compagnon.id)}
    if canal is not None:
        params["canal"] = str(canal.id)
    reponse = client.get("/api/messages-canal-meshtastic/a-envoyer/", params)
    assert reponse.status_code == status.HTTP_200_OK, reponse.data
    return [m["contenu"].split(" : ", 1)[-1] for m in reponse.json()]


class TestIsoleeParDefaut:
    def test_une_passerelle_navigateur_est_isolee(self, gw_moissac):
        assert est_isolee(gw_moissac) is True

    def test_une_passerelle_serie_creee_apres_la_regle_aussi(self, moissac):
        assert est_isolee(_passerelle(moissac, 0x2001, connexion_type=MeshtasticConnexionType.SERIE))

    def test_une_passerelle_mqtt_n_est_pas_concernee(self, moissac):
        assert not est_isolee(_passerelle(moissac, 0x2002, connexion_type=MeshtasticConnexionType.MQTT))

    def test_le_reglage_rend_le_comportement_de_reseau(self, gw_moissac):
        gw_moissac.relais_reseau = True
        assert est_isolee(gw_moissac) is False


class TestNomsCourts:
    def test_le_nom_de_la_commune_perd_mairie_de(self, moissac):
        assert nom_canal_commune(moissac) == "Moissac"

    def test_le_nom_d_une_crise_tient_dans_11_octets(self, crue):
        nom = nom_canal_crise(crue)
        assert nom.startswith("Crise")
        assert len(nom.encode()) <= 11

    def test_deux_crises_ne_portent_pas_le_meme_nom_de_canal(self, crue):
        """Même clé publique + même nom = même canal radio : deux crises se mélangeraient."""
        premier = nom_canal_crise(crue)
        assert nom_canal_crise(crue, deja_pris={premier}) != premier


class TestMutualisation:
    def test_les_communes_d_une_meme_crise_partagent_son_canal(self, crue, moissac, voisine):
        canal_a, cree_a = canal_crise(crue, "PROD")
        canal_b, cree_b = canal_crise(crue, "PROD")

        assert canal_a == canal_b
        assert (cree_a, cree_b) == (True, False)
        assert canal_a.psk_hex == PSK_PUBLIQUE

    def test_le_canal_de_commune_est_cree_une_fois(self, moissac):
        premier, _ = canal_commune(moissac, "PROD")
        second, cree = canal_commune(moissac, "PROD")
        assert premier == second and cree is False

    def test_chaque_passerelle_locale_emet_le_message_de_crise(self, crue, gw_moissac, gw_voisine):
        """Avec un statut unique, la première passerelle privait l'autre de l'émettre."""
        canal, _ = canal_crise(crue, "PROD")
        _sortant(canal, "Evacuation quai nord")
        pont = _client_pont()

        assert _file(pont, gw_moissac) == ["Evacuation quai nord"]
        assert _file(pont, gw_voisine) == ["Evacuation quai nord"]

    def test_mais_une_seule_fois_chacune(self, crue, gw_moissac):
        canal, _ = canal_crise(crue, "PROD")
        _sortant(canal, "Evacuation quai nord")
        pont = _client_pont()

        assert len(_file(pont, gw_moissac)) == 1
        assert _file(pont, gw_moissac) == []

    def test_le_message_passe_envoye_au_premier_emetteur(self, crue, gw_moissac):
        canal, _ = canal_crise(crue, "PROD")
        message = _sortant(canal, "x")
        _file(_client_pont(), gw_moissac)

        message.refresh_from_db()
        assert message.statut == StatutMessageMesh.ENVOYE


class TestNeReemetQueSaCriseEtSaCommune:
    def test_le_canal_de_sa_commune_passe(self, moissac, gw_moissac):
        canal, _ = canal_commune(moissac, "PROD")
        _sortant(canal, "Point d'eau mairie")
        assert _file(_client_pont(), gw_moissac) == ["Point d'eau mairie"]

    def test_le_canal_d_une_de_ses_equipes_passe(self, moissac, gw_moissac):
        equipe = Team.objects.create(name="CCFF", institution=moissac)
        canal = CanalMeshtastic.objects.create(nom="EquipeCCFF", equipe=equipe,
                                               institution=moissac, environment="PROD")
        _sortant(canal, "Rassemblement 14h")
        assert _file(_client_pont(), gw_moissac) == ["Rassemblement 14h"]

    def test_la_commune_d_une_autre_crise_ne_passe_pas(self, lointaine, gw_moissac):
        canal, _ = canal_commune(lointaine, "PROD")
        _sortant(canal, "Brest : marée")
        assert _file(_client_pont(), gw_moissac) == []

    def test_une_diffusion_du_reseau_ne_passe_pas(self, emcom, gw_moissac):
        """Exemple : l'alerte sismique diffusée sur Fr_EMCOM sans passerelle désignée."""
        _sortant(emcom, "Seisme M4.1 Pyrenees")
        assert _file(_client_pont(), gw_moissac) == []

    def test_un_message_trop_ancien_n_est_pas_rattrape(self, moissac, gw_moissac):
        """Se brancher ne doit pas vider d'un coup l'historique sur le réseau."""
        canal, _ = canal_commune(moissac, "PROD")
        _sortant(canal, "vieux", age_minutes=60)
        assert _file(_client_pont(), gw_moissac) == []

    def test_ouverte_au_reseau_elle_retrouve_l_ancien_comportement(self, lointaine, gw_moissac):
        gw_moissac.relais_reseau = True
        gw_moissac.save()
        canal, _ = canal_commune(lointaine, "PROD")
        _sortant(canal, "Brest : marée")
        assert _file(_client_pont(), gw_moissac, canal) == ["Brest : marée"]

    def test_une_passerelle_de_reseau_n_est_pas_touchee(self, lointaine, moissac):
        mqtt = _passerelle(moissac, 0x3001, connexion_type=MeshtasticConnexionType.MQTT)
        canal, _ = canal_commune(lointaine, "PROD")
        _sortant(canal, "Brest : marée")
        assert _file(_client_pont(), mqtt, canal) == ["Brest : marée"]


class TestRienNeRemonteVersLesAutresPasserelles:
    def test_ce_qu_entend_une_passerelle_n_est_mis_dans_aucune_file(self, crue, gw_moissac,
                                                                    gw_voisine):
        """Enregistré dans Assista-Crise, réémis par personne."""
        canal, _ = canal_crise(crue, "PROD")
        MessageCanalMeshtastic.objects.create(
            canal=canal, direction=DirectionMessageMesh.ENTRANT, contenu="Entendu à Moissac",
            contact_node_num=0xBEEF, environment="PROD")

        assert _file(_client_pont(), gw_voisine) == []
        assert not MessageCanalMeshtastic.objects.filter(
            direction=DirectionMessageMesh.SORTANT, contenu__contains="Entendu").exists()


class TestPlanDeCanaux:
    def test_les_communautaires_puis_la_crise_puis_la_commune(self, crue, gw_moissac, emcom,
                                                              balise):
        plan = plan_canaux(gw_moissac, "PROD")

        assert [e["role"] for e in plan] == ["communautaire", "communautaire", "crise", "commune"]
        assert [e["nom"] for e in plan[:2]] == ["Fr_Balise", "Fr_EMCOM"]
        assert all(e["disponible"] for e in plan)

    def test_un_communautaire_non_declare_n_est_pas_pousse(self, gw_moissac):
        """Sa clé n'est pas inventée : sans déclaration, on ne peut pas l'écrire sur la radio."""
        plan = plan_canaux(gw_moissac, "PROD")
        balise = next(e for e in plan if e["nom"] == "Fr_Balise")
        assert balise["disponible"] is False and balise["psk_hex"] == ""

    def test_les_canaux_de_crise_et_de_commune_sont_publics(self, crue, gw_moissac):
        plan = plan_canaux(gw_moissac, "PROD")
        locaux = [e for e in plan if e["role"] in ("crise", "commune")]
        assert locaux and all(e["public"] and e["psk_hex"] == PSK_PUBLIQUE for e in locaux)

    def test_l_api_exige_de_relayer_la_radio(self, gw_moissac, moissac, create_user):
        membre = create_user(username="m-canaux@test.fr", email="m-canaux@test.fr",
                             type=UserRole.LOCAL_AUTHORITY)
        ContactInstitution.objects.create(institution=moissac, utilisateur=membre, actif=True)
        client = APIClient()
        client.force_authenticate(user=membre)

        refus = client.get("/api/relais-serie/plan-canaux/", {"compagnon": str(gw_moissac.id)})
        assert refus.status_code == status.HTTP_403_FORBIDDEN

        ouvrir(membre, gw_moissac, "PROD")
        reponse = client.get("/api/relais-serie/plan-canaux/", {"compagnon": str(gw_moissac.id)})
        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["emplacements"] == 8
        assert "non chiffr" in reponse.data["avertissement"]


class TestAnnonceSurEmcom:
    def test_l_annonce_cible_la_seule_passerelle_locale(self, crue, gw_moissac, gw_voisine, emcom):
        message, raison = annoncer(gw_moissac, None, "PROD")

        assert raison is None
        assert message.compagnon == gw_moissac
        assert "crise Crise" in message.contenu and "commune Moissac" in message.contenu
        assert "non chiffre" in message.contenu
        pont = _client_pont()
        assert _file(pont, gw_voisine, emcom) == []
        assert len(_file(pont, gw_moissac, emcom)) == 1

    def test_pas_plus_d_une_annonce_par_demi_heure(self, crue, gw_moissac, emcom):
        annoncer(gw_moissac, None, "PROD")
        message, raison = annoncer(gw_moissac, None, "PROD")
        assert message is None and "30 minutes" in raison

    def test_sans_fr_emcom_declare_rien_n_est_annonce(self, crue, gw_moissac):
        message, raison = annoncer(gw_moissac, None, "PROD")
        assert message is None and "Fr_EMCOM" in raison


class TestAvertissementNonChiffre:
    def test_l_api_dit_si_la_cle_est_publique_sans_la_donner(self, moissac, create_user):
        admin = create_user(username="admin-canaux@test.fr", email="admin-canaux@test.fr",
                            type=UserRole.ADMINISTRATOR)
        public, _ = canal_commune(moissac, "PROD")
        prive = CanalMeshtastic.objects.create(nom="Secret", psk_hex="cc" * 16, environment="PROD")
        client = APIClient()
        client.force_authenticate(user=admin)

        donnees = {c["id"]: c for c in client.get("/api/canaux-meshtastic/").json()}

        assert donnees[str(public.id)]["cle_publique"] is True
        assert donnees[str(prive.id)]["cle_publique"] is False
        assert "psk_hex" not in donnees[str(public.id)]
