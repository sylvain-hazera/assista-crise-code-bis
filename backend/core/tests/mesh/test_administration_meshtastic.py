"""Administration à distance des nœuds Meshtastic (TacheAdminMeshtastic + le pont).

Ce qui est verrouillé ici tient à ce qu'on a lu dans le firmware (`AdminModule.cpp`, le
06/11/2026) et non dans la documentation :

- un message d'administration venant d'un autre nœud n'est accepté que s'il est chiffré par clé
  publique ET que la clé de l'émetteur est dans `security.admin_key` de la cible ; d'où le refus
  d'emblée des companions MQTT, qui n'ont pas d'appareil pour chiffrer ;
- les écritures exigent une clé de session, les lectures non ;
- `tx_power = 0` ne veut PAS dire 0 dBm : le firmware applique alors le maximum de la région,
  c'est une puissance inconnue — et la confondre avec 0 dBm faussait toute l'analyse d'asymétrie.
"""
import datetime

import pytest
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core.analyse_liaisons import analyser
from core.models import (
    CompagnonMeshtastic, ConfigurationNoeudMeshtastic, ContactMeshtastic, Institution,
    InstitutionType, LiaisonMeshtastic, MeshtasticConnexionType, SourceLiaisonMeshtastic,
    StatutTacheAdminMeshtastic, TacheAdminMeshtastic, TENTATIVES_MAX_TACHE_ADMIN,
    DELAI_RECLAMATION_TACHE_ADMIN_S,
)

URL_LISTE = "/api/taches-admin-meshtastic/"


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie Administration", type=itype)


@pytest.fixture
def passerelle(db, institution):
    """Appareil réel relié au pont : le seul type de companion qui puisse administrer."""
    return CompagnonMeshtastic.objects.create(
        nom="Passerelle série", node_num=0x1000, institution=institution,
        connexion_type=MeshtasticConnexionType.SERIE, serie_device="/dev/ttyACM0",
    )


@pytest.fixture
def companion_mqtt(db, institution):
    return CompagnonMeshtastic.objects.create(
        nom="Gaulix", node_num=0x2000, institution=institution,
        connexion_type=MeshtasticConnexionType.MQTT,
    )


def _client(create_user, type_role, institution, email):
    user = create_user(username=email, email=email, type=type_role, institution=institution)
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def institutionnel(create_user, institution):
    return _client(create_user, "SECOURS", institution, "secours-admin-mesh@x.fr")


@pytest.fixture
def administrateur(create_user, institution):
    return _client(create_user, "ADMIN", institution, "admin-admin-mesh@x.fr")


@pytest.fixture
def pont(create_user, institution):
    """Compte de service du pont : authentifié, pas institutionnel."""
    return _client(create_user, "UTIL_SIMPLE", institution, "pont-admin-mesh@x.fr")


