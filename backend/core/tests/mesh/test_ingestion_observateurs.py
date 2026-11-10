"""Ingestion des messages d'observateurs MeshCore (core/ingestion_observateurs_meshcore.py).

Le contrat est établi des DEUX côtés, pas supposé : les gabarits de topic viennent des chaînes
du firmware observateur `heltec_v4_repeater_observer_mqtt` v1.16
(`meshcore/%s/%s/packets`, `/raw`, `/status`), et la forme de la charge de la lecture qu'en
fait CoreScope (`cmd/ingestor/db.go:2546` : `raw`, `SNR`, `RSSI`, `origin`, `timestamp`).

Les trames sont construites ici, octet par octet, avec de vraies signatures Ed25519 : c'est le
seul moyen de savoir ce que l'ingestion devrait en tirer.
"""
import struct

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from core.ingestion_observateurs_meshcore import ingerer_paquet, lire_message, lire_topic
from core.models import LiaisonMeshCore, SourceLiaisonMeshtastic

OBSERVATEUR = "ab" * 32


def trame_advert(nom="Relais", lat=None, lon=None, cle_privee=None, signature_valide=True):
    """Une trame MeshCore complète : en-tête FLOOD + ADVERT, sans saut."""
    cle_privee = cle_privee or Ed25519PrivateKey.generate()
    publique = cle_privee.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )
    horodatage = 1762700000
    drapeaux = 0x82 | (0x10 if lat is not None else 0)
    donnees = bytes([drapeaux])
    if lat is not None:
        donnees += struct.pack("<ii", int(lat * 1e6), int(lon * 1e6))
    donnees += nom.encode() + b"\x00"

    signature = cle_privee.sign(publique + struct.pack("<I", horodatage) + donnees)
    if not signature_valide:
        signature = bytes(64)

    entete = bytes([(0x04 << 2) | 1])        # charge ADVERT, route FLOOD
    octet_chemin = bytes([0])                # taille de hash 1, aucun saut
    corps = publique + struct.pack("<I", horodatage) + signature + donnees
    return (entete + octet_chemin + corps).hex(), publique.hex()


class TestLectureDuTopic:

    def test_un_topic_d_observateur_est_decompose(self):
        assert lire_topic(f"meshcore/BOD/{OBSERVATEUR}/packets") == ("BOD", OBSERVATEUR, "packets")

    @pytest.mark.parametrize("topic", [
        "meshcore/status",                       # topic de service
        "meshcore/events/connection",            # idem
        f"meshcore/client/{OBSERVATEUR}/packets",  # client mobile, pas un observateur
        f"meshcore/BOD/{OBSERVATEUR}/inconnu",   # sous-topic qu'on ne sait pas traiter
        "autre/BOD/abc/packets",                 # pas notre racine
        "meshcore/BOD/abc",                      # trop court
    ])
    def test_ce_qui_n_est_pas_une_observation_est_refuse(self, topic):
        """Renvoyer None plutôt que deviner : le même broker porte des topics de service et de
        clients mobiles, qui ne sont pas des observations."""
        assert lire_topic(topic) is None

    def test_une_charge_json_est_lue(self):
        message = lire_message(f"meshcore/BOD/{OBSERVATEUR}/packets",
                               '{"raw": "aabb", "SNR": 7.25, "origin": "SH5"}')
        assert message.iata == "BOD"
        assert message.observateur == OBSERVATEUR
        assert message.donnees["SNR"] == 7.25

    def test_une_charge_brute_est_prise_comme_trame(self):
        """Le sous-topic `raw` ne porte pas de JSON : la charge EST la trame."""
        message = lire_message(f"meshcore/BOD/{OBSERVATEUR}/raw", "aabbcc")
        assert message.donnees == {"raw": "aabbcc"}

    def test_des_octets_indecodables_sont_rendus_en_hexadecimal(self):
        message = lire_message(f"meshcore/BOD/{OBSERVATEUR}/raw", b"\xff\xfe")
        assert message.donnees == {"raw": "fffe"}

    def test_un_json_casse_est_refuse_et_non_rafistole(self):
        assert lire_message(f"meshcore/BOD/{OBSERVATEUR}/packets", '{"raw": ') is None


