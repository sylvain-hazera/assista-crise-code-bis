"""Ouverture de session : le seul endroit qui délivre des jetons à une personne.

Parcours voulu par Sylvain (15/11/2026) pour un compte protégé par un second facteur :
**adresse, puis code, puis mot de passe**. Tant que le code n'a pas été donné, le serveur ne
regarde même pas le mot de passe : un mot de passe fuité seul ne permet ni d'entrer, ni de
savoir s'il est encore bon.

Ce module sert tous les chemins qui ouvraient une session : mot de passe (`/api/token/`), lien
magique, lien d'activation. Avant lui, chacun fabriquait ses jetons de son côté, et un second
facteur posé sur le seul mot de passe aurait été contourné par un simple lien reçu par e-mail.
"""
import hashlib
import hmac

from django.conf import settings
from django.core import signing
from rest_framework import status
from rest_framework.exceptions import APIException, AuthenticationFailed

from . import frein_connexion as frein
from . import second_facteur

SEL_ETAPE = "assista.connexion.code-verifie"
SEL_ENROLEMENT = "assista.connexion.enrolement"
VALIDITE_ETAPE_S = 5 * 60
VALIDITE_ENROLEMENT_S = 15 * 60

MESSAGE_REFUS = "Identifiants incorrects."
CODE_REQUIS = "CODE_REQUIS"
A_ACTIVER = "SECOND_FACTEUR_A_ACTIVER"


class SecondFacteurAActiver(APIException):
    """Le délai est passé : la personne a prouvé qui elle est, mais aucune session ne s'ouvre
    tant qu'elle n'a pas activé son second facteur. Elle reçoit de quoi le faire, et rien
    d'autre."""
    status_code = status.HTTP_403_FORBIDDEN
    default_code = A_ACTIVER

    def __init__(self, utilisateur):
        super().__init__({
            "code": A_ACTIVER,
            "detail": ("Votre compte doit être protégé par un code de sécurité. "
                       "Activez-le pour continuer."),
            "jeton_enrolement": signing.dumps({"u": str(utilisateur.pk)}, salt=SEL_ENROLEMENT),
        })


