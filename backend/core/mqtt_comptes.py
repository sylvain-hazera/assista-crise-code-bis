"""Comptes du broker MQTT : hachage au format Mosquitto et rendu des fichiers qu'il lit.

Pourquoi Django écrit ces fichiers plutôt que d'utiliser le greffon « dynamic security » de
Mosquitto, qui existe pourtant dans l'image : ce greffon ne sait créer un compte QUE par un
broker en fonctionnement (`mosquitto_ctrl -f` renvoie 0 sans rien faire pour `createClient` et
`createRole` — vérifié le 06/11/2026). Le broker ne pourrait donc authentifier personne, pas même
l'exporteur et le pont, tant que Django ne l'aurait pas amorcé. Sur une plateforme de crise, faire
dépendre la disponibilité du broker de celle de l'application n'est pas acceptable.

Ici le broker reste autonome : il s'amorce tout seul depuis ses secrets au premier démarrage, et
Django ne fait que réécrire les deux fichiers quand les comptes changent. Une boucle dans le
conteneur du broker détecte le changement et déclenche un rechargement de configuration (SIGHUP,
via `mosquitto_signal -a config-reload`) — Mosquitto relit alors `password_file` et `acl_file`.

Format du fichier de mots de passe (relevé sur `mosquitto_passwd` 2.1.2 puis reproduit à
l'identique, voir `core/tests/mesh/test_mqtt_comptes.py` qui fige un vecteur de référence) :

    <utilisateur>:$7$<iterations>$<sel en base64>$<empreinte en base64>

`$7$` désigne PBKDF2-HMAC-SHA512 ; le sel fait 64 octets ; l'empreinte est la sortie de
PBKDF2 sur 64 octets. `mosquitto_passwd` utilise 1000 itérations par défaut, on s'aligne dessus.
"""
import base64
import hashlib
import logging
import os
import re
import tempfile

logger = logging.getLogger(__name__)

# Valeurs de `mosquitto_passwd` 2.1.2. Les changer reste compatible (elles sont inscrites dans
# chaque ligne produite, donc relues telles quelles par le broker), mais il n'y a aucune raison
# de diverger de l'outil officiel.
ITERATIONS = 1000
LONGUEUR_SEL = 64
LONGUEUR_EMPREINTE = 64

# Un nom de compte MQTT sert aussi de nom de section dans le fichier de droits : on interdit tout
# ce qui pourrait y être interprété (espaces, retours à la ligne, deux-points, caractères de
# contrôle). Volontairement strict plutôt que d'échapper -- un nom de compte n'a aucune raison
# d'être exotique, et une injection dans un fichier de droits donnerait des droits.
MOTIF_NOM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,62}$")


class NomDeCompteInvalide(ValueError):
    pass


def valider_nom(nom: str) -> str:
    if not MOTIF_NOM.match(nom or ""):
        raise NomDeCompteInvalide(
            "Nom de compte MQTT invalide : 2 à 63 caractères, lettres, chiffres, point, tiret "
            "ou souligné, commençant par une lettre ou un chiffre."
        )
    return nom


def hacher(mot_de_passe: str, sel: bytes | None = None, iterations: int = ITERATIONS) -> str:
    """Partie droite d'une ligne du fichier de mots de passe (après « utilisateur: »).

    `sel` n'est jamais fourni en production (tiré au hasard) — l'argument n'existe que pour
    rejouer le vecteur de référence dans les tests."""
    if sel is None:
        sel = os.urandom(LONGUEUR_SEL)
    empreinte = hashlib.pbkdf2_hmac(
        "sha512", (mot_de_passe or "").encode("utf-8"), sel, iterations, LONGUEUR_EMPREINTE,
    )
    return (
        f"$7${iterations}$"
        f"{base64.b64encode(sel).decode()}${base64.b64encode(empreinte).decode()}"
    )


def rendre_passwd(comptes) -> str:
    """Fichier `password_file`. `comptes` : itérable d'objets portant `nom` et `mot_de_passe`.

    Un compte sans mot de passe est ignoré plutôt qu'écrit avec une empreinte vide : une ligne
    malformée ferait refuser le fichier entier par le broker, donc couperait TOUS les comptes."""
    lignes = []
    for compte in comptes:
        if not compte.mot_de_passe:
            continue
        lignes.append(f"{valider_nom(compte.nom)}:{hacher(compte.mot_de_passe)}")
    return "\n".join(lignes) + ("\n" if lignes else "")


