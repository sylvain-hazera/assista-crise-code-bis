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

# Mode « code par e-mail » : le central envoie un code à chaque connexion.
VALIDITE_CODE_MAIL = timedelta(minutes=5)
ESSAIS_CODE_MAIL = 5
# Entre deux envois à un même compte : sans cela, connaître une adresse suffirait à inonder
# une boîte aux lettres. Le frein (`core/frein_connexion.py`) borne en plus le nombre par jour.
DELAI_ENTRE_ENVOIS = timedelta(seconds=60)
ETAPE_ENVOI = "envoi-code"


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


# ── Le code envoyé par e-mail ────────────────────────────────────────────────────────────────
#
# Deux usages :
#
# - **mode e-mail** : le compte n'a pas d'application d'authentification, son code part tout
#   seul dès que l'adresse est saisie ;
# - **à la demande** (15/11/2026) : un compte protégé par une application peut AUSSI se faire
#   envoyer un code, en le demandant (« Recevoir un code par e-mail »). Téléphone oublié, perdu,
#   déchargé : on n'est pas enfermé dehors, et les dix codes de secours restent pour le jour où
#   la boîte aux lettres est elle aussi hors d'atteinte.
#
# Ce que cela protège : la force brute et le mot de passe fuité. Ce que cela ne protège PAS :
# quelqu'un qui lit la boîte aux lettres du titulaire — celui-là peut réinitialiser le mot de
# passe par e-mail, puis recevoir le code. Depuis que le code à la demande existe, c'est vrai
# de TOUS les comptes, y compris ceux qui ont une application : la sécurité d'un compte est
# celle de sa boîte aux lettres. C'est un choix (être dépanné sans administrateur), pas un oubli.
#
# Deux garde-fous restent : un code reçu par e-mail ne dispense jamais du mot de passe, et il
# ne complète jamais un LIEN reçu par e-mail (voir `core/connexion.py`) — le lien et le code
# arriveraient dans la même boîte et ne feraient qu'un seul facteur.

def _empreinte_code_mail(utilisateur_id, code: str) -> str:
    chiffres = "".join(c for c in (code or "") if c.isdigit())
    message = f"code-mail|{utilisateur_id}|{chiffres}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def masquer_adresse(email: str) -> str:
    """« c•••••@exemple.fr » : assez pour reconnaître sa boîte, pas pour l'apprendre."""
    nom, _, domaine = (email or "").partition("@")
    return f"{nom[:1]}{'•' * max(3, len(nom) - 1)}@{domaine}" if domaine else "votre adresse"


