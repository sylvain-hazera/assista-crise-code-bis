"""Signature des versions que les satellites acceptent d'installer.

Demande de Sylvain du 14/11/2026 : pouvoir lancer la mise à jour d'un satellite depuis le
central, **avec signature dès maintenant**.

**Pourquoi signer.** Un ordre de mise à jour fait exécuter du code sur une machine posée chez
un tiers. Sans signature, quiconque prend la main sur le central — ou sur un compte
d'administrateur — fait installer ce qu'il veut sur tous les satellites. Avec, le central ne
peut que **transmettre** : il désigne une version, mais seul le détenteur de la clé privée
peut en rendre une installable. Cette clé n'est jamais dans le dépôt, et jamais EN CLAIR sur le
serveur : depuis le 15/11/2026 il peut en garder une copie chiffrée par la phrase de passe de
son détenteur, pour que celui-ci signe depuis la page Satellites (voir la fin de ce module,
qui dit aussi ce que cela change).

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


# ── Signature depuis la page Satellites (15/11/2026) ────────────────────────────────────────
#
# Demande de Sylvain : « que je n'aie que la phrase de passe à rentrer dans la page web ».
#
# La signature se fait DANS LE NAVIGATEUR. Le serveur garde une copie de la clé privée
# « emballée » -- chiffrée avec la phrase de passe -- et la remet à l'administrateur ; son
# navigateur la déballe avec la phrase qu'il tape, signe, et n'envoie au serveur que le
# numéro de version et sa signature. La phrase de passe et la clé en clair ne quittent jamais
# le navigateur : ni le serveur, ni le pare-feu applicatif, ni aucun journal ne les voient.
#
# CE QUE CELA CHANGE, HONNÊTEMENT. Avant, la clé n'était pas sur le serveur. Désormais une
# copie chiffrée s'y trouve, et la page qui signe est servie par lui : quelqu'un qui prendrait
# la main sur le central pourrait modifier cette page pour capter la phrase de passe à la
# prochaine signature. Ce qui reste vrai : sans la phrase de passe, la copie ne sert à rien ;
# un compte d'administrateur volé ne suffit pas ; rien ne se signe sans un geste du détenteur.
#
# Pourquoi un emballage propre plutôt que le fichier OpenSSH : celui-ci est protégé par
# bcrypt-pbkdf, que les navigateurs n'offrent pas. PBKDF2 et AES-GCM, eux, sont natifs
# (WebCrypto), donc aucune bibliothèque de chiffrement n'est embarquée dans la page.

VERSION_EMBALLAGE = 1
ITERATIONS_EMBALLAGE = 600_000
#: Lié au chiffré (données associées) : un emballage fait pour autre chose ne se déballe pas ici.
CONTEXTE_EMBALLAGE = b"assista-crise-satellite/cle-web/v1"


def _b64(octets):
    return base64.b64encode(octets).decode("ascii")


def _cle_d_emballage(phrase, sel, iterations):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=sel,
                      iterations=iterations).derive(phrase.encode("utf-8"))


def emballer_cle(cle_privee, phrase, sel=None, vecteur=None, iterations=ITERATIONS_EMBALLAGE):
    """Chiffre une clé privée Ed25519 avec une phrase de passe, pour le navigateur.

    `sel` et `vecteur` ne se fixent que dans les tests : en service ils sont tirés au hasard."""
    import os

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if not phrase:
        raise ValueError("Phrase de passe vide.")
    sel = sel or os.urandom(16)
    vecteur = vecteur or os.urandom(12)
    pkcs8 = cle_privee.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    publique = cle_privee.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    chiffre = AESGCM(_cle_d_emballage(phrase, sel, iterations)).encrypt(
        vecteur, pkcs8, CONTEXTE_EMBALLAGE)
    return {
        "version": VERSION_EMBALLAGE,
        "derivation": "PBKDF2-SHA256",
        "iterations": iterations,
        "sel": _b64(sel),
        "vecteur": _b64(vecteur),
        "chiffre": _b64(chiffre),
        "cle_publique": _b64(publique),
    }


def deballer_cle(emballage, phrase):
    """L'inverse de `emballer_cle` -- ce que fait le navigateur. Sert aux tests et au contrôle
    fait par le script de préparation. Lève `SignatureInvalide` si la phrase est fausse."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        cle = _cle_d_emballage(phrase, base64.b64decode(emballage["sel"]), int(emballage["iterations"]))
        pkcs8 = AESGCM(cle).decrypt(
            base64.b64decode(emballage["vecteur"]), base64.b64decode(emballage["chiffre"]),
            CONTEXTE_EMBALLAGE)
    except InvalidTag:
        raise SignatureInvalide("Phrase de passe incorrecte.") from None
    return serialization.load_der_private_key(pkcs8, password=None)