@pytest.mark.django_db
class TestCreationDesTaches:

    def test_un_companion_mqtt_est_refuse_avec_la_raison(self, institutionnel, companion_mqtt):
        """Refus porté par l'API, pas découvert par le pont 30 s plus tard : un companion MQTT
        n'a pas d'appareil, et c'est le firmware de l'appareil qui chiffre le message."""
        reponse = institutionnel.post(URL_LISTE, {
            "compagnon": str(companion_mqtt.id), "type_tache": "LIRE_CONFIG_LORA",
        }, format="json")
        assert reponse.status_code == 400
        assert "firmware" in str(reponse.data).lower()

    def test_une_lecture_est_ouverte_aux_institutionnels(self, institutionnel, passerelle):
        """Relever une puissance d'émission n'est pas un acte matériel."""
        reponse = institutionnel.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "LIRE_CONFIG_LORA",
        }, format="json")
        assert reponse.status_code == 201
        tache = TacheAdminMeshtastic.objects.get()
        assert tache.statut == StatutTacheAdminMeshtastic.EN_ATTENTE
        assert tache.node_num_cible is None       # la passerelle elle-même par défaut
        assert tache.demande_par is not None      # imputable

    def test_une_ecriture_est_acceptee_de_l_institution_qui_a_deploye_la_passerelle(
            self, institutionnel, passerelle):
        """**Ce test disait l'inverse jusqu'au 10/11/2026** : toute écriture exigeait alors le
        rôle ADMIN réel. Changé sur demande explicite -- une passerelle est de la responsabilité
        de l'institution qui l'a déployée, c'est elle qui ira la rechercher si un réglage la
        rend muette, et faire dépendre son réglage d'un administrateur de plateforme n'ajoutait
        aucune sécurité : il ne sait pas où elle est.

        Ce qui n'a pas changé : l'écriture reste refusée à qui n'est PAS de cette institution
        (voir test_acces_radio.py), et elle reste refusée en zone DEMO."""
        reponse = institutionnel.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": 20},
        }, format="json")
        assert reponse.status_code == 201, reponse.data
        assert TacheAdminMeshtastic.objects.get().est_ecriture

    def test_une_ecriture_est_refusee_a_un_institutionnel_sans_lien_avec_la_passerelle(
            self, create_user, passerelle):
        """Le rôle institutionnel ne suffit pas : il faut répondre de CE matériel. Une mairie
        voisine n'a rien à régler sur la passerelle d'une autre."""
        ailleurs, _ = InstitutionType.objects.get_or_create(
            code="MAIRIE", defaults={"libelle": "Mairie"},
        )
        autre = Institution.objects.create(nom="Mairie sans radio", type=ailleurs)
        client = _client(create_user, "SECOURS", autre, "secours-sans-radio@x.fr")

        reponse = client.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": 20},
        }, format="json")
        assert reponse.status_code == 403
        assert TacheAdminMeshtastic.objects.count() == 0

    def test_une_ecriture_est_acceptee_d_un_administrateur(self, administrateur, passerelle):
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": 20},
        }, format="json")
        assert reponse.status_code == 201
        assert TacheAdminMeshtastic.objects.get().est_ecriture

    def test_une_ecriture_est_refusee_depuis_la_zone_demo(self, administrateur, passerelle):
        """Aucun pont n'exécuterait une tâche DEMO, et un relais réel n'a rien à voir avec une
        démonstration."""
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": 20},
        }, format="json", HTTP_X_ENVIRONMENT="DEMO")
        assert reponse.status_code == 403
        assert "démonstration" in str(reponse.data)

    def test_une_lecture_reste_possible_en_demo(self, create_user, institution, passerelle):
        """Une lecture n'est pas un acte matériel : elle reste ouverte en zone de démonstration
        à qui y a un rôle institutionnel prêté (`demo_role`), contrairement à une écriture.

        À noter pour qui lira ce test : le rôle PROD ne suffit pas en zone DEMO, c'est
        `demo_role` qui compte là-bas (get_effective_role)."""
        passerelle.environment = "DEMO"
        passerelle.save(update_fields=["environment"])
        user = create_user(username="demo-mesh@x.fr", email="demo-mesh@x.fr",
                           type="UTIL_SIMPLE", institution=institution, demo_role="SECOURS")
        client = APIClient()
        client.force_authenticate(user=user)
        reponse = client.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "LIRE_METADATA",
        }, format="json", HTTP_X_ENVIRONMENT="DEMO")
        assert reponse.status_code == 201

    @pytest.mark.parametrize("puissance", [0, 28, 40, -5])
    def test_une_puissance_hors_bornes_est_refusee(self, administrateur, passerelle, puissance):
        """27 dBm est le plafond de la bande 869,4-869,65 MHz, et le firmware ne le vérifie pas
        dans AdminModule : c'est donc ici ou nulle part."""
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": puissance},
        }, format="json")
        assert reponse.status_code == 400

    def test_une_puissance_manquante_est_refusee(self, administrateur, passerelle):
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
        }, format="json")
        assert reponse.status_code == 400

    def test_ni_patch_ni_delete(self, administrateur, passerelle):
        """Laisser modifier `statut`/`reponse` permettrait de maquiller une opération faite sur
        un relais : le pont rapporte par une action dédiée."""
        tache = TacheAdminMeshtastic.objects.create(
            compagnon=passerelle, type_tache="LIRE_METADATA", environment="PROD",
        )
        detail = f"{URL_LISTE}{tache.id}/"
        assert administrateur.patch(detail, {"statut": "TERMINEE"}, format="json").status_code == 405
        assert administrateur.delete(detail).status_code == 405

    def test_un_anonyme_ne_voit_rien(self, passerelle):
        assert APIClient().get(URL_LISTE).status_code in (401, 403)


