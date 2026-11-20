"""Notifications poussées vers les applications installées (Web Push), 20/11/2026.

Voir DOSSIER-PWA-INTERVENANTS.md, lot 4. Sur iPhone, une application web ne peut rien aller
chercher en arrière-plan : la seule façon de prévenir quelqu'un dont l'application est fermée est
la notification poussée, qui passe par le service du fabricant (Apple, Google, Mozilla). C'est la
seule exception au principe de core/notifications_application.py (« le téléphone vient
chercher »), et elle est tenue au plus court :

- le contenu est CHIFFRÉ DE BOUT EN BOUT pour le seul navigateur abonné (RFC 8291,
  « aes128gcm ») : le service du fabricant transporte des octets qu'il ne peut pas lire ;
- il ne porte que le titre de la notification et l'adresse de la page à ouvrir — jamais le
  corps, ni un nom de personne ; le détail se lit dans l'application, comme sur Android ;
- l'expéditeur est authentifié par une clé VAPID (RFC 8292), rangée en secret Docker
  (`vapid_prive`, PEM, courbe P-256), jamais en base ni dans le dépôt ;
- l'adresse d'envoi vient du navigateur : on n'appelle que les services de notification connus
  (`HOTES_AUTORISES`), en HTTPS, jamais une adresse quelconque (sinon le serveur deviendrait un
  relais vers n'importe où).

Écrit avec `cryptography`, sans bibliothèque de plus ; vérifié contre l'exemple de la RFC 8291
(annexe A) dans les essais.
"""
import base64
import json
import logging
import os
import struct
import time
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

#: Services de notification des navigateurs : Apple (Safari, iPhone, iPad), Google (Chrome,
#: Android), Mozilla (Firefox), Microsoft (Edge).
HOTES_AUTORISES = ("web.push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com",
                   "notify.windows.com")

#: Durée pendant laquelle le service garde un message pour un appareil éteint.
TTL_S = 24 * 3600
TAILLE_ENREGISTREMENT = 4096
DELAI_REPONSE_S = 15


class AbonnementRefuse(ValueError):
    pass


class AbonnementExpire(Exception):
    """Le service a répondu 404 ou 410 : cet abonnement n'existe plus, on l'oublie."""


