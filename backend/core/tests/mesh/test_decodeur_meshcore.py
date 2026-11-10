"""Décodage des trames MeshCore (core/decodeur_meshcore.py) et résolution des préfixes.

Les trames sont **construites octet par octet** ici, jamais copiées d'une capture : c'est le
seul moyen de savoir ce que le décodeur devrait trouver. Et la signature d'advert est une vraie
signature Ed25519, produite par la bibliothèque — une signature factice passerait à côté de ce
que la validation sert à attraper.

Ce qui est verrouillé vient du firmware MeshCore, lu le 10/11/2026 :

- un « hash » de chemin est un **préfixe de la clé publique**, pas un condensé — le firmware
  l'écrit : « hash is just prefix of pub_key » (`src/Identity.h:20`) ;
- `taille_hash == 4` est **réservée** et refusée quel que soit le nombre de sauts
  (`src/Packet.cpp:13-18`) ;
- les bornes `MAX_PATH_SIZE = 64` et `MAX_PACKET_PAYLOAD = 184` (`src/MeshCore.h:19,21`).
"""
import struct

import pytest

from core import decodeur_meshcore as dec
from core.resolution_prefixes import resoudre_chemin, resume


def entete(type_route=1, type_charge=0x04, version=0):
    """Bits 1-0 route, 5-2 charge, 7-6 version."""
    return bytes([(version << 6) | (type_charge << 2) | type_route])


def octet_chemin(taille_hash=1, nombre=0):
    return bytes([((taille_hash - 1) << 6) | nombre])


class TestEntete:

    def test_les_trois_champs_sont_lus_aux_bons_bits(self):
        # 0b01_0100_10 : version 1, charge 0x04 (ADVERT), route 2 (DIRECT).
        # Le découpage se lit de droite à gauche : 10 = route, 0100 = charge, 01 = version.
        lu = dec.decoder_entete(0b01010010)
        assert lu == {"type_route": 2, "nom_route": "DIRECT", "type_charge": 0x04,
                      "nom_charge": "ADVERT", "version": 1}

        # Et une charge GRP_TXT (0x05) sur une route FLOOD, pour fixer l'autre décalage.
        lu = dec.decoder_entete((0x05 << 2) | 1)
        assert (lu["type_charge"], lu["nom_charge"], lu["nom_route"]) == (5, "GRP_TXT", "FLOOD")

    def test_un_type_inconnu_est_nomme_inconnu_et_non_devine(self):
        lu = dec.decoder_entete((0x0C << 2) | 1)
        assert lu["nom_charge"] == "INCONNU"
        assert lu["type_charge"] == 0x0C

    @pytest.mark.parametrize("route,transport", [(0, True), (1, False), (2, False), (3, True)])
    def test_seules_les_routes_transport_portent_des_codes(self, route, transport):
        assert dec.route_de_transport(route) is transport


class TestChemin:

    def test_la_taille_de_hash_4_est_reservee_meme_sans_saut(self):
        """Le firmware la refuse quel que soit le nombre de sauts : un 0xC0 sur le fil est par
        définition malformé, et le décoder « au mieux » serait accepter une trame fabriquée."""
        assert dec.chemin_valide(0xC0) is False
        with pytest.raises(dec.TrameInvalide, match="réservée|Chemin invalide"):
            dec.decoder_chemin(0xC0, b"", 0)

    def test_un_chemin_au_dela_de_MAX_PATH_SIZE_est_refuse(self):
        # taille_hash 3, 63 sauts = 189 octets > 64
        assert dec.chemin_valide(0b10_111111) is False

    def test_les_sauts_sont_decoupes_a_la_taille_annoncee(self):
        tampon = bytes.fromhex("aabbcc")
        chemin, consommes = dec.decoder_chemin(octet_chemin(1, 3)[0], tampon, 0)
        assert chemin == {"taille_hash": 1, "nombre_sauts": 3, "sauts": ["aa", "bb", "cc"]}
        assert consommes == 3

        chemin, consommes = dec.decoder_chemin(octet_chemin(3, 1)[0], tampon, 0)
        assert chemin["sauts"] == ["aabbcc"]
        assert consommes == 3