@pytest.mark.django_db
class TestPriseEtRapport:

    def _tache(self, passerelle, **kwargs):
        return TacheAdminMeshtastic.objects.create(
            compagnon=passerelle, type_tache=kwargs.pop("type_tache", "LIRE_CONFIG_LORA"),
            environment="PROD", **kwargs,
        )

    def test_la_prise_verrouille_et_compte_la_tentative(self, pont, passerelle):
        """Le compteur s'incrémente à la PRISE : un pont qui meurt en pleine opération ne doit
        pas pouvoir la reprendre indéfiniment."""
        tache = self._tache(passerelle)
        reponse = pont.post(f"{URL_LISTE}prendre/", {"compagnon": str(passerelle.id)}, format="json")
        assert reponse.status_code == 200
        assert len(reponse.data) == 1
        tache.refresh_from_db()
        assert tache.statut == StatutTacheAdminMeshtastic.EN_COURS
        assert tache.tentatives == 1
        assert tache.date_prise is not None

        # Deuxième appel immédiat : plus rien à prendre, la tâche est verrouillée.
        assert pont.post(f"{URL_LISTE}prendre/", {"compagnon": str(passerelle.id)}, format="json").data == []

    def test_la_prise_exige_un_compagnon(self, pont):
        assert pont.post(f"{URL_LISTE}prendre/", {}, format="json").status_code == 400

    def test_une_tache_abandonnee_en_cours_est_rendue_a_la_file(self, pont, passerelle):
        """Sinon un pont redémarré en pleine opération la laisserait bloquée pour toujours."""
        tache = self._tache(
            passerelle, statut=StatutTacheAdminMeshtastic.EN_COURS,
            date_prise=timezone.now() - datetime.timedelta(seconds=DELAI_RECLAMATION_TACHE_ADMIN_S + 60),
        )
        reponse = pont.post(f"{URL_LISTE}prendre/", {"compagnon": str(passerelle.id)}, format="json")
        assert [t["id"] for t in reponse.data] == [str(tache.id)]

    def test_une_tache_en_cours_recente_n_est_pas_volee(self, pont, passerelle):
        self._tache(
            passerelle, statut=StatutTacheAdminMeshtastic.EN_COURS, date_prise=timezone.now(),
        )
        assert pont.post(f"{URL_LISTE}prendre/", {"compagnon": str(passerelle.id)}, format="json").data == []

    def test_une_tache_reprise_sans_fin_finit_par_echouer(self, pont, passerelle):
        """Un pont qui meurt à chaque tentative n'appellera jamais `rapporter` : sans garde, la
        tâche serait reprise indéfiniment, une tentative de plus à chaque fois."""
        tache = self._tache(
            passerelle, statut=StatutTacheAdminMeshtastic.EN_COURS,
            tentatives=TENTATIVES_MAX_TACHE_ADMIN,
            date_prise=timezone.now() - datetime.timedelta(seconds=DELAI_RECLAMATION_TACHE_ADMIN_S + 60),
        )
        assert pont.post(f"{URL_LISTE}prendre/", {"compagnon": str(passerelle.id)}, format="json").data == []
        tache.refresh_from_db()
        assert tache.statut == StatutTacheAdminMeshtastic.ECHEC
        assert "ne termine pas" in tache.erreur

    def test_un_succes_enregistre_la_reponse_et_la_configuration(self, pont, passerelle):
        tache = self._tache(passerelle, node_num_cible=0x3000, tentatives=1,
                            statut=StatutTacheAdminMeshtastic.EN_COURS)
        reponse = pont.post(f"{URL_LISTE}{tache.id}/rapporter/", {
            "succes": True,
            "reponse": {"puissance_emission_dbm": 22, "region": "EU_868"},
            "configuration": {"puissance_emission_dbm": 22, "region": "EU_868",
                              "modem_preset": "LONG_FAST", "hop_limit": 3},
        }, format="json")
        assert reponse.status_code == 200
        tache.refresh_from_db()
        assert tache.statut == StatutTacheAdminMeshtastic.TERMINEE
        assert "EU_868" in tache.reponse
        assert tache.date_reponse is not None

        config = ConfigurationNoeudMeshtastic.objects.get(node_num=0x3000)
        assert config.puissance_emission_dbm == 22
        assert config.releve_par_id == passerelle.id

    def test_la_configuration_de_la_passerelle_elle_meme_est_rangee_sous_son_node_num(self, pont, passerelle):
        tache = self._tache(passerelle, statut=StatutTacheAdminMeshtastic.EN_COURS, tentatives=1)
        pont.post(f"{URL_LISTE}{tache.id}/rapporter/", {
            "succes": True, "reponse": {}, "configuration": {"puissance_emission_dbm": 14},
        }, format="json")
        assert ConfigurationNoeudMeshtastic.objects.get(node_num=passerelle.node_num).puissance_emission_dbm == 14

    def test_un_relevé_partiel_n_ecrase_pas_la_puissance_connue(self, pont, passerelle):
        """Une lecture de métadonnées ne connaît pas la puissance : écraser celle de la veille
        par un vide ferait régresser l'analyse d'asymétrie sans que personne s'en aperçoive."""
        ConfigurationNoeudMeshtastic.objects.create(
            node_num=0x3000, environment="PROD", puissance_emission_dbm=22,
            date_releve=timezone.now(),
        )
        tache = self._tache(passerelle, node_num_cible=0x3000, type_tache="LIRE_METADATA",
                            statut=StatutTacheAdminMeshtastic.EN_COURS, tentatives=1)
        pont.post(f"{URL_LISTE}{tache.id}/rapporter/", {
            "succes": True, "reponse": {"firmware_version": "2.7.4"},
            "configuration": {"firmware_version": "2.7.4", "hardware_model": "HELTEC_V3"},
        }, format="json")
        config = ConfigurationNoeudMeshtastic.objects.get(node_num=0x3000)
        assert config.firmware_version == "2.7.4"
        assert config.puissance_emission_dbm == 22       # conservée

    def test_un_firmware_bavard_ne_fait_pas_perdre_le_releve(self, pont, passerelle):
        """Un firmware annonce ce qu'il veut : une chaîne trop longue est tronquée, pas une
        erreur qui perdrait tout le relevé."""
        tache = self._tache(passerelle, node_num_cible=0x3000,
                            statut=StatutTacheAdminMeshtastic.EN_COURS, tentatives=1)
        reponse = pont.post(f"{URL_LISTE}{tache.id}/rapporter/", {
            "succes": True, "reponse": {},
            "configuration": {"firmware_version": "2" * 200, "puissance_emission_dbm": 20},
        }, format="json")
        assert reponse.status_code == 200
        config = ConfigurationNoeudMeshtastic.objects.get(node_num=0x3000)
        assert len(config.firmware_version) == 40
        assert config.puissance_emission_dbm == 20

    def test_un_releve_inexploitable_ne_perd_pas_le_resultat_de_l_operation(self, pont, passerelle):
        """La réponse de la tâche est enregistrée avant l'inventaire : échouer sur l'inventaire
        ferait réessayer le pont sur une tâche déjà terminée."""
        tache = self._tache(passerelle, node_num_cible=0x3000,
                            statut=StatutTacheAdminMeshtastic.EN_COURS, tentatives=1)
        reponse = pont.post(f"{URL_LISTE}{tache.id}/rapporter/", {
            "succes": True, "reponse": {"firmware_version": "2.7.4"},
            "configuration": {"puissance_emission_dbm": "beaucoup"},
        }, format="json")
        assert reponse.status_code == 200
        tache.refresh_from_db()
        assert tache.statut == StatutTacheAdminMeshtastic.TERMINEE
        assert "2.7.4" in tache.reponse

    def test_une_puissance_a_zero_est_bien_enregistree(self, pont, passerelle):
        """Elle dit qu'on a interrogé ce nœud. C'est l'analyse qui l'écarte, pas le stockage."""
        tache = self._tache(passerelle, node_num_cible=0x3000,
                            statut=StatutTacheAdminMeshtastic.EN_COURS, tentatives=1)
        pont.post(f"{URL_LISTE}{tache.id}/rapporter/", {
            "succes": True, "reponse": {}, "configuration": {"puissance_emission_dbm": 0},
        }, format="json")
        assert ConfigurationNoeudMeshtastic.objects.get(node_num=0x3000).puissance_emission_dbm == 0

    def test_un_echec_est_rendu_a_la_file_tant_qu_il_reste_des_tentatives(self, pont, passerelle):
        """Une opération traverse la radio : un relais qui dormait n'est pas une opération
        invalide."""
        tache = self._tache(passerelle, statut=StatutTacheAdminMeshtastic.EN_COURS, tentatives=1)
        pont.post(f"{URL_LISTE}{tache.id}/rapporter/",
                  {"succes": False, "erreur": "Aucune réponse du nœud après 90 s."}, format="json")
        tache.refresh_from_db()
        assert tache.statut == StatutTacheAdminMeshtastic.EN_ATTENTE
        assert "90 s" in tache.erreur

    def test_un_echec_devient_definitif_au_dernier_essai(self, pont, passerelle):
        tache = self._tache(passerelle, statut=StatutTacheAdminMeshtastic.EN_COURS,
                            tentatives=TENTATIVES_MAX_TACHE_ADMIN)
        pont.post(f"{URL_LISTE}{tache.id}/rapporter/",
                  {"succes": False, "erreur": "Clé publique non autorisée."}, format="json")
        tache.refresh_from_db()
        assert tache.statut == StatutTacheAdminMeshtastic.ECHEC
        # Le message reste visible : jamais d'échec silencieux.
        assert "autorisée" in tache.erreur
        assert tache.date_reponse is not None

    def test_un_echec_sans_message_reste_explicite(self, pont, passerelle):
        tache = self._tache(passerelle, statut=StatutTacheAdminMeshtastic.EN_COURS,
                            tentatives=TENTATIVES_MAX_TACHE_ADMIN)
        pont.post(f"{URL_LISTE}{tache.id}/rapporter/", {"succes": False}, format="json")
        tache.refresh_from_db()
        assert tache.erreur