def envoyer_code_par_mail(request, utilisateur, facteur=None, appareil: str = "",
                          a_la_demande: bool = False) -> bool:
    """Tire un code, valable cinq minutes, et l'envoie à l'adresse du compte. Rend vrai s'il
    est parti.

    Sans `a_la_demande`, seul un compte en mode e-mail en reçoit un : c'est l'envoi automatique,
    à la saisie de l'adresse. Avec, tout compte protégé en reçoit un : c'est la personne qui le
    demande. Rien ne part si un envoi vient d'avoir lieu.

    Le code ne figure ni dans l'objet du message (qui est journalisé), ni en base (où seule
    son empreinte est gardée) : il n'existe en clair que dans le message lui-même."""
    from . import frein_connexion as frein
    from .audit import send_mail_logged
    from .branding import branding_for_institution
    from .models import SecondFacteur

    facteur = facteur or SecondFacteur.objects.filter(utilisateur=utilisateur).first()
    if facteur is None:
        return False
    if facteur.mode != SecondFacteur.MODE_EMAIL and (not a_la_demande or facteur.confirme_le is None):
        # Application d'authentification : jamais d'envoi spontané, et rien tant qu'elle
        # n'est pas activée (l'activation prouve que l'application connaît le secret).
        return False
    maintenant = timezone.now()
    if facteur.code_mail_envoye_le and maintenant - facteur.code_mail_envoye_le < DELAI_ENTRE_ENVOIS:
        return False
    # Un appareil déjà connu du compte a son propre quota d'envois, comme il a son propre
    # compteur d'échecs : quelqu'un qui saisit l'adresse du titulaire en boucle épuise le
    # quota des inconnus, pas celui du titulaire sur son poste.
    compteur = frein.cle(ETAPE_ENVOI, utilisateur.email, utilisateur, appareil)
    if frein.attente(compteur):
        return False
    frein.echec(compteur)

    code = f"{secrets.randbelow(10 ** CHIFFRES):0{CHIFFRES}d}"
    SecondFacteur.objects.filter(pk=facteur.pk).update(
        code_mail_empreinte=_empreinte_code_mail(utilisateur.pk, code),
        code_mail_expire_le=maintenant + VALIDITE_CODE_MAIL,
        code_mail_essais=0,
        code_mail_envoye_le=maintenant,
    )
    nom = branding_for_institution(getattr(utilisateur, "institution", None)).nom_affichage
    try:
        send_mail_logged(
            request,
            subject=f"Votre code de connexion {nom}",
            message=(
                f"Bonjour {utilisateur.first_name},\n\n"
                f"Votre code de connexion : {code[:3]} {code[3:]}\n\n"
                "Il est valable 5 minutes et ne sert qu'une fois.\n\n"
                "Vous n'êtes pas en train de vous connecter ? Quelqu'un a saisi votre adresse. "
                "Ne communiquez ce code à personne ; sans lui, on ne peut pas entrer. Si cela "
                "se répète, prévenez un administrateur."
            ),
            from_email=None, recipient_list=[utilisateur.email], fail_silently=False,
        )
    except Exception:
        # L'échec est déjà journalisé et remonté par send_mail_logged. Le code tiré ne sert
        # à personne : on l'efface, et la personne pourra en redemander un tout de suite.
        SecondFacteur.objects.filter(pk=facteur.pk).update(
            code_mail_empreinte="", code_mail_expire_le=None, code_mail_envoye_le=None)
        return False
    return True


def _verifier_code_mail(facteur, code: str) -> bool:
    """Vrai si `code` est le code envoyé, encore valable. Il ne sert qu'une fois, et cinq
    essais ratés l'annulent : il faut alors en demander un autre."""
    from django.db.models import F

    from .models import SecondFacteur

    if (not facteur.code_mail_empreinte or facteur.code_mail_expire_le is None
            or facteur.code_mail_expire_le <= timezone.now()
            or facteur.code_mail_essais >= ESSAIS_CODE_MAIL):
        return False
    if len("".join(c for c in (code or "") if c.isdigit())) != CHIFFRES:
        return False
    attendu = facteur.code_mail_empreinte
    if hmac.compare_digest(_empreinte_code_mail(facteur.utilisateur_id, code), attendu):
        # Conditionnelle : si deux requêtes présentent le même code, une seule passe.
        return SecondFacteur.objects.filter(pk=facteur.pk, code_mail_empreinte=attendu).update(
            code_mail_empreinte="", code_mail_expire_le=None, code_mail_envoye_le=None) == 1
    SecondFacteur.objects.filter(pk=facteur.pk).update(code_mail_essais=F("code_mail_essais") + 1)
    return False


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
        return {"applicable": False, "actif": False, "requis": False, "mode": None,
                "date_limite": None, "bloquant": False, "codes_secours_restants": 0,
                "mot_de_passe_defini": False}

    facteur = second_facteur_actif(utilisateur)
    actif = facteur is not None
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
        # « application » ou « email » : d'où vient le code de ce compte.
        "mode": facteur.mode.lower() if actif else None,
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