@pytest.mark.django_db
class TestIngestion:

    def _message(self, **donnees):
        return lire_message(f"meshcore/BOD/{OBSERVATEUR}/packets", __import__("json").dumps(donnees))

    def test_un_advert_signe_cree_une_liaison_orientee(self):
        """L'observateur a ENTENDU l'émetteur : il est le récepteur de la liaison."""
        trame, publique = trame_advert(nom="Relais du piton")
        decode, liaison = ingerer_paquet(self._message(raw=trame, SNR=6.5))

        assert decode["charge"]["nom"] == "Relais du piton"
        assert liaison is not None
        assert liaison.emetteur_prefixe_hex == publique
        assert liaison.recepteur_pubkey_hex == OBSERVATEUR
        assert liaison.source == SourceLiaisonMeshtastic.RF
        assert liaison.snr == 6.5
        # Clé complète, pas un préfixe : un advert porte les 32 octets.
        assert liaison.prefixe_octets == 32

    def test_un_advert_a_signature_invalide_ne_cree_rien(self):
        """N'importe qui peut fabriquer un advert portant la clé d'autrui : la liaison serait
        attribuée au mauvais nœud."""
        trame, _ = trame_advert(signature_valide=False)
        decode, liaison = ingerer_paquet(self._message(raw=trame))

        assert decode is not None                 # la trame reste lisible
        assert liaison is None
        assert LiaisonMeshCore.objects.count() == 0

    def test_une_charge_chiffree_ne_produit_pas_de_liaison(self):
        """Hors advert, l'émetteur n'est pas connu : en déduire une liaison supposerait de
        savoir qui a émis."""
        entete = bytes([(0x02 << 2) | 1])         # TXT_MSG
        trame = (entete + bytes([0]) + bytes.fromhex("aabb1234") + b"chiffre!").hex()
        decode, liaison = ingerer_paquet(self._message(raw=trame))

        assert decode["charge"]["type"] == "TXT_MSG"
        assert liaison is None

    def test_les_observations_s_agregent_et_retiennent_le_meilleur_snr(self):
        cle = Ed25519PrivateKey.generate()
        for snr in (2.0, 8.5, 4.0):
            trame, _ = trame_advert(cle_privee=cle)
            ingerer_paquet(self._message(raw=trame, SNR=snr))

        liaison = LiaisonMeshCore.objects.get()
        assert liaison.snr == 8.5
        assert liaison.nombre == 3

    def test_une_trame_illisible_est_ignoree_sans_bruit(self):
        """Une trame malformée sur un broker public est attendue, pas un incident."""
        decode, liaison = ingerer_paquet(self._message(raw="00"))
        assert decode is None and liaison is None

    def test_un_message_sans_trame_ne_fait_rien(self):
        decode, liaison = ingerer_paquet(self._message(SNR=5))
        assert decode is None and liaison is None

    def test_un_snr_absent_n_invente_pas_de_valeur(self):
        """Zéro dB est une liaison correcte ; « inconnu » n'est pas une valeur."""
        trame, _ = trame_advert()
        _, liaison = ingerer_paquet(self._message(raw=trame))
        assert liaison.snr is None

    def test_la_position_d_un_advert_est_decodee(self):
        trame, _ = trame_advert(nom="Piton", lat=-21.123456, lon=55.456789)
        decode, _ = ingerer_paquet(self._message(raw=trame))
        assert decode["charge"]["latitude"] == pytest.approx(-21.123456)
        assert decode["charge"]["longitude"] == pytest.approx(55.456789)


URL_SOURCES = "/api/sources-observateurs-meshcore/"


def _utilisateur_mc(create_user, email, type_role="UTIL_SIMPLE", **extra):
    return create_user(username=email, email=email, type=type_role, **extra)


def _client_mc(utilisateur):
    from rest_framework.test import APIClient

    client = APIClient()
    client.force_authenticate(user=utilisateur)
    return client