class TestConfianceDesPrefixes:

    def test_un_prefixe_court_passe_au_seuil_par_defaut(self):
        """Le défaut est 1 et c'est délibéré : 56 % des sauts d'un réseau réel portent un
        préfixe d'un octet, un seuil à 2 ferait disparaître la moitié du graphe."""
        assert dec.prefixe_fiable(1) is True

    def test_un_seuil_releve_ecarte_les_prefixes_courts(self):
        assert dec.prefixe_fiable(1, minimum=2) is False
        assert dec.prefixe_fiable(2, minimum=2) is True

    def test_une_longueur_inconnue_ne_prouve_rien_des_que_le_seuil_monte(self):
        assert dec.prefixe_fiable(0, minimum=1) is True
        assert dec.prefixe_fiable(0, minimum=2) is False


class TestPaquetComplet:

    def test_un_paquet_sans_saut_se_decode(self):
        trame = entete(type_route=1, type_charge=0x03) + octet_chemin(1, 0) + struct.pack("<I", 42)
        lu = dec.decoder_paquet(trame.hex())
        assert lu["entete"]["nom_charge"] == "ACK"
        assert lu["chemin"]["sauts"] == []
        assert lu["charge"] == {"type": "ACK", "somme": 42}
        assert lu["codes_transport"] is None

    def test_une_route_de_transport_consomme_ses_quatre_octets(self):
        trame = (entete(type_route=0, type_charge=0x03) + bytes.fromhex("11223344")
                 + octet_chemin(1, 0) + struct.pack("<I", 7))
        lu = dec.decoder_paquet(trame.hex())
        assert lu["codes_transport"] == {"code1": "1122", "code2": "3344"}
        assert lu["charge"]["somme"] == 7

    def test_un_chemin_qui_deborde_du_tampon_est_refuse(self):
        """Sans cette garde, la tranche suivante lirait au-delà du tampon : l'octet de chemin
        vient du fil et peut annoncer jusqu'à 3 × 63 octets."""
        # Un chemin VALIDE au sens du firmware (20 × 1 octet ≤ MAX_PATH_SIZE) mais plus long
        # que la trame : c'est ce cas-là que la garde attrape, pas un chemin malformé.
        trame = entete() + octet_chemin(1, 20) + b"\x01\x02"
        with pytest.raises(dec.TrameInvalide, match="dépasse"):
            dec.decoder_paquet(trame.hex())

    def test_une_charge_au_dela_du_maximum_du_firmware_est_refusee(self):
        trame = entete(type_charge=0x0F) + octet_chemin(1, 0) + b"\x00" * 200
        with pytest.raises(dec.TrameInvalide, match="184"):
            dec.decoder_paquet(trame.hex())

    def test_un_hexadecimal_invalide_est_refuse_et_non_tronque(self):
        with pytest.raises(dec.TrameInvalide, match="Hexadécimal"):
            dec.decoder_paquet("zz")

    def test_une_charge_chiffree_expose_son_enveloppe_sans_la_dechiffrer(self):
        corps = bytes.fromhex("aa") + bytes.fromhex("bb") + bytes.fromhex("1234") + b"chiffre!"
        trame = entete(type_charge=0x02) + octet_chemin(1, 0) + corps
        charge = dec.decoder_paquet(trame.hex())["charge"]
        assert charge["type"] == "TXT_MSG"
        assert charge["hash_destination"] == "aa"
        assert charge["hash_source"] == "bb"
        assert charge["mac"] == "1234"