@pytest.mark.django_db
class TestClePubliqueDeLAppareil:
    """C'est la clé de l'APPAREIL qu'un nœud compare, pas l'identité logicielle du companion :
    sans elle affichée, l'exploitant ne peut rien autoriser."""

    def _url(self, passerelle):
        return reverse('compagnonmeshtastic-rapporter-cle-publique', args=[passerelle.id])

    def test_le_pont_rapporte_la_cle(self, pont, passerelle):
        cle = "ab" * 32
        reponse = pont.post(self._url(passerelle), {"cle_publique_hex": cle}, format="json")
        assert reponse.status_code == 200
        passerelle.refresh_from_db()
        assert passerelle.cle_publique_appareil_hex == cle

    @pytest.mark.parametrize("cle", ["abcd", "zz" * 32, "AB" * 33])
    def test_une_cle_mal_formee_est_refusee(self, pont, passerelle, cle):
        """Elle est recopiée à la main dans une application mobile : on ne range pas n'importe
        quoi dans ce champ."""
        assert pont.post(self._url(passerelle), {"cle_publique_hex": cle},
                         format="json").status_code == 400

    def test_la_cle_est_exposee_par_la_serialisation(self, institutionnel, passerelle):
        passerelle.cle_publique_appareil_hex = "cd" * 32
        passerelle.save(update_fields=["cle_publique_appareil_hex"])
        reponse = institutionnel.get(f"/api/compagnons-meshtastic/{passerelle.id}/")
        assert reponse.data["cle_publique_appareil_hex"] == "cd" * 32


