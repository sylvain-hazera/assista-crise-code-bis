"""Décodage des trames MeshCore : en-tête, chemin, advert, charges chiffrées.

Porté de `cmd/ingestor/decoder.go`, `internal/channel` et `internal/sigvalidate` de
**CoreScope** (https://github.com/Kpa-clawbot/CoreScope, GPL-3.0), commit
`1577b57d67b869657eabe9cb5d3c9fbced520669` du 09/11/2026. Assista-Crise est en AGPL-3.0, plus
contraignante : la reprise n'impose aucune obligation nouvelle, mais chaque fichier repris
porte son origine — c'est la règle du projet (voir DOCUMENTATION.md).

Le code est réécrit en Python ; ce qui a de la valeur et qu'on ne devine pas, ce sont les
constantes et les bornes, que leur auteur a tirées du firmware et qu'il cite ligne par ligne.
Elles sont reprises avec ces références, parce qu'une borne sans sa source est une borne qu'on
finit par « corriger » au premier paquet surprenant.

**Le format, en un coup d'œil** :

```
octet 0            en-tête : bits 1-0 type de route, 5-2 type de charge, 7-6 version
[4 octets]         codes de transport, seulement sur les routes TRANSPORT_*
1 octet            octet de chemin : bits 7-6 (taille de hash − 1), bits 5-0 nombre de sauts
n octets           les sauts, chacun sur `taille_hash` octets
reste              la charge utile (184 octets au plus)
```

**Ce qui est porté, et ce qui ne l'est pas.** L'en-tête, le chemin, l'advert signé, les charges
chiffrées et les messages de canal le sont — c'est ce dont le projet a besoin pour cartographier
un réseau. Les charges exotiques (MULTIPART imbriqué, CONTROL/DISCOVER, RAW_CUSTOM) sont
reconnues par leur type et rendues brutes : CoreScope y traite des cas repérés au fil de ses
propres incidents, et recopier ce détail sans pouvoir le rejouer aurait été du bruit. Leur
`type` suffit à les compter et à les ignorer sciemment.

**Ce que le décodeur ne fait pas, volontairement** : il ne résout pas un préfixe de saut vers un
nœud. C'est une autre question, et elle est piégeuse — voir `prefixe_fiable` et
`core/resolution_prefixes.py`.
"""
import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# ── Types, tels que le firmware les numérote ────────────────────────────────
ROUTE_TRANSPORT_FLOOD, ROUTE_FLOOD, ROUTE_DIRECT, ROUTE_TRANSPORT_DIRECT = 0, 1, 2, 3

NOMS_ROUTE = {
    0: "TRANSPORT_FLOOD", 1: "FLOOD", 2: "DIRECT", 3: "TRANSPORT_DIRECT",
}

NOMS_CHARGE = {
    0x00: "REQ", 0x01: "RESPONSE", 0x02: "TXT_MSG", 0x03: "ACK", 0x04: "ADVERT",
    0x05: "GRP_TXT", 0x06: "GRP_DATA", 0x07: "ANON_REQ", 0x08: "PATH", 0x09: "TRACE",
    0x0A: "MULTIPART", 0x0B: "CONTROL", 0x0F: "RAW_CUSTOM",
}

# Charges dont le corps est chiffré et suit la même enveloppe : hash de destination (1 octet),
# hash de source (1), MAC (2), puis le chiffré.
CHARGES_CHIFFREES = {"REQ", "RESPONSE", "TXT_MSG", "ANON_REQ", "GRP_DATA"}

# Bornes du firmware (`firmware/src/MeshCore.h:19,21`). Elles ne sont pas décoratives : une
# trame qui les dépasse est malformée ou hostile, et la décoder au mieux reviendrait à lire
# au-delà du tampon.
MAX_TAILLE_CHEMIN = 64       # MAX_PATH_SIZE
MAX_CHARGE_PAQUET = 184      # MAX_PACKET_PAYLOAD
MAX_TAILLE_NOM = 32          # MAX_ADVERT_DATA_SIZE


class TrameInvalide(ValueError):
    """Trame qu'on refuse de décoder, avec la raison. Jamais un décodage « au mieux » : une
    trame à moitié comprise produit des liaisons et des positions fausses."""


# ── En-tête ─────────────────────────────────────────────────────────────────