class TestAdvert:

    def _advert(self, donnees, cle_privee=None):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization

        cle_privee = cle_privee or Ed25519PrivateKey.generate()
        publique = cle_privee.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
        )
        horodatage = 1762700000
        message = publique + struct.pack("<I", horodatage) + donnees
        signature = cle_privee.sign(message)
        return publique + struct.pack("<I", horodatage) + signature + donnees, publique

    def test_un_advert_signe_est_reconnu_valide(self):
        """Vraie signature Ed25519 : une signature factice passerait à côté de ce que la
        validation sert à attraper."""
        donnees = bytes([0x82]) + b"Relais du piton\x00"   # drapeaux : répéteur + nom
        corps, publique = self._advert(donnees)
        lu = dec.decoder_advert(corps)

        assert lu["signature_valide"] is True
        assert lu["cle_publique"] == publique.hex()
        assert lu["nom"] == "Relais du piton"
        assert lu["drapeaux"]["repeteur"] is True
        assert lu["drapeaux"]["position"] is False

    def test_un_advert_altere_est_reconnu_invalide(self):
        donnees = bytes([0x82]) + b"Relais\x00"
        corps, _ = self._advert(donnees)
        # On change UN octet des données signées : la signature ne doit plus correspondre.
        altere = bytearray(corps)
        altere[-3] ^= 0xFF
        assert dec.decoder_advert(bytes(altere))["signature_valide"] is False

    def test_une_position_est_lue_au_millionieme_de_degre(self):
        # Drapeaux : position (0x10) + nom (0x80). La Réunion, approximativement.
        lat, lon = -21123456, 55456789
        donnees = bytes([0x90]) + struct.pack("<ii", lat, lon) + b"Piton\x00"
        corps, _ = self._advert(donnees)
        lu = dec.decoder_advert(corps)

        assert lu["latitude"] == pytest.approx(-21.123456)
        assert lu["longitude"] == pytest.approx(55.456789)
        assert lu["nom"] == "Piton"

    def test_une_position_negative_est_signee(self):
        """Piège classique : lire les coordonnées en non signé place tout l'hémisphère sud en
        Sibérie."""
        donnees = bytes([0x10]) + struct.pack("<ii", -21000000, -55000000)
        corps, _ = self._advert(donnees)
        lu = dec.decoder_advert(corps)
        assert lu["latitude"] < 0 and lu["longitude"] < 0

    def test_un_nom_trop_long_est_tronque_a_la_taille_du_firmware(self):
        donnees = bytes([0x80]) + b"X" * 80 + b"\x00"
        corps, _ = self._advert(donnees)
        assert len(dec.decoder_advert(corps)["nom"]) == dec.MAX_TAILLE_NOM

    def test_un_advert_trop_court_ne_leve_pas(self):
        lu = dec.decoder_advert(b"\x01" * 50)
        assert "erreur" in lu


class TestCanaux:

    def test_la_cle_se_derive_du_nom(self):
        import hashlib
        cle = dec.deriver_cle_canal("#public")
        assert len(cle) == 16
        assert cle == hashlib.sha256(b"#public").digest()[:16]

    def test_un_aller_retour_de_chiffrement(self):
        """Le secret du HMAC est la clé SUIVIE DE 16 OCTETS NULS, et seuls deux octets du MAC
        sont comparés : rater l'un ou l'autre fait échouer en silence."""
        import hashlib
        import hmac as _hmac
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        cle = dec.deriver_cle_canal("#test")
        clair = struct.pack("<I", 1762700000) + b"\x00" + b"Jean: bonjour" + b"\x00" * 2
        clair += b"\x00" * (-len(clair) % 16)
        chiffreur = Cipher(algorithms.AES(cle), modes.ECB()).encryptor()
        chiffre = chiffreur.update(clair) + chiffreur.finalize()
        mac = _hmac.new(cle + b"\x00" * 16, chiffre, hashlib.sha256).digest()[:2]

        obtenu = dec.dechiffrer_canal(cle, mac, chiffre)
        assert obtenu is not None
        message = dec.lire_message_canal(obtenu)
        assert message["expediteur"] == "Jean"
        assert message["message"] == "bonjour"

    def test_un_mac_qui_ne_correspond_pas_rend_None(self):
        """Cas courant sur un réseau partagé : un autre groupe utilise le même NOM de canal
        avec une autre clé. Ce n'est pas une erreur de chez nous."""
        cle = dec.deriver_cle_canal("#test")
        assert dec.dechiffrer_canal(cle, b"\x00\x00", b"\x00" * 16) is None

    def test_un_chiffre_de_taille_invalide_rend_None(self):
        cle = dec.deriver_cle_canal("#test")
        assert dec.dechiffrer_canal(cle, b"\x00\x00", b"\x00" * 15) is None