@pytest.mark.django_db
class TestCorrectionDePuissance:
    """Ce que la lecture de configuration débloque vraiment : sans puissance connue, l'écart de
    SNR mélange le bruit du nœud et sa puissance, et un nœud qui émet plus fort que ses voisins
    passe pour sourd."""

    @pytest.fixture
    def noeud(self, passerelle):
        def _creer(num, lat=44.84, lon=-0.57):
            return ContactMeshtastic.objects.create(
                compagnon=passerelle, node_num=num, long_name=f"Noeud {num}",
                location=Point(lon, lat, srid=4326),
                dernier_advert=timezone.now() - datetime.timedelta(hours=1),
            )
        return _creer

    @pytest.fixture
    def liaison(self, db):
        def _creer(emetteur, recepteur, snr, nombre=5):
            return LiaisonMeshtastic.objects.create(
                emetteur=emetteur, recepteur=recepteur, source=SourceLiaisonMeshtastic.RF,
                snr=snr, nombre=nombre, environment="PROD",
                dernier_vu=timezone.now() - datetime.timedelta(hours=1),
            )
        return _creer

    def _config(self, node_num, puissance):
        return ConfigurationNoeudMeshtastic.objects.create(
            node_num=node_num, environment="PROD", puissance_emission_dbm=puissance,
            date_releve=timezone.now(),
        )

    def _reseau_sourd(self, noeud, liaison):
        """Le nœud 10 paraît sourd : ses deux voisins l'entendent 12 dB mieux qu'il ne les
        entend."""
        noeud(10); noeud(20); noeud(30)
        liaison(10, 20, snr=10.0); liaison(20, 10, snr=-2.0)
        liaison(10, 30, snr=9.0); liaison(30, 10, snr=-3.0)

    def test_sans_puissance_connue_le_diagnostic_est_signale_comme_non_corrige(self, noeud, liaison):
        self._reseau_sourd(noeud, liaison)
        resultat = analyser("PROD")
        assert resultat["puissance_connue"] is False
        assert len(resultat["sourds"]) == 1
        assert resultat["sourds"][0]["puissance_connue"] is False

    def test_une_difference_de_puissance_connue_explique_l_ecart_et_annule_le_diagnostic(self, noeud, liaison):
        """Le cas qui comptait : 10 émet 12 dB plus fort que ses voisins. Il n'est pas sourd, il
        crie. Avant la lecture de configuration, on l'aurait envoyé réparer une antenne."""
        self._reseau_sourd(noeud, liaison)
        self._config(10, 22)
        self._config(20, 10)
        self._config(30, 10)
        resultat = analyser("PROD")
        assert resultat["puissance_connue"] is True
        assert resultat["noeuds_puissance_connue"] == 3
        assert resultat["sourds"] == []

    def test_le_diagnostic_tient_quand_les_puissances_sont_egales(self, noeud, liaison):
        self._reseau_sourd(noeud, liaison)
        for num in (10, 20, 30):
            self._config(num, 20)
        resultat = analyser("PROD")
        assert len(resultat["sourds"]) == 1
        # Corrigé, et marqué comme tel : la conclusion ne vaut pas la même chose qu'une
        # conclusion non corrigée.
        assert resultat["sourds"][0]["puissance_connue"] is True

    def test_une_puissance_a_zero_est_traitee_comme_inconnue(self, noeud, liaison):
        """Piège central : le firmware interprète tx_power = 0 comme « maximum de la région ».
        La prendre pour 0 dBm inventerait un écart de 20 dB qui n'existe pas."""
        self._reseau_sourd(noeud, liaison)
        self._config(10, 0)
        self._config(20, 20)
        self._config(30, 20)
        resultat = analyser("PROD")
        assert resultat["noeuds_puissance_connue"] == 2
        assert len(resultat["sourds"]) == 1
        assert resultat["sourds"][0]["puissance_connue"] is False

    def test_une_seule_puissance_connue_ne_corrige_rien(self, noeud, liaison):
        """Une demi-correction serait pire que pas de correction."""
        self._reseau_sourd(noeud, liaison)
        self._config(10, 22)
        resultat = analyser("PROD")
        assert len(resultat["sourds"]) == 1
        assert all(m["correction_db"] == 0.0 for m in resultat["sourds"][0]["mesures"])

    def test_un_desequilibre_explique_par_la_puissance_n_est_plus_signale(self, noeud, liaison):
        noeud(40); noeud(50)
        liaison(40, 50, snr=8.0)
        liaison(50, 40, snr=-5.0)
        assert len(analyser("PROD")["desequilibrees"]) == 1
        self._config(40, 27)
        self._config(50, 14)       # 13 dB d'écart de puissance : il explique tout l'écart de SNR
        assert analyser("PROD")["desequilibrees"] == []


