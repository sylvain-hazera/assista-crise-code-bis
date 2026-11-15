"""Second facteur de connexion : code à usage unique (TOTP, RFC 6238) et codes de secours.

Décisions de Sylvain du 15/11/2026 :

- **obligatoire pour les comptes à pouvoir** (administrateur, autorité locale, secours,
  régulateur, membre de bureau, encadrant d'équipe), facultatif pour les autres ;
- **quinze jours** pour l'activer : pendant ce délai le site rappelle, après il n'ouvre plus
  de session sans activation ;
- **rien sur un satellite** : le secret n'y est pas copié, donc aucun code n'y est demandé.

Le calcul du code est écrit ici, sur la bibliothèque standard, plutôt que tiré d'un paquet :
c'est trente lignes, vérifiées contre les vecteurs de la RFC (voir les tests), et une
dépendance de moins dans le chemin de connexion.

Les comptes de service (ponts radio, satellites) sont des machines : ils n'ont pas de
téléphone, et un mot de passe tiré au hasard. Ils ne sont jamais « à pouvoir » ici.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone

PAS_SECONDES = 30
CHIFFRES = 6
# Un pas de tolérance de chaque côté : l'horloge d'un téléphone dérive, et l'on tape rarement
# un code dans la seconde où il s'affiche.
TOLERANCE_PAS = 1
DELAI_ACTIVATION = timedelta(days=15)
NOMBRE_CODES_SECOURS = 10
EMETTEUR = "Assista-Crise"


# ── Le code ──────────────────────────────────────────────────────────────────────────────────

def nouveau_secret() -> str:
    """160 bits, en base32 sans remplissage : ce qu'attendent les applications d'authentification."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def _cle(secret: str) -> bytes:
    propre = secret.strip().replace(" ", "").upper()
    return base64.b32decode(propre + "=" * (-len(propre) % 8))


def code_au_pas(secret: str, pas: int, chiffres: int = CHIFFRES) -> str:
    """Le code attendu pour un pas de 30 secondes donné (HOTP, RFC 4226, sur HMAC-SHA1)."""
    condense = hmac.new(_cle(secret), struct.pack(">Q", pas), hashlib.sha1).digest()
    decalage = condense[-1] & 0x0F
    valeur = struct.unpack(">I", condense[decalage:decalage + 4])[0] & 0x7FFFFFFF
    return str(valeur % (10 ** chiffres)).zfill(chiffres)


