"""Réimplémentation du chiffrement de canal Meshtastic (AES-CTR par PSK partagée).

La lib officielle `meshtastic` (PyPI) ne fait QUE piloter un vrai appareil connecté en
série/BLE/TCP — l'appareil chiffre/déchiffre lui-même en firmware, la lib Python ne voit jamais
que des MeshPacket déjà en clair. Comme notre companion est purement logiciel (pas de matériel
radio, connexion directe au broker MQTT d'un réseau tiers comme Gaulix), c'est à NOUS de faire ce
que le firmware ferait normalement.

Sources (protocole officiel, pas une déduction) :
- Nonce = 8 octets packet_id (little-endian) + 4 octets from_node (little-endian) + 4 octets à
  zéro (compteur de bloc initial) — voir CryptoEngine::initNonce, firmware officiel
  (github.com/meshtastic/firmware, src/mesh/CryptoEngine.cpp).
- AES-CTR, clé 16 octets (AES128) ou 32 octets (AES256) selon la longueur de la PSK — voir
  CryptoEngine::encryptAESCtr, même fichier.
- PSK courte (1 octet, valeur 0x00-0x0A) = raccourci du firmware, PAS une clé secrète propre à
  assista-crise : 0x00 = pas de chiffrement, 0x01 = la clé par défaut ci-dessous inchangée,
  0x02-0x0A = même clé avec le dernier octet incrémenté de (index - 1) — voir Channels::getKey
  (Channels.cpp) et le commentaire du champ `psk` dans meshtastic/protobufs (channel.proto).
"""

from __future__ import annotations

import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import hashes, serialization

# Clé PSK "par défaut" du protocole Meshtastic (16 octets, AES128) — publiée dans le protobuf
# officiel channel.proto, pas un secret : sert uniquement de base pour les raccourcis d'index
# 0x01-0x0A, jamais utilisée telle quelle pour un canal réellement privé.
DEFAULT_PSK = bytes.fromhex("d4f1bb3a20290759f0bcffabcf4e6901")


class PskInvalidePourDechiffrement(Exception):
    pass


def deriver_cle(psk: bytes) -> bytes | None:
    """PSK brute (telle que configurée sur un canal) -> clé AES effective, ou None si le canal
    n'est pas chiffré. Accepte les trois formats du protocole : vide, index court (1 octet),
    ou clé complète (16 ou 32 octets)."""
    if len(psk) == 0:
        return None
    if len(psk) == 1:
        index = psk[0]
        if index == 0:
            return None
        cle = bytearray(DEFAULT_PSK)
        cle[-1] = (cle[-1] + index - 1) & 0xFF
        return bytes(cle)
    if len(psk) in (16, 32):
        return psk
    raise PskInvalidePourDechiffrement(f"Longueur de PSK inattendue : {len(psk)} octet(s).")


def construire_nonce(packet_id: int, from_node: int) -> bytes:
    """8 octets packet_id (LE) + 4 octets from_node (LE) + 4 octets à zéro (compteur de bloc
    initial) = bloc initial AES-CTR de 128 bits (16 octets), taille exigée par le mode CTR pour
    AES (voir docstring du module)."""
    return (
        struct.pack("<Q", packet_id & 0xFFFFFFFFFFFFFFFF)
        + struct.pack("<I", from_node & 0xFFFFFFFF)
        + b"\x00\x00\x00\x00"
    )


def chiffrer(psk: bytes, packet_id: int, from_node: int, texte_clair: bytes) -> bytes | None:
    """None si le canal n'est pas chiffré (à envoyer tel quel) — sinon le texte chiffré, de
    même longueur que l'entrée (CTR = chiffrement de flux, pas de padding)."""
    cle = deriver_cle(psk)
    if cle is None:
        return None
    nonce = construire_nonce(packet_id, from_node)
    chiffreur = Cipher(algorithms.AES(cle), modes.CTR(nonce)).encryptor()
    return chiffreur.update(texte_clair) + chiffreur.finalize()


def dechiffrer(psk: bytes, packet_id: int, from_node: int, texte_chiffre: bytes) -> bytes | None:
    """AES-CTR est symétrique (chiffrer == déchiffrer), mais séparé par lisibilité côté appelant."""
    cle = deriver_cle(psk)
    if cle is None:
        return texte_chiffre
    nonce = construire_nonce(packet_id, from_node)
    dechiffreur = Cipher(algorithms.AES(cle), modes.CTR(nonce)).decryptor()
    return dechiffreur.update(texte_chiffre) + dechiffreur.finalize()


def _xor_octets(data: bytes) -> int:
    code = 0
    for octet in data:
        code ^= octet
    return code


def hash_canal(nom: str, psk: bytes) -> int:
    """Reproduit Channels::generateHash (firmware officiel, Channels.cpp) : XOR de tous les
    octets du nom, XOR de tous les octets de la PSK RÉSOLUE (pas la forme courte), les deux
    combinés par XOR. Remplit MeshPacket.channel — un vrai appareil s'en sert pour filtrer
    rapidement les paquets d'un canal qu'il ne connaît pas, avant même de tenter le
    déchiffrement ; une valeur incorrecte ici peut faire ignorer silencieusement le paquet côté
    récepteur même si le chiffrement est par ailleurs correct."""
    cle = deriver_cle(psk) or b""
    return (_xor_octets(nom.encode("utf-8")) ^ _xor_octets(cle)) & 0xFF


