"""Frein à la force brute, PAR COMPTE et non par adresse IP.

Avant le 15/11/2026 la seule limite était celle du proxy : dix tentatives par minute et par
adresse IP. Rien ne plafonnait une attaque venant de mille adresses sur un même compte, et
soixante mots de passe faux d'affilée sur un compte donnaient soixante refus sans le moindre
ralentissement.

Règles :

- **cinq échecs sans délai**, puis un délai qui double à chaque nouvel échec, plafonné à
  quinze minutes ;
- **jamais de verrouillage définitif** : un compte de maire ne doit pas pouvoir être fermé de
  l'extérieur en pleine crise. Au pire, un inconnu obtient un essai par quart d'heure ;
- **un appareil déjà connu du compte a son propre compteur** (`AppareilConnu`) : les échecs
  d'un attaquant ne ralentissent que les appareils inconnus, pas le titulaire sur son poste ;
- **une adresse inconnue est freinée comme les autres**, sinon le frein dirait qui est inscrit ;
- le compteur s'efface après un jour sans échec, ou à la première réussite.

Rien n'est stocké en clair : la clé d'un compteur est une empreinte de l'étape, de l'adresse
saisie et de l'appareil.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db.models import F
from django.utils import timezone

ETAPE_MOT_DE_PASSE = "mot-de-passe"
ETAPE_CODE = "code"

ECHECS_SANS_DELAI = 5
DELAIS_SECONDES = (30, 60, 120, 300, 600, 900)
OUBLI = timedelta(hours=24)
APPAREILS_GARDES = 20


def _hmac(texte: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), texte.encode(), hashlib.sha256).hexdigest()


def empreinte_appareil(jeton: str) -> str:
    return hashlib.sha256((jeton or "").encode()).hexdigest()


def appareil_connu(utilisateur, jeton: str) -> bool:
    from .models import AppareilConnu

    if utilisateur is None or not jeton or len(jeton) < 32:
        return False
    return AppareilConnu.objects.filter(
        utilisateur=utilisateur, empreinte=empreinte_appareil(jeton)).exists()


def cle(etape: str, email: str, utilisateur=None, appareil: str = "", voie: str = "") -> str:
    """La clé du compteur. Avec un appareil connu de ce compte, c'est le compteur de cet
    appareil ; sinon, celui que se partagent tous les appareils inconnus.

    `voie` isole un compteur de plus : celui des essais faits APRÈS une étape déjà franchie
    (le mot de passe de qui a donné le bon code)."""
    adresse = (email or "").strip().lower()
    suffixe = empreinte_appareil(appareil) if appareil_connu(utilisateur, appareil) else ""
    return _hmac(f"frein|{etape}|{adresse}|{suffixe}|{voie}")


def attente(cle_compteur: str) -> int:
    """Secondes à attendre avant le prochain essai (0 = on peut essayer)."""
    from .models import FreinConnexion

    compteur = FreinConnexion.objects.filter(cle=cle_compteur).first()
    if compteur is None or compteur.bloque_jusqua is None:
        return 0
    reste = (compteur.bloque_jusqua - timezone.now()).total_seconds()
    return max(0, int(reste) + (1 if reste > int(reste) else 0))


def echec(cle_compteur: str) -> int:
    """Compte un échec. Rend les secondes d'attente qui en résultent."""
    from .models import FreinConnexion

    maintenant = timezone.now()
    compteur, _ = FreinConnexion.objects.get_or_create(cle=cle_compteur)
    if compteur.dernier_echec and maintenant - compteur.dernier_echec > OUBLI:
        FreinConnexion.objects.filter(pk=compteur.pk).update(echecs=0, bloque_jusqua=None)
    FreinConnexion.objects.filter(pk=compteur.pk).update(
        echecs=F("echecs") + 1, dernier_echec=maintenant)
    compteur.refresh_from_db()

    au_dela = compteur.echecs - ECHECS_SANS_DELAI
    if au_dela <= 0:
        return 0
    delai = DELAIS_SECONDES[min(au_dela, len(DELAIS_SECONDES)) - 1]
    FreinConnexion.objects.filter(pk=compteur.pk).update(
        bloque_jusqua=maintenant + timedelta(seconds=delai))
    try:
        from .metrics import CONNEXIONS_FREINEES
        CONNEXIONS_FREINEES.inc()
    except Exception:  # la mesure ne doit jamais empêcher de freiner
        pass
    return delai


def reussite(cle_compteur: str) -> None:
    from .models import FreinConnexion

    FreinConnexion.objects.filter(cle=cle_compteur).delete()


def purger() -> int:
    """Efface les compteurs oubliés. Appelé au fil de l'eau : la table reste petite."""
    from .models import FreinConnexion

    supprimes, _ = FreinConnexion.objects.filter(
        dernier_echec__lt=timezone.now() - OUBLI).delete()
    return supprimes


# ── Appareils connus ─────────────────────────────────────────────────────────────────────────

def libelle_appareil(agent: str) -> str:
    """« Chrome sur Android » : assez pour que le titulaire reconnaisse son appareil, trop peu
    pour le pister. L'en-tête complet n'est pas gardé."""
    agent = agent or ""
    if "ReserveResilience" in agent or "okhttp" in agent.lower() or "ktor" in agent.lower():
        navigateur = "Application mobile"
    elif "Edg/" in agent:
        navigateur = "Edge"
    elif "Firefox/" in agent:
        navigateur = "Firefox"
    elif "Chrome/" in agent:
        navigateur = "Chrome"
    elif "Safari/" in agent:
        navigateur = "Safari"
    else:
        navigateur = "Navigateur"
    if "Android" in agent:
        systeme = "Android"
    elif "iPhone" in agent or "iPad" in agent:
        systeme = "iPhone ou iPad"
    elif "Windows" in agent:
        systeme = "Windows"
    elif "Mac OS X" in agent:
        systeme = "Mac"
    elif "Linux" in agent:
        systeme = "Linux"
    else:
        systeme = ""
    return f"{navigateur} sur {systeme}" if systeme else navigateur


def retenir_appareil(utilisateur, jeton: str, agent: str = "") -> tuple[str, bool]:
    """Après une connexion RÉUSSIE : retient l'appareil. Rend `(jeton, nouveau)`.

    `jeton` : celui que l'appareil a présenté, s'il en a un assez long ; sinon on lui en tire
    un. Le même jeton peut être connu de plusieurs comptes (un poste partagé en mairie) : la
    reconnaissance porte sur la paire (compte, appareil)."""
    from .models import AppareilConnu

    if not jeton or len(jeton) < 32 or len(jeton) > 200:
        jeton = secrets.token_urlsafe(32)
    appareil, nouveau = AppareilConnu.objects.get_or_create(
        utilisateur=utilisateur, empreinte=empreinte_appareil(jeton),
        defaults={"libelle": libelle_appareil(agent)},
    )
    if not nouveau:
        appareil.save(update_fields=["dernier_usage"])
    else:
        anciens = list(AppareilConnu.objects.filter(utilisateur=utilisateur)
                       .order_by("-dernier_usage").values_list("pk", flat=True)[APPAREILS_GARDES:])
        if anciens:
            AppareilConnu.objects.filter(pk__in=anciens).delete()
    return jeton, nouveau
