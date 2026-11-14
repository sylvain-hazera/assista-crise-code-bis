"""Signature des versions que les satellites acceptent d'installer.

Demande de Sylvain du 14/11/2026 : pouvoir lancer la mise à jour d'un satellite depuis le
central, **avec signature dès maintenant**.

**Pourquoi signer.** Un ordre de mise à jour fait exécuter du code sur une machine posée chez
un tiers. Sans signature, quiconque prend la main sur le central — ou sur un compte
d'administrateur — fait installer ce qu'il veut sur tous les satellites. Avec, le central ne
peut que **transmettre** : il désigne une version, mais seul le détenteur de la clé privée
peut en rendre une installable. Cette clé n'est ni dans le dépôt ni sur le serveur.

**Ce qui est signé** : le numéro de commit, complet. Git adresse le contenu par son empreinte,
donc signer le commit, c'est signer tout l'arbre de fichiers — un dépôt compromis ne peut pas
servir autre chose sous ce numéro.

**Le format** est celui d'OpenSSH (`ssh-keygen -Y sign`, « SSHSIG »), pour deux raisons :
`ssh-keygen` est déjà présent sur toute machine Linux, donc le satellite vérifie sans rien
installer ; et il gère la phrase de passe de la clé privée, qu'on n'a donc pas à réinventer.
Ce module relit ce format en Python parce que l'image du central n'embarque pas `ssh-keygen`.
Il est testé contre de vraies signatures produites par `ssh-keygen`.

Le satellite, lui, refait la vérification de son côté avec SA copie de la clé publique
(`satellite/agent_mise_a_jour.py`) : celle du central n'est qu'un garde-fou de saisie.
"""
import base64
import hashlib
import re
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

#: Espace de noms de la signature. Une signature faite pour autre chose (un commit git, un
#: fichier) avec la même clé ne vaut donc PAS ordre de mise à jour.
ESPACE_DE_NOMS = "assista-crise-satellite"

FICHIER_CLES = Path(__file__).with_name("signature_satellites.pub")

_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_TYPE_CLE = b"ssh-ed25519"


class SignatureInvalide(Exception):
    """La signature ne vérifie pas, ou n'est pas lisible. Le message dit pourquoi."""


def commit_valide(commit):
    """Un numéro de commit COMPLET, en minuscules. Un préfixe est refusé : il désigne plusieurs
    commits possibles, et on ne signe pas une ambiguïté."""
    return bool(_COMMIT.match(commit or ""))


def message_a_signer(commit):
    """Le texte exact que la clé signe. Versionné (`/v1`) et en lignes `cle=valeur`, pour
    pouvoir y ajouter un jour les empreintes d'images préconstruites sans casser l'existant."""
    return f"{ESPACE_DE_NOMS}/v1\ncommit={commit}\n".encode()


def _chaine(tampon, position):
    """Lit une chaîne au format SSH : longueur sur 4 octets, puis le contenu."""
    if position + 4 > len(tampon):
        raise SignatureInvalide("Signature tronquée.")
    longueur = int.from_bytes(tampon[position:position + 4], "big")
    fin = position + 4 + longueur
    if fin > len(tampon):
        raise SignatureInvalide("Signature tronquée.")
    return tampon[position + 4:fin], fin


def _encoder(contenu):
    return len(contenu).to_bytes(4, "big") + contenu


def cles_publiques(texte=None):
    """Les clés autorisées, en octets bruts (32 octets chacune).

    Plusieurs lignes possibles : c'est ce qui permet de changer de clé sans coupure, en
    laissant l'ancienne valable le temps que la nouvelle soit en place."""
    if texte is None:
        try:
            texte = FICHIER_CLES.read_text(encoding="utf-8")
        except OSError:
            return []
    cles = []
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        champs = ligne.split()
        if len(champs) < 2 or champs[0] != _TYPE_CLE.decode():
            continue
        try:
            blob = base64.b64decode(champs[1], validate=True)
            type_cle, position = _chaine(blob, 0)
            cle, _ = _chaine(blob, position)
        except (ValueError, SignatureInvalide):
            continue
        if type_cle == _TYPE_CLE and len(cle) == 32:
            cles.append(cle)
    return cles


def verifier(commit, signature, cles=None):
    """Vérifie que `signature` est celle de `commit` par une clé autorisée. Lève sinon.

    Ne renvoie rien : il n'y a pas de « presque valide ». Tout ce qui n'est pas une signature
    Ed25519 de ce message exact, dans cet espace de noms, par une clé connue, est refusé."""
    if not commit_valide(commit):
        raise SignatureInvalide(
            "Numéro de version attendu : les 40 caractères du commit, en minuscules.")
    if cles is None:
        cles = cles_publiques()
    if not cles:
        raise SignatureInvalide(
            "Aucune clé de signature n'est configurée sur ce serveur "
            "(scripts/satellites/creer-cle-signature.sh).")

    lignes = [ligne.strip() for ligne in (signature or "").strip().splitlines()]
    if len(lignes) < 3 or lignes[0] != "-----BEGIN SSH SIGNATURE-----" \
            or lignes[-1] != "-----END SSH SIGNATURE-----":
        raise SignatureInvalide(
            "Bloc de signature attendu, de « -----BEGIN SSH SIGNATURE----- » à "
            "« -----END SSH SIGNATURE----- ».")
    try:
        blob = base64.b64decode("".join(lignes[1:-1]), validate=True)
    except ValueError:
        raise SignatureInvalide("Bloc de signature illisible (base64).") from None

    if blob[:6] != b"SSHSIG" or int.from_bytes(blob[6:10], "big") != 1:
        raise SignatureInvalide("Ce bloc n'est pas une signature OpenSSH.")
    cle_blob, position = _chaine(blob, 10)
    espace, position = _chaine(blob, position)
    reserve, position = _chaine(blob, position)
    algorithme, position = _chaine(blob, position)
    signature_blob, _ = _chaine(blob, position)

    if espace != ESPACE_DE_NOMS.encode():
        raise SignatureInvalide(
            "Cette signature a été faite pour un autre usage que les versions de satellite.")
    if algorithme not in (b"sha256", b"sha512"):
        raise SignatureInvalide("Algorithme d'empreinte non reconnu.")

    type_cle, suite = _chaine(cle_blob, 0)
    cle, _ = _chaine(cle_blob, suite)
    if type_cle != _TYPE_CLE or cle not in cles:
        raise SignatureInvalide("Cette signature ne vient pas d'une clé autorisée.")

    type_signature, suite = _chaine(signature_blob, 0)
    octets_signature, _ = _chaine(signature_blob, suite)
    if type_signature != _TYPE_CLE:
        raise SignatureInvalide("Type de signature non reconnu.")

    empreinte = hashlib.new(algorithme.decode(), message_a_signer(commit)).digest()
    signe = (b"SSHSIG" + _encoder(espace) + _encoder(reserve) + _encoder(algorithme)
             + _encoder(empreinte))
    try:
        Ed25519PublicKey.from_public_bytes(cle).verify(octets_signature, signe)
    except InvalidSignature:
        raise SignatureInvalide(
            "La signature ne correspond pas à cette version.") from None
