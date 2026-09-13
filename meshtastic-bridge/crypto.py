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

import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

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