def decoder_entete(octet):
    """Bits 1-0 : type de route. Bits 5-2 : type de charge. Bits 7-6 : version."""
    route = octet & 0x03
    charge = (octet >> 2) & 0x0F
    return {
        "type_route": route,
        "nom_route": NOMS_ROUTE.get(route, "INCONNU"),
        "type_charge": charge,
        "nom_charge": NOMS_CHARGE.get(charge, "INCONNU"),
        "version": (octet >> 6) & 0x03,
    }


def route_de_transport(type_route):
    """TRANSPORT_FLOOD et TRANSPORT_DIRECT portent 4 octets de codes avant l'octet de chemin."""
    return type_route in (ROUTE_TRANSPORT_FLOOD, ROUTE_TRANSPORT_DIRECT)


# ── Chemin ──────────────────────────────────────────────────────────────────

def chemin_valide(octet_chemin):
    """Miroir de `Packet::isValidPathLen` (firmware `src/Packet.cpp:13-18`).

    `taille_hash == 4` est **réservée** : le firmware la refuse quel que soit le nombre de
    sauts, donc un `0xC0` sur le fil est par définition malformé — même sur un paquet sans
    saut."""
    nombre = octet_chemin & 0x3F
    taille = (octet_chemin >> 6) + 1
    if taille == 4:
        return False
    return nombre * taille <= MAX_TAILLE_CHEMIN


def decoder_chemin(octet_chemin, tampon, position):
    """Les sauts, chacun sur `taille_hash` octets. Renvoie (chemin, octets consommés)."""
    if not chemin_valide(octet_chemin):
        taille, nombre = (octet_chemin >> 6) + 1, octet_chemin & 0x3F
        raise TrameInvalide(
            f"Chemin invalide : octet 0x{octet_chemin:02X} (taille_hash={taille}, "
            f"sauts={nombre}) — refusé par le firmware (Packet.cpp:13-18, "
            f"MAX_PATH_SIZE={MAX_TAILLE_CHEMIN})."
        )
    taille = (octet_chemin >> 6) + 1
    nombre = octet_chemin & 0x3F
    sauts = []
    for i in range(nombre):
        debut = position + i * taille
        fin = debut + taille
        if fin > len(tampon):
            break
        sauts.append(tampon[debut:fin].hex())
    return {"taille_hash": taille, "nombre_sauts": nombre, "sauts": sauts}, taille * nombre


# ── Confiance accordée à un préfixe ─────────────────────────────────────────

# Valeur par défaut de CoreScope, et son raisonnement vaut d'être gardé : mesuré sur un réseau
# réel, **56 % des sauts observés portent un préfixe d'un seul octet** et 41 % des répéteurs
# utilisent un hash d'un octet. Exiger 2 d'emblée ferait disparaître la moitié du graphe sans
# que rien ne l'explique à l'écran.
MIN_OCTETS_HASH_DEFAUT = 1
MAX_OCTETS_HASH = 3


def prefixe_fiable(octets, minimum=MIN_OCTETS_HASH_DEFAUT):
    """« Ce préfixe de saut peut-il servir de PREUVE de topologie ? »

    Un préfixe d'un octet n'a que 256 valeurs : au-delà d'une vingtaine de nœuds les collisions
    sont inévitables, et un candidat « unique aujourd'hui » peut être un faux positif demain.
    Ce seuil ne change rien au STOCKAGE — une trame est toujours enregistrée telle qu'elle est
    reçue — il ne décide que de ce qui a le droit de devenir une arête du graphe.

    `octets == 0` désigne une observation de longueur inconnue : elle ne peut pas prouver
    qu'elle atteint le seuil dès que celui-ci dépasse le minimum du format."""
    minimum = max(1, min(MAX_OCTETS_HASH, minimum or MIN_OCTETS_HASH_DEFAUT))
    if not octets:
        return minimum <= 1
    return octets >= minimum


# ── Charges ─────────────────────────────────────────────────────────────────

def _charge_chiffree(nom, tampon):
    if len(tampon) < 4:
        return {"type": nom, "erreur": "trop court", "brut": tampon.hex()}
    return {
        "type": nom,
        "hash_destination": tampon[0:1].hex(),
        "hash_source": tampon[1:2].hex(),
        "mac": tampon[2:4].hex(),
        "chiffre": tampon[4:].hex(),
    }