@pytest.mark.django_db
class TestReglagesDeNoeud:
    """Écritures de configuration : l'équivalent de son `modifier()`.

    Tout est validé AVANT de traverser la radio : Django est le seul point d'entrée, et refuser
    tout de suite avec un message lisible vaut mieux que laisser l'exploitant attendre trente
    secondes un échec rapporté par le pont."""

    def test_le_catalogue_sert_de_source_unique_aux_bornes(self, institutionnel):
        """Les bornes sont des contraintes du firmware : les recopier dans le frontend
        garantirait qu'elles divergent."""
        reponse = institutionnel.get(f"{URL_LISTE}reglages/")
        assert reponse.status_code == 200
        sections = reponse.data["sections"]
        assert set(sections) >= {"device", "lora", "position", "voisinage", "telemetrie"}
        lora = sections["lora"]
        assert lora["redemarre"] is True           # le firmware redémarre sur un changement LoRa
        assert lora["champs"]["hop_limit"] == {
            "type": "entier", "libelle": "Nombre de sauts",
            "aide": lora["champs"]["hop_limit"]["aide"], "mini": 1, "maxi": 7,
            "valeurs_speciales": [], "reglementaire": False, "avertissement": "",
        }
        assert sections["voisinage"]["module"] is True
        # 4 h : minimum imposé par le firmware pour un rapport de voisinage sur LoRa.
        assert sections["voisinage"]["champs"]["update_interval"]["mini"] == 14400

    def test_la_lecture_d_une_section_est_ouverte_aux_institutionnels(self, institutionnel, passerelle):
        reponse = institutionnel.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "LIRE_REGLAGES",
            "parametres": {"section": "voisinage"},
        }, format="json")
        assert reponse.status_code == 201

    def test_une_section_inconnue_est_refusee(self, institutionnel, passerelle):
        reponse = institutionnel.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "LIRE_REGLAGES",
            "parametres": {"section": "bluetooth"},
        }, format="json")
        assert reponse.status_code == 400
        assert "section attendue" in str(reponse.data)

    def test_une_ecriture_de_reglages_exige_de_repondre_du_materiel(self, create_user, passerelle):
        """**Ce test exigeait le rôle administrateur jusqu'au 10/11/2026.** Le critère n'est plus
        le grade mais la propriété : l'institution qui a déployé cette passerelle écrit dessus
        (voir le test de TestCreationDesTaches), une autre non. C'est cette seconde moitié qui
        est vérifiée ici."""
        itype, _ = InstitutionType.objects.get_or_create(
            code="MAIRIE", defaults={"libelle": "Mairie"},
        )
        autre = Institution.objects.create(nom="Mairie etrangere aux reglages", type=itype)
        client = _client(create_user, "SECOURS", autre, "secours-reglages-etranger@x.fr")

        reponse = client.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_REGLAGES",
            "parametres": {"section": "lora", "valeurs": {"hop_limit": 4}},
        }, format="json")
        assert reponse.status_code == 403

    def test_un_administrateur_peut_modifier_le_nombre_de_sauts(self, administrateur, passerelle):
        """`hop_limit` seul : il change la portée, pas la bande ni la puissance — donc pas de
        confirmation réglementaire. `tx_power` en exigerait une (voir TestReglagesReglementes)."""
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_REGLAGES",
            "parametres": {"section": "lora", "valeurs": {"hop_limit": 4}},
        }, format="json")
        assert reponse.status_code == 201, reponse.data
        assert TacheAdminMeshtastic.objects.get().est_ecriture

    @pytest.mark.parametrize("valeurs,extrait", [
        ({"hop_limit": 9}, "hors bornes"),
        ({"hop_limit": "trois"}, "entier est attendu"),
        ({"hop_limit": True}, "entier est attendu"),
        ({"region": "UNSET"}, "n'est pas acceptée"),
        ({"modem_preset": "SUPER_RAPIDE"}, "inconnue"),
        ({"region": "ATLANTIDE"}, "inconnue"),
        ({"tx_power": 40}, "hors bornes"),
        ({"override_frequency": 1200.0}, "hors bornes"),
        ({"channel_num": 500}, "hors bornes"),
        # Valides, mais refusées faute de confirmation réglementaire (TestReglagesReglementes).
        ({"region": "US"}, "contrainte réglementaire"),
        ({"tx_power": 30}, "contrainte réglementaire"),
        ({"override_frequency": 868.5}, "contrainte réglementaire"),
        ({"channel_num": 20}, "contrainte réglementaire"),
        ({}, "Aucun réglage"),
    ])
    def test_les_valeurs_invalides_sont_refusees_avec_la_raison(self, administrateur, passerelle,
                                                               valeurs, extrait):
        """**Politique inversée le 09/11/2026, à la demande de l'exploitant.** `override_frequency`,
        `channel_num`, `tx_power` au-dessus de 27 dBm et les régions hors Europe étaient hors
        liste blanche, refusés par principe. Ils sont désormais modifiables : 868 MHz ne désigne
        pas la même bande ni les mêmes conditions en métropole et à La Réunion, et trancher à sa
        place l'empêchait de faire ce que sa situation autorise. Ce qui reste refusé ici, c'est
        une valeur qu'aucune région n'accepterait, ou une demande non confirmée."""
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_REGLAGES",
            "parametres": {"section": "lora", "valeurs": valeurs},
        }, format="json")
        assert reponse.status_code == 400, valeurs
        assert extrait in str(reponse.data), reponse.data

    def test_le_minimum_de_temps_d_antenne_du_voisinage_est_impose(self, administrateur, passerelle):
        """4 h entre deux rapports : limite du firmware, pas une préférence. Un rapport de
        voisinage est volumineux et le diffuser souvent sature le réseau pour tout le monde."""
        refuse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_REGLAGES",
            "parametres": {"section": "voisinage", "valeurs": {"update_interval": 3600}},
        }, format="json")
        assert refuse.status_code == 400

        accepte = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_REGLAGES",
            "parametres": {"section": "voisinage", "valeurs": {"update_interval": 14400,
                                                               "enabled": True}},
        }, format="json")
        assert accepte.status_code == 201, accepte.data

    def test_zero_reste_accepte_pour_l_intervalle_de_telemetrie(self, administrateur, passerelle):
        """0 n'est pas une valeur basse : c'est « valeur par défaut du firmware »."""
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_REGLAGES",
            "parametres": {"section": "telemetrie", "valeurs": {"device_update_interval": 0}},
        }, format="json")
        assert reponse.status_code == 201, reponse.data

    def test_le_nom_court_est_borne_en_octets_pas_en_caracteres(self, administrateur, passerelle):
        """Quatre lettres accentuées font huit octets : le firmware tronquerait en silence."""
        refuse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_NOM",
            "parametres": {"nom_court": "éééé"},
        }, format="json")
        assert refuse.status_code == 400
        assert "octets" in str(refuse.data)

        accepte = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_NOM",
            "parametres": {"nom_court": "PILA", "nom_long": "Relais du Pilat"},
        }, format="json")
        assert accepte.status_code == 201, accepte.data

    def test_renommer_sans_nom_est_refuse(self, administrateur, passerelle):
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_NOM", "parametres": {},
        }, format="json")
        assert reponse.status_code == 400

    def test_une_ecriture_de_reglages_est_refusee_depuis_la_demo(self, administrateur, passerelle):
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_REGLAGES",
            "parametres": {"section": "device", "valeurs": {"role": "ROUTER"}},
        }, format="json", HTTP_X_ENVIRONMENT="DEMO")
        assert reponse.status_code == 403

    def test_le_role_et_la_rediffusion_sont_modifiables(self, administrateur, passerelle):
        """Les deux réglages qui décident si un relais relaie vraiment : un nœud au mauvais rôle
        est un relais mort, et c'était invisible et incorrigible à distance."""
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_REGLAGES",
            "parametres": {"section": "device",
                           "valeurs": {"role": "ROUTER", "rebroadcast_mode": "ALL"}},
        }, format="json")
        assert reponse.status_code == 201, reponse.data