def rendre_acl(comptes, entete: str = "") -> str:
    """Fichier `acl_file`, un bloc par compte, chacun au minimum nécessaire.

    Les droits viennent du rôle, jamais d'une saisie libre : un champ « topic » libre dans
    l'interface web permettrait de s'accorder `#` en lecture, donc de lire tout le trafic."""
    from .models import RoleCompteMqtt

    morceaux = [entete] if entete else []
    for compte in comptes:
        nom = valider_nom(compte.nom)
        morceaux.append(f"\n# {compte.description or compte.get_role_display()}")
        morceaux.append(f"user {nom}")
        if compte.role == RoleCompteMqtt.SUPERVISION:
            # Statistiques du broker seulement : aucun message applicatif.
            morceaux.append("topic read $SYS/#")
        else:
            racine = compte.racine_topic.strip().rstrip("/")
            morceaux.append(f"topic readwrite {racine}/#")
    return "\n".join(morceaux) + "\n"


ENTETE_ACL = (
    "# Fichier ENGENDRÉ par Assista-Crise (core/mqtt_comptes.py) à chaque changement de compte.\n"
    "# Ne pas modifier à la main : la prochaine écriture écraserait la modification.\n"
    "# Les comptes s'administrent depuis /admin/comptes-mqtt."
)


def _ecrire_atomique(chemin: str, contenu: str) -> None:
    """Écriture par fichier temporaire puis renommage : le broker relit ces fichiers à tout
    moment (rechargement de configuration), il ne doit jamais en lire un à moitié écrit. Le
    renommage est atomique sur le même système de fichiers."""
    dossier = os.path.dirname(chemin)
    descripteur, temporaire = tempfile.mkstemp(dir=dossier, prefix=".tmp-")
    try:
        with os.fdopen(descripteur, "w") as fichier:
            fichier.write(contenu)
        # Lisible par le seul propriétaire : le fichier contient des empreintes de mots de passe.
        # 0640 et non 0600 : le broker tourne sous l'utilisateur `mosquitto`, pas sous celui du
        # backend -- le groupe commun du volume partagé lui donne la lecture.
        os.chmod(temporaire, 0o640)
        os.replace(temporaire, chemin)
    except Exception:
        os.unlink(temporaire)
        raise


def ecrire_fichiers(dossier: str | None = None) -> bool:
    """Réécrit `passwd` et `acl` depuis la base. Renvoie False sans rien faire si aucun dossier
    n'est configuré (dev, satellite : le broker y garde ses fichiers amorcés)."""
    from django.conf import settings

    from .models import CompteMqtt

    dossier = dossier or getattr(settings, "MQTT_COMPTES_DIR", "")
    if not dossier or not os.path.isdir(dossier):
        logger.info("MQTT_COMPTES_DIR absent ou non configuré : fichiers de comptes non réécrits.")
        return False

    comptes = list(CompteMqtt.objects.filter(actif=True))

    # Garde-fou : tant que les comptes d'infrastructure ne sont pas enregistrés en base, écrire
    # ces fichiers les SUPPRIMERAIT du broker -- l'exporteur de supervision et le pont
    # Meshtastic perdraient l'accès, sans aucune erreur visible. On préfère ne rien écrire et le
    # dire. `manage.py initialiser_comptes_mqtt` les enregistre depuis /run/secrets.
    if not any(compte.infrastructure for compte in comptes):
        logger.warning(
            "Aucun compte MQTT d'infrastructure en base : fichiers NON réécrits, pour ne pas "
            "couper l'exporteur et le pont. Lancer « manage.py initialiser_comptes_mqtt »."
        )
        return False

    _ecrire_atomique(os.path.join(dossier, "passwd"), rendre_passwd(comptes))
    _ecrire_atomique(os.path.join(dossier, "acl"), rendre_acl(comptes, entete=ENTETE_ACL))
    logger.info("Fichiers de comptes MQTT réécrits (%s compte(s) actif(s)).", len(comptes))
    return True