def signer(cle_privee, commit):
    """Produit la signature d'un commit, au format exact de `ssh-keygen -Y sign` (Ed25519 est
    déterministe : même clé et même commit donnent le même bloc, à l'octet près).

    Le serveur ne signe jamais en service -- il n'a pas la clé en clair. Cette fonction est la
    RÉFÉRENCE à laquelle la signature faite dans le navigateur est comparée dans les tests."""
    from cryptography.hazmat.primitives import serialization

    if not commit_valide(commit):
        raise SignatureInvalide("Numéro de version attendu : les 40 caractères du commit.")
    publique = cle_privee.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    espace, algorithme = ESPACE_DE_NOMS.encode(), b"sha512"
    empreinte = hashlib.sha512(message_a_signer(commit)).digest()
    a_signer = (b"SSHSIG" + _encoder(espace) + _encoder(b"") + _encoder(algorithme)
                + _encoder(empreinte))
    bloc = (
        b"SSHSIG" + (1).to_bytes(4, "big")
        + _encoder(_encoder(_TYPE_CLE) + _encoder(publique))
        + _encoder(espace) + _encoder(b"") + _encoder(algorithme)
        + _encoder(_encoder(_TYPE_CLE) + _encoder(cle_privee.sign(a_signer)))
    )
    texte = _b64(bloc)
    lignes = [texte[i:i + 70] for i in range(0, len(texte), 70)]
    return "\n".join(["-----BEGIN SSH SIGNATURE-----", *lignes, "-----END SSH SIGNATURE-----"])


def _fichier_emballage():
    import os

    return Path(os.environ.get("SIGNATURE_SATELLITES_WEB_FILE", "/run/secrets/signature_satellites_web"))


def cle_emballee():
    """L'emballage à remettre au navigateur de l'administrateur, ou None s'il n'a pas été
    préparé (scripts/satellites/preparer-signature-web.sh) ou s'il ne correspond à aucune clé
    autorisée -- auquel cas il ne produirait que des signatures refusées."""
    import json

    try:
        emballage = json.loads(_fichier_emballage().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    attendus = {"version", "derivation", "iterations", "sel", "vecteur", "chiffre", "cle_publique"}
    if not isinstance(emballage, dict) or set(emballage) != attendus:
        return None
    try:
        if base64.b64decode(emballage["cle_publique"]) not in cles_publiques():
            return None
    except (ValueError, TypeError):
        return None
    return emballage


def derniere_version_poussee():
    """Le dernier commit de la branche de référence sur le dépôt public, ou lève
    `SignatureInvalide` avec la raison.

    On ne signe que ce qui est DÉJÀ poussé : un satellite récupère son code sur ce dépôt, et
    une version signée qu'il ne peut pas télécharger est un ordre qui échoue partout. L'appel
    part du serveur et ne porte que le nom du dépôt, qui est public."""
    import os

    import requests

    depot = os.environ.get("SATELLITES_DEPOT_GITHUB", "").strip()
    branche = os.environ.get("SATELLITES_BRANCHE", "main").strip() or "main"
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", depot):
        raise SignatureInvalide("Le dépôt des satellites n'est pas configuré sur ce serveur.")
    try:
        reponse = requests.get(
            f"https://api.github.com/repos/{depot}/commits/{branche}",
            headers={"Accept": "application/vnd.github+json"}, timeout=8)
        reponse.raise_for_status()
        donnees = reponse.json()
        commit = str(donnees["sha"]).lower()
        titre = str(donnees["commit"]["message"]).splitlines()[0][:120]
        date = donnees["commit"]["committer"]["date"]
    except (requests.RequestException, ValueError, KeyError, TypeError, IndexError):
        raise SignatureInvalide("Le dépôt public n'a pas répondu : réessayez dans un instant.") from None
    if not commit_valide(commit):
        raise SignatureInvalide("Le dépôt a rendu un numéro de version illisible.")
    return {"commit": commit, "titre": titre, "date": date}