def verifier_code(utilisateur, code: str, accepter_mail: bool = True) -> bool:
    """Vrai si `code` est le code du moment de l'application (jamais deux fois le même), le
    code envoyé par e-mail s'il y en a un en cours, ou un code de secours encore inutilisé.
    Ne compte aucun échec : c'est le rôle de `core/frein_connexion.py`.

    `accepter_mail=False` : là où un code reçu par e-mail ne prouverait rien de plus que ce
    qui a déjà été prouvé (session ouverte par un lien reçu dans la même boîte)."""
    from .models import SecondFacteur

    facteur = second_facteur_actif(utilisateur)
    if facteur is None:
        return False
    if facteur.mode == SecondFacteur.MODE_EMAIL:
        return _verifier_code_mail(facteur, code) or _consommer_code_secours(utilisateur, code)
    pas = pas_du_code(facteur.secret, code, apres_le_pas=facteur.dernier_pas)
    if pas is not None:
        # Conditionnelle : si deux requêtes présentent le même code, une seule passe.
        return SecondFacteur.objects.filter(
            pk=facteur.pk, dernier_pas__lt=pas).update(dernier_pas=pas) == 1
    if accepter_mail and _verifier_code_mail(facteur, code):
        return True
    return _consommer_code_secours(utilisateur, code)


class ModeImpossible(ValueError):
    """Ce compte ne peut pas choisir ce mode. Le message dit pourquoi, pour le titulaire."""


def preparer(utilisateur, mode: str = "application", request=None) -> dict:
    """Prépare un second facteur, pas encore actif.

    - `application` : tire un secret et rend de quoi le donner à l'application
      d'authentification (QR code, lien, clé à recopier) ;
    - `email` : envoie un premier code à l'adresse du compte. Le saisir prouvera que la boîte
      aux lettres est bien lue par le titulaire.

    Refuse si un second facteur est déjà actif : il faut d'abord le retirer, ce qui demande
    un code."""
    from .models import SecondFacteur

    if second_facteur_actif(utilisateur) is not None:
        raise ValueError("Un second facteur est déjà actif sur ce compte.")

    if mode == "email":
        # Le code arrive là où arrivent aussi les liens de connexion et de réinitialisation.
        # Sans mot de passe, tout tiendrait à la seule boîte aux lettres : un seul facteur.
        if not utilisateur.has_usable_password():
            raise ModeImpossible(
                "Le code par e-mail demande que votre compte ait un mot de passe. "
                "Choisissez-en un d'abord, ou utilisez une application d'authentification.")
        SecondFacteur.objects.filter(utilisateur=utilisateur).delete()
        facteur = SecondFacteur.objects.create(
            utilisateur=utilisateur, secret="", mode=SecondFacteur.MODE_EMAIL)
        if not envoyer_code_par_mail(request, utilisateur, facteur):
            SecondFacteur.objects.filter(pk=facteur.pk).delete()
            raise ModeImpossible(
                "Le code n'a pas pu être envoyé. Attendez une minute et réessayez.")
        return {"mode": "email", "adresse": masquer_adresse(utilisateur.email)}

    SecondFacteur.objects.filter(utilisateur=utilisateur).delete()
    facteur = SecondFacteur.objects.create(utilisateur=utilisateur, secret=nouveau_secret())
    adresse = adresse_otpauth(facteur.secret, utilisateur.email)
    return {"mode": "application", "secret": facteur.secret, "adresse": adresse,
            "qr_svg": qr_svg(adresse)}


def confirmer(utilisateur, code: str):
    """Active le second facteur préparé si `code` prouve que le titulaire le maîtrise : son
    application connaît le secret, ou il lit bien sa boîte aux lettres.
    Rend les codes de secours (montrés cette seule fois), ou None si le code est faux."""
    from .models import SecondFacteur

    facteur = SecondFacteur.objects.filter(utilisateur=utilisateur, confirme_le__isnull=True).first()
    if facteur is None:
        return None
    if facteur.mode == SecondFacteur.MODE_EMAIL:
        if not _verifier_code_mail(facteur, code):
            return None
        pas = 0
    else:
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