def b64url(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode()


def depuis_b64url(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def valider_abonnement(abonnement) -> dict:
    """L'abonnement tel que le navigateur le donne (PushSubscription.toJSON()), vérifié :
    {"endpoint": "https://…", "keys": {"p256dh": …, "auth": …}}. Lève AbonnementRefuse."""
    if not isinstance(abonnement, dict):
        raise AbonnementRefuse("Abonnement illisible.")
    adresse = str(abonnement.get("endpoint") or "")
    cles = abonnement.get("keys") or {}
    url = urlparse(adresse)
    hote = (url.hostname or "").lower()
    if url.scheme != "https" or not any(hote == h or hote.endswith("." + h) for h in HOTES_AUTORISES):
        raise AbonnementRefuse("Service de notification inconnu.")
    try:
        p256dh, auth = depuis_b64url(str(cles["p256dh"])), depuis_b64url(str(cles["auth"]))
    except (KeyError, TypeError, ValueError):
        raise AbonnementRefuse("Clés de l'abonnement manquantes.")
    if len(p256dh) != 65 or p256dh[0] != 4 or len(auth) != 16:
        raise AbonnementRefuse("Clés de l'abonnement invalides.")
    return {"endpoint": adresse, "keys": {"p256dh": str(cles["p256dh"]), "auth": str(cles["auth"])}}


# ── Chiffrement du contenu (RFC 8291 et RFC 8188) ───────────────────────────────────────

def _hkdf(sel: bytes, ikm: bytes, info: bytes, longueur: int) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    return HKDF(algorithm=hashes.SHA256(), length=longueur, salt=sel, info=info).derive(ikm)


def chiffrer(contenu: bytes, p256dh: bytes, auth: bytes, *, cle_ephemere=None, sel: bytes = None) -> bytes:
    """Le corps de la requête, « aes128gcm » : en-tête (sel, taille, clé publique éphémère) puis
    un unique enregistrement chiffré. `cle_ephemere` et `sel` ne se donnent que dans les essais."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    if len(contenu) > TAILLE_ENREGISTREMENT - 17 - 16 - 86:
        raise ValueError("Contenu trop long pour une notification.")
    cle_ephemere = cle_ephemere or ec.generate_private_key(ec.SECP256R1())
    sel = sel or os.urandom(16)
    publique_ephemere = cle_ephemere.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    cle_navigateur = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)
    secret_partage = cle_ephemere.exchange(ec.ECDH(), cle_navigateur)

    ikm = _hkdf(auth, secret_partage, b"WebPush: info\x00" + p256dh + publique_ephemere, 32)
    cle_contenu = _hkdf(sel, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(sel, ikm, b"Content-Encoding: nonce\x00", 12)
    # Un seul enregistrement, le dernier : délimiteur 0x02, sans bourrage.
    chiffre = AESGCM(cle_contenu).encrypt(nonce, contenu + b"\x02", None)
    entete = sel + struct.pack(">I", TAILLE_ENREGISTREMENT) + bytes([len(publique_ephemere)]) + publique_ephemere
    return entete + chiffre


# ── Authentification de l'expéditeur (VAPID, RFC 8292) ──────────────────────────────────

def _chemin_cle() -> Path:
    return Path(os.environ.get("VAPID_PRIVE_FILE", "/run/secrets/vapid_prive"))


def cle_privee():
    """La clé VAPID (P-256), ou None si le secret n'est pas posé : les notifications poussées
    sont alors simplement absentes, le reste marche."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    chemin = _chemin_cle()
    try:
        return load_pem_private_key(chemin.read_bytes(), password=None)
    except (OSError, ValueError):
        return None


def cle_publique_b64url(cle=None):
    """La clé publique à donner au navigateur (applicationServerKey), ou None."""
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    cle = cle or cle_privee()
    if cle is None:
        return None
    return b64url(cle.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint))


def entete_vapid(adresse: str, cle, contact: str, maintenant: float = None) -> str:
    """« vapid t=<jeton ES256>, k=<clé publique> » pour l'origine du service appelé."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    url = urlparse(adresse)
    revendications = {"aud": f"{url.scheme}://{url.netloc}",
                      "exp": int((maintenant or time.time()) + 12 * 3600), "sub": contact}
    signe = (b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode()) + "."
             + b64url(json.dumps(revendications, separators=(",", ":")).encode()))
    r, s = decode_dss_signature(cle.sign(signe.encode(), ec.ECDSA(hashes.SHA256())))
    jeton = signe + "." + b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={jeton}, k={cle_publique_b64url(cle)}"


# ── Envoi ───────────────────────────────────────────────────────────────────────────────

def envoyer(abonnement: dict, message: dict, *, urgent: bool = False, contact: str = "https://www.assista-crise.fr",
            cle=None, poster=None) -> int:
    """Envoie `message` (petit dictionnaire JSON) à un abonnement. Rend le statut HTTP.
    Lève AbonnementExpire sur 404/410, AbonnementRefuse sur un abonnement douteux."""
    import requests

    abonnement = valider_abonnement(abonnement)
    cle = cle or cle_privee()
    if cle is None:
        raise RuntimeError("Clé VAPID absente : notifications poussées désactivées.")
    corps = chiffrer(json.dumps(message, ensure_ascii=False).encode(),
                     depuis_b64url(abonnement["keys"]["p256dh"]), depuis_b64url(abonnement["keys"]["auth"]))
    entetes = {
        "Authorization": entete_vapid(abonnement["endpoint"], cle, contact),
        "Content-Encoding": "aes128gcm", "Content-Type": "application/octet-stream",
        "TTL": str(TTL_S), "Urgency": "high" if urgent else "normal",
    }
    reponse = (poster or requests.post)(abonnement["endpoint"], data=corps, headers=entetes,
                                         timeout=DELAI_REPONSE_S, allow_redirects=False)
    if reponse.status_code in (404, 410):
        raise AbonnementExpire(reponse.status_code)
    if reponse.status_code >= 400:
        logger.warning("Notification poussée refusée par %s : %s", urlparse(abonnement["endpoint"]).hostname,
                       reponse.status_code)
    return reponse.status_code