def _valider_signature_advert(cle_publique, signature, horodatage, donnees):
    """Signature Ed25519 d'un advert. Le message signé est
    `clé publique (32) + horodatage (4, petit-boutiste) + données applicatives`."""
    if len(cle_publique) != 32 or len(signature) != 64:
        return False
    message = cle_publique + struct.pack("<I", horodatage) + donnees
    try:
        Ed25519PublicKey.from_public_bytes(cle_publique).verify(signature, message)
        return True
    except (InvalidSignature, ValueError):
        return False


def decoder_advert(tampon, valider_signature=True):
    """`clé publique (32) + horodatage (4 LE) + signature (64) + données applicatives`.

    Les données applicatives commencent par un octet de drapeaux : bits 3-0 le type de nœud,
    bit 4 une position, bits 5 et 6 deux champs de capacités, bit 7 un nom."""
    if len(tampon) < 100:
        return {"type": "ADVERT", "erreur": "trop court pour un advert", "brut": tampon.hex()}

    cle_publique = tampon[0:32]
    horodatage = struct.unpack_from("<I", tampon, 32)[0]
    signature = tampon[36:100]
    donnees = tampon[100:]

    advert = {
        "type": "ADVERT",
        "cle_publique": cle_publique.hex(),
        "horodatage": horodatage,
        "signature": signature.hex(),
    }
    if valider_signature:
        advert["signature_valide"] = _valider_signature_advert(
            cle_publique, signature, horodatage, donnees,
        )

    if not donnees:
        return advert

    drapeaux = donnees[0]
    type_noeud = drapeaux & 0x0F
    a_position = bool(drapeaux & 0x10)
    a_capacites1 = bool(drapeaux & 0x20)
    a_capacites2 = bool(drapeaux & 0x40)
    a_nom = bool(drapeaux & 0x80)
    advert["drapeaux"] = {
        "brut": drapeaux, "type": type_noeud,
        "chat": type_noeud == 1, "repeteur": type_noeud == 2,
        "room": type_noeud == 3, "capteur": type_noeud == 4,
        "position": a_position, "capacites1": a_capacites1,
        "capacites2": a_capacites2, "nom": a_nom,
    }

    position = 1
    if a_position and len(donnees) >= position + 8:
        lat, lon = struct.unpack_from("<ii", donnees, position)
        # Entiers signés au millionième de degré.
        advert["latitude"] = lat / 1e6
        advert["longitude"] = lon / 1e6
        position += 8
    if a_capacites1 and len(donnees) >= position + 2:
        advert["capacites1"] = struct.unpack_from("<H", donnees, position)[0]
        position += 2
    if a_capacites2 and len(donnees) >= position + 2:
        advert["capacites2"] = struct.unpack_from("<H", donnees, position)[0]
        position += 2
    if a_nom:
        fin = donnees.find(b"\x00", position)
        if fin == -1:
            fin = len(donnees)
        nom = donnees[position:fin].decode("utf-8", errors="replace")
        # Le firmware écrit le nom dans un tampon de 32 octets : au-delà, c'est une trame
        # fabriquée, et on ne la laisse pas remplir notre champ.
        advert["nom"] = nom[:MAX_TAILLE_NOM]

    return advert


# ── Canaux : dérivation de clé et déchiffrement ─────────────────────────────

def deriver_cle_canal(nom_canal):
    """Clé AES-128 d'un canal `#nom` : les 16 premiers octets de SHA-256(nom)."""
    return hashlib.sha256(nom_canal.encode("utf-8")).digest()[:16]


def hash_canal(cle):
    """Premier octet de SHA-256(clé) : c'est lui qui préfixe une charge GRP_TXT."""
    return hashlib.sha256(cle).digest()[0]