@pytest.mark.django_db
class TestReglagesReglementes:
    """Réglages qui décident de ce qui part dans l'air : fréquence, numéro de canal, décalage,
    rapport cyclique, puissance, région.

    Ils sont EXPOSÉS (décision du 09/11/2026) : 868 MHz ne désigne pas la même bande ni les mêmes
    conditions en métropole et à La Réunion, et un outil qui tranche à la place de l'exploitant
    l'empêche de faire ce que sa situation autorise. Ce qui est verrouillé ici, ce n'est donc pas
    l'interdiction — c'est que la demande soit DÉLIBÉRÉE et TRAÇABLE : confirmation explicite,
    nominative, au journal d'audit. Et que l'avertissement affiché dise la vérité du firmware,
    pas une généralité."""

    def _ecrire(self, client, passerelle, valeurs, confirmer=False):
        parametres = {"section": "lora", "valeurs": valeurs}
        if confirmer:
            parametres["confirmation_reglementaire"] = True
        return client.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_REGLAGES",
            "parametres": parametres,
        }, format="json")

    @pytest.mark.parametrize("valeurs", [
        {"override_frequency": 869.525},
        {"channel_num": 3},
        {"frequency_offset": 0.002},
        {"override_duty_cycle": True},
        {"region": "US"},
        {"tx_power": 30},
    ])
    def test_un_reglage_reglemente_est_refuse_sans_confirmation(self, administrateur, passerelle, valeurs):
        reponse = self._ecrire(administrateur, passerelle, valeurs)
        assert reponse.status_code == 400
        assert "contrainte réglementaire" in str(reponse.data)
        assert TacheAdminMeshtastic.objects.count() == 0

    @pytest.mark.parametrize("valeurs", [
        {"override_frequency": 869.525},
        {"channel_num": 3},
        {"frequency_offset": 0.002},
        {"override_duty_cycle": True},
        {"region": "US"},
        {"tx_power": 30},
    ])
    def test_le_meme_reglage_passe_avec_la_confirmation(self, administrateur, passerelle, valeurs):
        """Le but n'est pas d'interdire : c'est de rendre l'acte délibéré."""
        reponse = self._ecrire(administrateur, passerelle, valeurs, confirmer=True)
        assert reponse.status_code == 201, reponse.data
        assert TacheAdminMeshtastic.objects.get().parametres["confirmation_reglementaire"] is True

    def test_la_confirmation_est_lisible_dans_le_journal_d_audit(self, administrateur, passerelle):
        """C'est ce qu'on cherchera si la question est posée : enfouie dans le dictionnaire de
        paramètres, elle serait introuvable."""
        from core.models import AuditLog
        self._ecrire(administrateur, passerelle, {"override_duty_cycle": True}, confirmer=True)
        journal = AuditLog.objects.filter(objet_type="TacheAdminMeshtastic").latest('date_action')
        assert "CONFIRMATION REGLEMENTAIRE" in journal.commentaire

    def test_un_reglage_anodin_n_exige_aucune_confirmation(self, administrateur, passerelle):
        """Sinon la case devient un réflexe, et une case cochée par réflexe ne protège de rien."""
        reponse = self._ecrire(administrateur, passerelle, {"hop_limit": 5})
        assert reponse.status_code == 201, reponse.data

    def test_un_melange_exige_la_confirmation_a_cause_du_seul_champ_reglemente(self, administrateur, passerelle):
        reponse = self._ecrire(administrateur, passerelle, {"hop_limit": 5, "tx_power": 30})
        assert reponse.status_code == 400
        assert "tx_power" in str(reponse.data)

    def test_la_fraction_de_mhz_est_conservee(self, administrateur, passerelle):
        """Un décalage de quartz se compte en kHz : arrondir 0,002 MHz à l'entier le rendrait
        inutilisable, et arrondir une fréquence déplacerait le nœud hors du réseau."""
        self._ecrire(administrateur, passerelle, {"override_frequency": 869.525}, confirmer=True)
        assert TacheAdminMeshtastic.objects.get().parametres["valeurs"]["override_frequency"] == 869.525

    @pytest.mark.parametrize("valeurs", [
        {"override_frequency": 1200.0},       # hors 400-1000 MHz
        {"override_frequency": True},         # un booléen n'est pas une fréquence
        {"frequency_offset": 50.0},           # 50 MHz de décalage n'a aucun sens
        {"channel_num": 500},                 # aucune région n'a 500 créneaux
        {"tx_power": 40},                     # au-dessus de toute région du firmware
        {"region": "ATLANTIDE"},
    ])
    def test_une_valeur_absurde_reste_refusee_meme_confirmee(self, administrateur, passerelle, valeurs):
        """La confirmation lève la contrainte réglementaire, pas les bornes : elle dit « j'assume
        la conformité », pas « accepte n'importe quoi »."""
        reponse = self._ecrire(administrateur, passerelle, valeurs, confirmer=True)
        assert reponse.status_code == 400

    def test_zero_desactive_la_frequence_imposee(self, administrateur, passerelle):
        """0 est hors de l'intervalle 400-1000 et pourtant accepté : c'est la valeur « le nœud
        suit le plan de canaux de sa région »."""
        reponse = self._ecrire(administrateur, passerelle, {"override_frequency": 0}, confirmer=True)
        assert reponse.status_code == 201, reponse.data

    def test_la_puissance_dediee_passe_seule_sous_le_plafond_francais(self, administrateur, passerelle):
        reponse = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": 27},
        }, format="json")
        assert reponse.status_code == 201, reponse.data

    def test_la_puissance_dediee_au_dessus_de_27_dbm_exige_la_confirmation(self, administrateur, passerelle):
        """27 dBm (500 mW) est le plafond que le firmware applique à EU_868. Au-dessus, certaines
        régions l'autorisent et le firmware ne borne plus un propriétaire « licencié » : c'est
        donc possible, mais pas par inadvertance."""
        refus = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": 30},
        }, format="json")
        assert refus.status_code == 400
        assert "confirmation_reglementaire" in str(refus.data)

        accord = administrateur.post(URL_LISTE, {
            "compagnon": str(passerelle.id), "type_tache": "DEFINIR_PUISSANCE",
            "parametres": {"puissance_dbm": 30, "confirmation_reglementaire": True},
        }, format="json")
        assert accord.status_code == 201, accord.data