@pytest.mark.django_db
class TestSourcesObservateurs:
    """Déclaration des brokers d'observateurs.

    Ce qui est verrouillé ici est le piège qui a coûté une journée côté Meshtastic : un filtre
    d'abonnement faux donne une connexion parfaitement réussie et zéro paquet, ce qui est
    indiscernable d'un réseau calme."""

    def _admin(self, create_user):
        return _client_mc(_utilisateur_mc(create_user, "admin-obs@x.fr", "ADMIN"))

    def test_un_administrateur_declare_une_source(self, create_user):
        from core.models import SourceObservateurMeshCore

        reponse = self._admin(create_user).post(URL_SOURCES, {
            "nom": "Analyzer France", "broker_host": "82.64.30.121", "broker_port": 1883,
            "mqtt_username": "mm", "mqtt_password": "secret", "filtre_topic": "meshcore/#",
        }, format="json")
        assert reponse.status_code == 201, reponse.data
        # Le mot de passe part, il ne revient jamais.
        assert "mqtt_password" not in reponse.data
        assert SourceObservateurMeshCore.objects.get().mqtt_username == "mm"

    def test_le_mot_de_passe_n_est_pas_stocke_en_clair(self, create_user):
        """« On ne stocke rien en clair. » Vérifié en SQL brut, pas par l'ORM."""
        from django.db import connection
        from core.models import SourceObservateurMeshCore

        self._admin(create_user).post(URL_SOURCES, {
            "nom": "Analyzer", "broker_host": "exemple.invalide",
            "mqtt_password": "mot-de-passe-reconnaissable", "filtre_topic": "meshcore/#",
        }, format="json")
        source = SourceObservateurMeshCore.objects.get()
        assert source.mqtt_password == "mot-de-passe-reconnaissable"

        with connection.cursor() as curseur:
            curseur.execute(
                "SELECT mqtt_password FROM core_sourceobservateurmeshcore WHERE id = %s",
                [str(source.id)],
            )
            brut = curseur.fetchone()[0]
        assert "mot-de-passe-reconnaissable" not in (brut or "")

    @pytest.mark.parametrize("filtre,motif", [
        ("", "requis"),
        ("autre/#", "meshcore"),
        ("meshcore/BOD/abc/packets", "joker"),
    ])
    def test_un_filtre_qui_ne_recevrait_rien_est_refuse(self, create_user, filtre, motif):
        reponse = self._admin(create_user).post(URL_SOURCES, {
            "nom": "Mauvais filtre", "broker_host": "exemple.invalide",
            "filtre_topic": filtre,
        }, format="json")
        assert reponse.status_code == 400
        assert motif in str(reponse.data).lower()

    def test_un_filtre_regional_est_accepte(self, create_user):
        """Un exploitant peut n'ouvrir la lecture que sur sa région."""
        reponse = self._admin(create_user).post(URL_SOURCES, {
            "nom": "Bordeaux seulement", "broker_host": "exemple.invalide",
            "filtre_topic": "meshcore/BOD/#",
        }, format="json")
        assert reponse.status_code == 201

    def test_un_operateur_radio_lit_mais_ne_declare_pas(self, create_user):
        """Déclarer un broker tiers engage une connexion sortante permanente : c'est un acte
        d'exploitation, pas une opération radio courante."""
        from core.models import NoeudUtilisateurMeshtastic, SourceObservateurMeshCore

        porteur = _utilisateur_mc(create_user, "porteur-obs@x.fr")
        NoeudUtilisateurMeshtastic.objects.create(utilisateur=porteur, node_num=0xB100)
        SourceObservateurMeshCore.objects.create(
            nom="Existante", broker_host="exemple.invalide", filtre_topic="meshcore/#",
        )
        client = _client_mc(porteur)

        assert client.get(URL_SOURCES).status_code == 200
        assert client.post(URL_SOURCES, {
            "nom": "Nouvelle", "broker_host": "x.invalide", "filtre_topic": "meshcore/#",
        }, format="json").status_code == 403

    def test_un_compte_sans_acces_radio_ne_voit_rien(self, create_user):
        citoyen = _utilisateur_mc(create_user, "citoyen-obs@x.fr")
        assert _client_mc(citoyen).get(URL_SOURCES).status_code == 403

    def test_le_pont_rapporte_un_abonnement_refuse(self, create_user):
        """Sans ce rapport, un abonnement refusé serait de nouveau silencieux et la source
        resterait affichée « connectée »."""
        from core.models import SourceObservateurMeshCore

        source = SourceObservateurMeshCore.objects.create(
            nom="Analyzer", broker_host="exemple.invalide", filtre_topic="meshcore/#",
        )
        admin = self._admin(create_user)
        reponse = admin.post(f"{URL_SOURCES}{source.id}/rapporter-etat/",
                             {"etat": "ERREUR", "erreur": "Abonnement refusé : Not authorized"},
                             format="json")
        assert reponse.status_code == 200
        source.refresh_from_db()
        assert source.dernier_etat == "ERREUR"
        assert "Not authorized" in source.derniere_erreur
        assert source.derniere_connexion is None