def dechiffrer_canal(cle, mac, chiffre):
    """Vérifie le MAC puis déchiffre en AES-128-**ECB**.

    Trois détails qui font échouer en silence si on les rate, et qui viennent de leur
    implémentation :

    - le secret du HMAC est la clé de 16 octets **suivie de 16 octets nuls** ;
    - seuls les **2 premiers octets** du HMAC-SHA256 sont comparés ;
    - le chiffrement est ECB, sans vecteur d'initialisation.

    Renvoie None si le MAC ne correspond pas : c'est le cas courant sur un réseau partagé, où
    un autre groupe utilise le même NOM de canal avec une autre clé."""
    if len(cle) != 16 or len(mac) != 2 or not chiffre or len(chiffre) % 16:
        return None
    secret = cle + b"\x00" * 16
    attendu = hmac.new(secret, chiffre, hashlib.sha256).digest()
    if attendu[0] != mac[0] or attendu[1] != mac[1]:
        return None
    chiffreur = Cipher(algorithms.AES(cle), modes.ECB()).decryptor()
    return chiffreur.update(chiffre) + chiffreur.finalize()


def lire_message_canal(clair):
    """`horodatage (4 LE) + drapeaux (1) + "expéditeur: message"`, terminé par des zéros."""
    if len(clair) < 5:
        return None
    horodatage = struct.unpack_from("<I", clair, 0)[0]
    texte = clair[5:].split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    expediteur, separateur, message = texte.partition(": ")
    return {
        "horodatage": horodatage,
        "expediteur": expediteur if separateur else "",
        "message": message if separateur else texte,
    }


def decoder_charge(nom_charge, tampon, valider_signature=True):
    if nom_charge == "ADVERT":
        return decoder_advert(tampon, valider_signature)
    if nom_charge in CHARGES_CHIFFREES:
        return _charge_chiffree(nom_charge, tampon)
    if nom_charge == "ACK":
        if len(tampon) < 4:
            return {"type": "ACK", "erreur": "trop court", "brut": tampon.hex()}
        return {"type": "ACK", "somme": struct.unpack_from("<I", tampon, 0)[0]}
    if nom_charge == "GRP_TXT":
        if len(tampon) < 3:
            return {"type": "GRP_TXT", "erreur": "trop court", "brut": tampon.hex()}
        return {
            "type": "GRP_TXT",
            "hash_canal": tampon[0:1].hex(),
            "mac": tampon[1:3].hex(),
            "chiffre": tampon[3:].hex(),
        }
    # Types reconnus mais non décomposés : voir la docstring du module.
    return {"type": nom_charge, "brut": tampon.hex(), "octets": len(tampon)}


# ── Entrée ──────────────────────────────────────────────────────────────────

def decoder_paquet(trame_hex, valider_signature=True):
    """Décode une trame MeshCore brute. Lève `TrameInvalide` plutôt que de deviner."""
    nettoyee = "".join(trame_hex.split())
    try:
        tampon = bytes.fromhex(nettoyee)
    except ValueError as erreur:
        raise TrameInvalide(f"Hexadécimal invalide : {erreur}") from erreur
    if len(tampon) < 2:
        raise TrameInvalide("Trame trop courte : il faut au moins l'en-tête et l'octet de chemin.")

    entete = decoder_entete(tampon[0])
    position = 1

    codes = None
    if route_de_transport(entete["type_route"]):
        if len(tampon) < position + 4:
            raise TrameInvalide("Trame trop courte pour les codes de transport.")
        codes = {"code1": tampon[position:position + 2].hex(),
                 "code2": tampon[position + 2:position + 4].hex()}
        position += 4

    if position >= len(tampon):
        raise TrameInvalide("Trame trop courte : pas d'octet de chemin.")
    octet_chemin = tampon[position]
    position += 1

    chemin, consommes = decoder_chemin(octet_chemin, tampon, position)
    position += consommes
    if position > len(tampon):
        # Un octet de chemin peut annoncer jusqu'à 3 × 63 octets : sans cette garde, la tranche
        # suivante lirait au-delà du tampon.
        raise TrameInvalide(
            f"Le chemin annoncé ({consommes} octets par l'octet 0x{octet_chemin:02X}) dépasse "
            f"la trame ({len(tampon)} octets)."
        )

    charge_brute = tampon[position:]
    if len(charge_brute) > MAX_CHARGE_PAQUET:
        raise TrameInvalide(
            f"Charge de {len(charge_brute)} octets au-delà du maximum du firmware "
            f"({MAX_CHARGE_PAQUET}, MeshCore.h:19)."
        )

    return {
        "entete": entete,
        "codes_transport": codes,
        "chemin": chemin,
        "charge": decoder_charge(entete["nom_charge"], charge_brute, valider_signature),
        "brut": tampon.hex(),
    }