@pytest.mark.django_db
class TestAvertissementsDuCatalogue:
    """L'avertissement doit dire la vérité du FIRMWARE, et être propre à la zone choisie.

    Un avertissement identique partout n'est pas lu. Celui d'une région dit la bande, la
    puissance et le rapport cyclique que l'appareil appliquera réellement — valeurs recopiées de
    la table RDEF de `src/mesh/RadioInterface.cpp`, pas de la documentation publique, qui ne les
    donne pas."""

    def _catalogue(self, client):
        reponse = client.get(f"{URL_LISTE}reglages/")
        assert reponse.status_code == 200
        return reponse.data

    def test_chaque_region_porte_son_propre_avertissement(self, institutionnel):
        catalogue = self._catalogue(institutionnel)
        region = catalogue["sections"]["lora"]["champs"]["region"]
        assert region["reglementaire"] is True
        avertissements = region["avertissements_par_valeur"]
        # Au moins les régions européennes et une région lointaine, chacune avec SON texte.
        assert avertissements["EU_868"] != avertissements["US"]
        assert "869.4" in avertissements["EU_868"] and "869.65" in avertissements["EU_868"]
        assert "27 dBm" in avertissements["EU_868"]
        assert "902.0" in avertissements["US"]

    def test_l_avertissement_europeen_dit_que_l_outre_mer_n_est_pas_automatique(self, institutionnel):
        """C'est le point de départ de toute cette reprise : la bande de 868 MHz n'est pas la
        même affaire en métropole et à La Réunion."""
        catalogue = self._catalogue(institutionnel)
        texte = catalogue["sections"]["lora"]["champs"]["region"]["avertissements_par_valeur"]["EU_868"]
        assert "La Réunion" in texte
        assert "chapitre 7" in texte
        assert catalogue["avertissement_france"] in texte

    def test_une_region_absente_de_la_table_du_firmware_est_signalee(self, institutionnel):
        """Sept régions existent dans le protobuf sans entrée dans la table du firmware : les
        poser peut rendre le nœud muet, et il faudra l'appareil en main."""
        catalogue = self._catalogue(institutionnel)
        assert "EU_874" in catalogue["regions_sans_table_firmware"]
        texte = catalogue["sections"]["lora"]["champs"]["region"]["avertissements_par_valeur"]["EU_874"]
        assert "muet" in texte

    def test_une_region_radioamateur_rappelle_la_licence(self, institutionnel):
        catalogue = self._catalogue(institutionnel)
        assert "ITU1_2M" in catalogue["regions_radioamateur"]
        texte = catalogue["sections"]["lora"]["champs"]["region"]["avertissements_par_valeur"]["ITU1_2M"]
        assert "licence" in texte
        assert "tiers" in texte

    def test_le_rapport_cyclique_dit_que_le_firmware_est_deja_plus_strict_que_la_loi(self, institutionnel):
        """Fait non évident, vérifié dans AirTime::isTxAllowedAirUtil : le limiteur s'arrête à la
        MOITIÉ du rapport cyclique de la région, soit 5 % en EU_868. Le désactiver ne « revient
        pas à la limite légale », il supprime toute limite côté appareil."""
        champ = self._catalogue(institutionnel)["sections"]["lora"]["champs"]["override_duty_cycle"]
        assert champ["reglementaire"] is True
        assert "5 %" in champ["avertissement"]
        assert "fenêtre glissante d'une heure" in champ["avertissement"]

    def test_la_puissance_dit_que_le_plafond_du_firmware_n_est_pas_une_garantie(self, institutionnel):
        """`is_licensed` sur le propriétaire fait sauter le plafond de région : annoncer un
        garde-fou qui n'en est pas un serait pire que de ne rien annoncer."""
        champ = self._catalogue(institutionnel)["sections"]["lora"]["champs"]["tx_power"]
        assert "is_licensed" in champ["avertissement"]

    def test_la_table_des_regions_du_firmware_est_servie(self, institutionnel):
        """Servie plutôt que recopiée dans le frontend : le plafond affiché par l'interface vient
        de là, une constante dupliquée finirait par mentir."""
        regions = self._catalogue(institutionnel)["regions_firmware"]
        assert regions["EU_868"] == {
            "debut_mhz": 869.4, "fin_mhz": 869.65,
            "rapport_cyclique_pct": 10, "puissance_max_dbm": 27,
        }

    def test_la_section_lora_est_marquee_reglementaire(self, institutionnel):
        sections = self._catalogue(institutionnel)["sections"]
        assert sections["lora"]["reglementaire"] is True
        assert sections["voisinage"]["reglementaire"] is False

    def test_un_reglage_irreversible_est_signale_meme_sans_enjeu_legal(self, institutionnel):
        """Couper l'émission n'est pas illégal — c'est juste sans retour à distance."""
        champ = self._catalogue(institutionnel)["sections"]["lora"]["champs"]["tx_enabled"]
        assert champ["reglementaire"] is False
        assert "l'appareil en main" in champ["avertissement"]