class CodeRequis(APIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = CODE_REQUIS

    def __init__(self, detail="Saisissez le code de votre application d'authentification."):
        super().__init__({"code": CODE_REQUIS, "detail": detail})


class TropDEssais(APIException):
    """Le frein est serré : rien n'est examiné avant `attendre` secondes."""
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_code = "TROP_D_ESSAIS"

    def __init__(self, attendre: int):
        minutes = max(1, round(attendre / 60))
        delai = f"{attendre} secondes" if attendre < 90 else f"{minutes} minutes"
        super().__init__({
            "code": "TROP_D_ESSAIS",
            "detail": f"Trop d'essais. Réessayez dans {delai}.",
            "attendre": attendre,
        })


def trouver_utilisateur(email: str):
    """Le compte actif de cette adresse, ou None. Par l'index aveugle : l'e-mail est chiffré."""
    from .crypto_fields import blind_index
    from .models import User

    adresse = (email or "").strip()
    if not adresse:
        return None
    return User.objects.filter(email_bidx=blind_index(adresse), is_active=True).first()


def _compter_echec(etape: str) -> None:
    try:
        from .metrics import CONNEXIONS_ECHOUEES
        CONNEXIONS_ECHOUEES.labels(etape=etape).inc()
    except Exception:
        pass


def exiger_libre(cle_compteur: str) -> None:
    reste = frein.attente(cle_compteur)
    if reste:
        raise TropDEssais(reste)


# ── Étape 1 : l'adresse ──────────────────────────────────────────────────────────────────────

def etape_apres_adresse(email: str) -> str:
    """« code » ou « mot_de_passe » : ce que le site demande ensuite.

    Répondre « code » aux seuls comptes protégés dirait à n'importe qui lesquels le sont, donc
    lesquels ont du pouvoir. Une adresse sur huit qui ne correspond à rien reçoit la même
    réponse, toujours la même pour une adresse donnée : « code » ne prouve plus rien."""
    utilisateur = trouver_utilisateur(email)
    if utilisateur is not None:
        return "code" if second_facteur.second_facteur_actif(utilisateur) else "mot_de_passe"
    if not second_facteur.applicable():
        return "mot_de_passe"
    empreinte = hmac.new(settings.SECRET_KEY.encode(),
                         f"etape|{(email or '').strip().lower()}".encode(),
                         hashlib.sha256).digest()
    return "code" if empreinte[0] < 32 else "mot_de_passe"


# ── Étape 2 : le code ────────────────────────────────────────────────────────────────────────

def verifier_code_de_connexion(email: str, code: str, appareil: str = "") -> str:
    """Rend un jeton d'étape (cinq minutes) si le code est bon. Sinon lève, avec la même
    réponse que l'adresse existe ou non."""
    utilisateur = trouver_utilisateur(email)
    compteur = frein.cle(frein.ETAPE_CODE, email, utilisateur, appareil)
    exiger_libre(compteur)
    if utilisateur is None or not second_facteur.verifier_code(utilisateur, code):
        _compter_echec(frein.ETAPE_CODE)
        reste = frein.echec(compteur)
        if reste:
            raise TropDEssais(reste)
        raise AuthenticationFailed("Code incorrect.")
    frein.reussite(compteur)
    return signing.dumps({"u": str(utilisateur.pk)}, salt=SEL_ETAPE)


def _jeton_valide(jeton: str, utilisateur, sel: str, validite: int) -> bool:
    if not jeton:
        return False
    try:
        contenu = signing.loads(jeton, salt=sel, max_age=validite)
    except signing.BadSignature:
        return False
    return contenu.get("u") == str(utilisateur.pk)


def code_deja_verifie(jeton_etape: str, utilisateur) -> bool:
    return _jeton_valide(jeton_etape, utilisateur, SEL_ETAPE, VALIDITE_ETAPE_S)


def utilisateur_a_enroler(jeton_enrolement: str):
    """Le compte qu'autorise ce jeton d'activation, ou None."""
    from .models import User

    try:
        contenu = signing.loads(jeton_enrolement or "", salt=SEL_ENROLEMENT,
                                max_age=VALIDITE_ENROLEMENT_S)
    except signing.BadSignature:
        return None
    return User.objects.filter(pk=contenu.get("u"), is_active=True).first()


# ── Étape 3 : le mot de passe ────────────────────────────────────────────────────────────────

def avant_mot_de_passe(email: str, jeton_etape: str, appareil: str = ""):
    """À appeler AVANT de regarder le mot de passe. Rend `(utilisateur ou None, clé du compteur)`.

    Lève si le compte est freiné, ou s'il est protégé par un code qui n'a pas été donné —
    avec le message d'un mot de passe faux, et sans que le mot de passe ait été examiné."""
    utilisateur = trouver_utilisateur(email)
    protege = utilisateur is not None and second_facteur.second_facteur_actif(utilisateur)
    if protege and code_deja_verifie(jeton_etape, utilisateur):
        # Qui a donné le bon code a son propre compteur : les essais sans code d'un inconnu ne
        # peuvent pas le ralentir, même s'il se connecte depuis un appareil neuf.
        compteur = frein.cle(frein.ETAPE_MOT_DE_PASSE, email, utilisateur, appareil,
                             voie="code-verifie")
        exiger_libre(compteur)
        return utilisateur, compteur
    compteur = frein.cle(frein.ETAPE_MOT_DE_PASSE, email, utilisateur, appareil)
    exiger_libre(compteur)
    if protege:
        echec_mot_de_passe(compteur)
    return utilisateur, compteur


def echec_mot_de_passe(compteur: str):
    """Compte l'échec et lève le refus (ou l'attente, si le frein vient de se serrer)."""
    _compter_echec(frein.ETAPE_MOT_DE_PASSE)
    reste = frein.echec(compteur)
    if reste:
        raise TropDEssais(reste)
    raise AuthenticationFailed(MESSAGE_REFUS)


# ── Délivrer la session ──────────────────────────────────────────────────────────────────────

def ouvrir_session(request, utilisateur, appareil: str = "", fiche_avec_requete: bool = True) -> dict:
    """Les jetons de session de `utilisateur`, qui vient de prouver qui il est.

    Lève `SecondFacteurAActiver` si le compte est à pouvoir, sans second facteur, et que ses
    quinze jours sont passés.

    `fiche_avec_requete=False` : la fiche du compte est rendue sans la requête, comme la
    connexion par mot de passe l'a toujours fait. Avec la requête, `UserSerializer` applique le
    masquage de la zone DEMO — et, la personne n'étant pas encore « connectée » au sens de la
    requête, il lui rendrait SON PROPRE nom sous pseudonyme si son navigateur était resté en
    zone de démonstration."""
    from django.contrib.auth.models import update_last_login
    from rest_framework_simplejwt.settings import api_settings as reglages_jwt
    from rest_framework_simplejwt.tokens import RefreshToken

    from .serializers import UserSerializer

    etat = second_facteur.etat(utilisateur)
    if etat["bloquant"]:
        raise SecondFacteurAActiver(utilisateur)

    agent = request.META.get("HTTP_USER_AGENT", "") if request is not None else ""
    appareil, nouveau = frein.retenir_appareil(utilisateur, appareil, agent)
    rafraichissement = RefreshToken.for_user(utilisateur)
    if reglages_jwt.UPDATE_LAST_LOGIN:
        update_last_login(None, utilisateur)
    contexte = {"pour_soi": True}
    if fiche_avec_requete:
        contexte["request"] = request
    return {
        "refresh": str(rafraichissement),
        "access": str(rafraichissement.access_token),
        "user": UserSerializer(utilisateur, context=contexte).data,
        "appareil": appareil,
        "appareil_nouveau": nouveau,
    }


def ouvrir_session_par_lien(request, utilisateur, code: str = "", appareil: str = "") -> dict:
    """Session ouverte par un lien reçu par e-mail (lien magique, lien d'activation).

    Le lien prouve l'accès à la boîte aux lettres : c'est UN facteur. Si le compte est protégé,
    il faut aussi le code — sinon lire les e-mails de quelqu'un suffirait à entrer chez lui."""
    if second_facteur.second_facteur_actif(utilisateur):
        if not code:
            raise CodeRequis()
        compteur = frein.cle(frein.ETAPE_CODE, utilisateur.email, utilisateur, appareil)
        exiger_libre(compteur)
        if not second_facteur.verifier_code(utilisateur, code):
            _compter_echec(frein.ETAPE_CODE)
            reste = frein.echec(compteur)
            if reste:
                raise TropDEssais(reste)
            raise CodeRequis("Code incorrect.")
        frein.reussite(compteur)
    return ouvrir_session(request, utilisateur, appareil)


def session_encore_permise(utilisateur) -> bool:
    """Au renouvellement d'une session : faux si le compte aurait dû activer son second facteur
    et ne l'a pas fait. La session s'arrête alors à l'expiration de son jeton d'accès."""
    return not second_facteur.etat(utilisateur)["bloquant"]