def pas_courant(instant: float | None = None) -> int:
    return int((time.time() if instant is None else instant) // PAS_SECONDES)


def pas_du_code(secret: str, code: str, apres_le_pas: int = 0, instant: float | None = None):
    """Le pas auquel ce code est valide, ou None.

    `apres_le_pas` : dernier pas déjà accepté pour ce secret. Un code de ce pas ou d'un pas
    antérieur est refusé — il a déjà servi."""
    code = "".join(c for c in (code or "") if c.isdigit())
    if len(code) != CHIFFRES:
        return None
    maintenant = pas_courant(instant)
    for pas in range(maintenant - TOLERANCE_PAS, maintenant + TOLERANCE_PAS + 1):
        if pas <= apres_le_pas:
            continue
        if hmac.compare_digest(code_au_pas(secret, pas), code):
            return pas
    return None


def adresse_otpauth(secret: str, email: str) -> str:
    """L'adresse que lit une application d'authentification (QR code ou lien direct)."""
    etiquette = quote(f"{EMETTEUR}:{email}")
    return (f"otpauth://totp/{etiquette}?secret={secret}&issuer={quote(EMETTEUR)}"
            f"&algorithm=SHA1&digits={CHIFFRES}&period={PAS_SECONDES}")


def qr_svg(texte: str) -> str:
    """Le QR code en SVG, fabriqué ici : le secret ne part vers aucun service de génération."""
    import io

    import qrcode
    import qrcode.image.svg

    image = qrcode.make(texte, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    tampon = io.BytesIO()
    image.save(tampon)
    return tampon.getvalue().decode("utf-8")


# ── Les codes de secours ─────────────────────────────────────────────────────────────────────

_ALPHABET_SECOURS = "abcdefghjkmnpqrstuvwxyz23456789"  # sans 0/o, 1/i/l : se recopie sans erreur


def _normaliser_secours(code: str) -> str:
    return "".join(c for c in (code or "").lower() if c in _ALPHABET_SECOURS)


def _empreinte_secours(utilisateur_id, code: str) -> str:
    message = f"code-secours|{utilisateur_id}|{_normaliser_secours(code)}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def renouveler_codes_secours(utilisateur) -> list[str]:
    """Remplace tous les codes de secours du compte et rend les nouveaux, EN CLAIR, une seule
    fois : seule leur empreinte est gardée."""
    from .models import CodeSecours

    CodeSecours.objects.filter(utilisateur=utilisateur).delete()
    codes = []
    for _ in range(NOMBRE_CODES_SECOURS):
        brut = "".join(secrets.choice(_ALPHABET_SECOURS) for _ in range(10))
        codes.append(f"{brut[:5]}-{brut[5:]}")
    CodeSecours.objects.bulk_create([
        CodeSecours(utilisateur=utilisateur, empreinte=_empreinte_secours(utilisateur.pk, code))
        for code in codes
    ])
    return codes


def _consommer_code_secours(utilisateur, code: str) -> bool:
    from .models import CodeSecours

    if len(_normaliser_secours(code)) != 10:
        return False
    # La mise à jour conditionnelle rend l'usage unique même si deux requêtes arrivent ensemble.
    return CodeSecours.objects.filter(
        utilisateur=utilisateur, empreinte=_empreinte_secours(utilisateur.pk, code),
        utilise_le__isnull=True,
    ).update(utilise_le=timezone.now()) == 1


# ── Qui est concerné ─────────────────────────────────────────────────────────────────────────

def applicable() -> bool:
    """Faux sur un satellite : le secret n'y est pas copié, aucun code n'y est demandé."""
    return not getattr(settings, "SATELLITE_ID", "")


def est_compte_de_service(utilisateur) -> bool:
    """Pont radio, satellite, ou tout compte marqué « machine » : pas de téléphone."""
    if getattr(utilisateur, "compte_service_pont", False) or getattr(utilisateur, "compte_machine", False):
        return True
    from .models import Satellite

    return Satellite.objects.filter(compte_service=utilisateur).exists()


def est_a_pouvoir(utilisateur) -> bool:
    """Le compte peut décider pour d'autres : son rôle, un bureau, ou l'encadrement d'une équipe.

    L'appartenance se lit dans `ContactInstitution`, jamais dans `User.institution` (voir
    `core/institution_courante.py`)."""
    from .models import ContactInstitution, Team, UserRole

    if utilisateur is None or not getattr(utilisateur, "pk", None):
        return False
    if est_compte_de_service(utilisateur):
        return False
    if utilisateur.is_superuser or utilisateur.is_staff:
        return True
    if utilisateur.type in (UserRole.ADMINISTRATOR, UserRole.LOCAL_AUTHORITY,
                            UserRole.ORGANIZED_RESCUE, UserRole.REGULATEUR):
        return True
    if ContactInstitution.objects.filter(
        utilisateur=utilisateur, actif=True, membre_bureau=True,
    ).exists():
        return True
    return Team.objects.filter(membres_encadrement=utilisateur).exists()


def second_facteur_actif(utilisateur):
    """Le `SecondFacteur` confirmé du compte, ou None. Toujours None sur un satellite."""
    from .models import SecondFacteur

    if not applicable() or utilisateur is None:
        return None
    return SecondFacteur.objects.filter(
        utilisateur=utilisateur, confirme_le__isnull=False,
    ).first()


def etat(utilisateur) -> dict:
    """Où en est ce compte : ce que le site affiche, et ce que la connexion applique.

    Pose la date limite la première fois qu'un compte à pouvoir est vu sans second facteur :
    c'est ce qui fait courir les quinze jours, pour les comptes existants comme pour celui qui
    devient encadrant demain."""
    if not applicable() or utilisateur is None or not getattr(utilisateur, "pk", None):
        return {"applicable": False, "actif": False, "requis": False,
                "date_limite": None, "bloquant": False, "codes_secours_restants": 0,
                "mot_de_passe_defini": False}

    actif = second_facteur_actif(utilisateur) is not None
    requis = est_a_pouvoir(utilisateur)
    date_limite = None
    if requis and not actif:
        if utilisateur.second_facteur_exige_le is None:
            utilisateur.second_facteur_exige_le = timezone.now() + DELAI_ACTIVATION
            type(utilisateur).objects.filter(pk=utilisateur.pk).update(
                second_facteur_exige_le=utilisateur.second_facteur_exige_le)
        date_limite = utilisateur.second_facteur_exige_le
    return {
        "applicable": True,
        "actif": actif,
        "requis": requis,
        "date_limite": date_limite,
        "bloquant": bool(date_limite and date_limite <= timezone.now()),
        "codes_secours_restants": (
            utilisateur.codes_secours.filter(utilise_le__isnull=True).count() if actif else 0),
        # Un compte créé par import se connecte par lien et n'a pas de mot de passe : le site
        # ne doit pas lui en redemander un pour activer son code.
        "mot_de_passe_defini": utilisateur.has_usable_password(),
    }


# ── Vérifier, activer, retirer ───────────────────────────────────────────────────────────────

def verifier_code(utilisateur, code: str) -> bool:
    """Vrai si `code` est le code du moment (jamais deux fois le même) ou un code de secours
    encore inutilisé. Ne compte aucun échec : c'est le rôle de `core/frein_connexion.py`."""
    from .models import SecondFacteur

    facteur = second_facteur_actif(utilisateur)
    if facteur is None:
        return False
    pas = pas_du_code(facteur.secret, code, apres_le_pas=facteur.dernier_pas)
    if pas is not None:
        # Conditionnelle : si deux requêtes présentent le même code, une seule passe.
        return SecondFacteur.objects.filter(
            pk=facteur.pk, dernier_pas__lt=pas).update(dernier_pas=pas) == 1
    return _consommer_code_secours(utilisateur, code)


def preparer(utilisateur) -> dict:
    """Tire un nouveau secret, pas encore actif, et rend de quoi le donner à l'application
    d'authentification. Refuse si un second facteur est déjà actif : il faut d'abord le
    retirer, ce qui demande un code."""
    from .models import SecondFacteur

    if second_facteur_actif(utilisateur) is not None:
        raise ValueError("Un second facteur est déjà actif sur ce compte.")
    SecondFacteur.objects.filter(utilisateur=utilisateur).delete()
    facteur = SecondFacteur.objects.create(utilisateur=utilisateur, secret=nouveau_secret())
    adresse = adresse_otpauth(facteur.secret, utilisateur.email)
    return {"secret": facteur.secret, "adresse": adresse, "qr_svg": qr_svg(adresse)}


def confirmer(utilisateur, code: str):
    """Active le second facteur préparé si `code` prouve que l'application le connaît.
    Rend les codes de secours (montrés cette seule fois), ou None si le code est faux."""
    from .models import SecondFacteur

    facteur = SecondFacteur.objects.filter(utilisateur=utilisateur, confirme_le__isnull=True).first()
    if facteur is None:
        return None
    pas = pas_du_code(facteur.secret, code)
    if pas is None:
        return None
    facteur.confirme_le = timezone.now()
    facteur.dernier_pas = pas
    facteur.save(update_fields=["confirme_le", "dernier_pas"])
    return renouveler_codes_secours(utilisateur)


def retirer(utilisateur, exiger_tout_de_suite: bool = False) -> bool:
    """Retire le second facteur et ses codes de secours. Vrai s'il y en avait un.

    `exiger_tout_de_suite` : pour un compte à pouvoir, la prochaine connexion devra en
    activer un nouveau sans nouveau délai de quinze jours (cas de la réinitialisation par un
    administrateur : le compte était déjà protégé, il ne redevient pas ouvert deux semaines)."""
    from .models import CodeSecours, SecondFacteur

    supprimes, _ = SecondFacteur.objects.filter(utilisateur=utilisateur).delete()
    CodeSecours.objects.filter(utilisateur=utilisateur).delete()
    if exiger_tout_de_suite and est_a_pouvoir(utilisateur):
        utilisateur.second_facteur_exige_le = timezone.now()
        type(utilisateur).objects.filter(pk=utilisateur.pk).update(
            second_facteur_exige_le=utilisateur.second_facteur_exige_le)
    return bool(supprimes)