CLE_A = "aa" + "11" * 31
CLE_B = "aa" + "22" * 31      # même premier octet que CLE_A : collision sur 1 octet
CLE_C = "bb" + "33" * 31


class TestResolutionDesPrefixes:

    def test_un_prefixe_unique_est_resolu_avec_certitude(self):
        noeuds = {CLE_A: (-21.0, 55.5), CLE_C: (-21.1, 55.6)}
        resolus = resoudre_chemin(["bb"], 1, noeuds)
        assert resolus[0]["certitude"] == "unique"
        assert resolus[0]["pubkey"] == CLE_C
        assert resolus[0]["fiable"] is True

    def test_un_prefixe_inconnu_reste_inconnu(self):
        """Mieux vaut un trou dans le chemin qu'un trait faux."""
        resolus = resoudre_chemin(["ff"], 1, {CLE_A: None})
        assert resolus[0]["certitude"] == "inconnu"
        assert resolus[0]["pubkey"] is None
        assert resolus[0]["fiable"] is False

    def test_une_collision_sans_position_reste_ambigue(self):
        noeuds = {CLE_A: None, CLE_B: None}
        resolus = resoudre_chemin(["aa"], 1, noeuds)
        assert resolus[0]["certitude"] == "ambigu"
        assert resolus[0]["candidats"] == 2
        assert resolus[0]["fiable"] is False

    def test_la_geographie_departage_mais_le_resultat_est_marque_deduit(self):
        """Une déduction géographique est une hypothèse, pas une résolution : elle sert à
        tracer un itinéraire, jamais à prouver une topologie."""
        noeuds = {CLE_C: (-21.0, 55.5), CLE_A: (-21.05, 55.52), CLE_B: (48.8, 2.3)}
        resolus = resoudre_chemin(["bb", "aa"], 1, noeuds)
        assert resolus[1]["certitude"] == "deduit"
        assert resolus[1]["pubkey"] == CLE_A          # le voisin proche, pas celui de Paris
        assert resolus[1]["fiable"] is False

    def test_la_passe_arriere_resout_un_premier_saut_ambigu(self):
        """Sans elle, un chemin dont le premier saut est ambigu ne se résoudrait jamais."""
        noeuds = {CLE_A: (-21.05, 55.52), CLE_B: (48.8, 2.3), CLE_C: (-21.0, 55.5)}
        resolus = resoudre_chemin(["aa", "bb"], 1, noeuds)
        assert resolus[0]["certitude"] == "deduit"
        assert resolus[0]["pubkey"] == CLE_A

    def test_un_saut_invraisemblable_est_signale(self):
        noeuds = {CLE_C: (-21.0, 55.5), "cc" + "44" * 31: (48.8, 2.3),
                  "dd" + "55" * 31: (-21.02, 55.52)}
        resolus = resoudre_chemin(["bb", "cc", "dd"], 1, noeuds)
        assert resolus[1]["invraisemblable"] is True
        assert resolus[1]["fiable"] is False

    def test_un_seuil_releve_rend_tout_le_chemin_non_fiable(self):
        noeuds = {CLE_C: (-21.0, 55.5)}
        resolus = resoudre_chemin(["bb"], 1, noeuds, minimum_octets=2)
        assert resolus[0]["certitude"] == "unique"
        assert resolus[0]["fiable"] is False

    def test_le_resume_dit_si_tout_le_chemin_est_sur(self):
        noeuds = {CLE_C: (-21.0, 55.5), CLE_A: None, CLE_B: None}
        bilan = resume(resoudre_chemin(["bb", "aa"], 1, noeuds))
        assert bilan["uniques"] == 1
        assert bilan["ambigus"] == 1
        # Un seul saut deviné suffit à rendre l'itinéraire discutable.
        assert bilan["chemin_sur"] is False