# ── PKC (DM chiffrés par clé publique, firmware 2.5+) ──────────────────────────────────────
#
# Reproduit CryptoEngine::encryptCurve25519/decryptCurve25519 (firmware officiel,
# CryptoEngine.cpp) — contrairement au chiffrement par canal ci-dessus, JAMAIS testé contre du
# vrai matériel au moment de l'écriture (le PSK par canal, lui, a été validé en déchiffrant du
# trafic réel Gaulix). À manier avec précaution, premier test à faire avec un message très
# court vers un correspondant qui peut confirmer la réception en clair.
#
# - Échange Diffie-Hellman X25519 entre notre clé privée et la clé publique du correspondant
#   (Curve25519::dh2 dans le firmware — X25519 standard RFC 7748, pas une variante).
# - Clé partagée = SHA256(secret_dh) — 32 octets, utilisée directement comme clé AES-256.
# - AEAD = AES-CCM, tag d'authentification de 8 octets (pas 16, la valeur par défaut usuelle).
# - Nonce : même construction que le mode PSK (8 octets packet_id LE + 4 octets from_node LE +
#   4 octets "extraNonce"), MAIS extraNonce est ICI un tirage aléatoire 32 bits par message (PAS
#   zéro), et le nonce n'est passé à AES-CCM que TRONQUÉ à 13 octets (paramétrage CCM du
#   firmware, L=2) — les 3 derniers octets du buffer de 16 (soit les 3 derniers octets
#   d'extraNonce) ne participent donc PAS au calcul cryptographique, uniquement le premier.
# - Mise en forme du paquet sur le fil : [ciphertext][tag d'authentification, 8 octets]
#   [extraNonce COMPLET, 4 octets] — le récepteur relit extraNonce depuis la fin pour
#   reconstruire le même nonce, exactement comme le packet_id/from_node sont déjà connus par
#   ailleurs (champs en clair du MeshPacket).
PKC_TAG_LENGTH = 8
PKC_NONCE_LENGTH_CCM = 13


def cle_publique_depuis_privee_hex(cle_privee_hex: str) -> str:
    cle_privee = X25519PrivateKey.from_private_bytes(bytes.fromhex(cle_privee_hex))
    return cle_privee.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    ).hex()


def _cle_partagee_pkc(notre_cle_privee_hex: str, leur_cle_publique_hex: str) -> bytes:
    notre_cle_privee = X25519PrivateKey.from_private_bytes(bytes.fromhex(notre_cle_privee_hex))
    leur_cle_publique = X25519PublicKey.from_public_bytes(bytes.fromhex(leur_cle_publique_hex))
    secret_dh = notre_cle_privee.exchange(leur_cle_publique)
    digest = hashes.Hash(hashes.SHA256())
    digest.update(secret_dh)
    return digest.finalize()


def chiffrer_pkc(notre_cle_privee_hex: str, leur_cle_publique_hex: str, packet_id: int, from_node: int, texte_clair: bytes) -> bytes:
    cle_partagee = _cle_partagee_pkc(notre_cle_privee_hex, leur_cle_publique_hex)
    extra_nonce = int.from_bytes(os.urandom(4), "little")
    nonce16 = construire_nonce_avec_extra(packet_id, from_node, extra_nonce)
    aesccm = AESCCM(cle_partagee, tag_length=PKC_TAG_LENGTH)
    chiffre_et_tag = aesccm.encrypt(nonce16[:PKC_NONCE_LENGTH_CCM], texte_clair, None)
    return chiffre_et_tag + struct.pack("<I", extra_nonce)


def dechiffrer_pkc(notre_cle_privee_hex: str, leur_cle_publique_hex: str, packet_id: int, from_node: int, texte_chiffre: bytes) -> bytes:
    if len(texte_chiffre) < 4 + PKC_TAG_LENGTH:
        raise ValueError("Paquet PKC trop court pour contenir tag + extraNonce.")
    extra_nonce = struct.unpack("<I", texte_chiffre[-4:])[0]
    chiffre_et_tag = texte_chiffre[:-4]
    cle_partagee = _cle_partagee_pkc(notre_cle_privee_hex, leur_cle_publique_hex)
    nonce16 = construire_nonce_avec_extra(packet_id, from_node, extra_nonce)
    aesccm = AESCCM(cle_partagee, tag_length=PKC_TAG_LENGTH)
    return aesccm.decrypt(nonce16[:PKC_NONCE_LENGTH_CCM], chiffre_et_tag, None)


def construire_nonce_avec_extra(packet_id: int, from_node: int, extra_nonce: int) -> bytes:
    """Comme construire_nonce, mais avec un extraNonce explicite (0 par défaut en mode PSK,
    aléatoire en mode PKC — voir docstring de la section PKC)."""
    return (
        struct.pack("<Q", packet_id & 0xFFFFFFFFFFFFFFFF)
        + struct.pack("<I", from_node & 0xFFFFFFFF)
        + struct.pack("<I", extra_nonce & 0xFFFFFFFF)
    )
