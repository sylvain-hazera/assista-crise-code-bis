"""Création de compte : arrêter les robots sans rien demander aux personnes (16/11/2026).

Demande de Sylvain : « un challenge facile pour des humains en temps de crise mais qui bloque
les robots ». Avant, l'inscription n'avait ni contrôle ni limite propre, alors qu'un compte de
particulier est actif aussitôt et reçoit un e-mail de bienvenue : un robot pouvait créer des
comptes en série et faire écrire le site à des adresses qui n'avaient rien demandé.

**Aucune énigme à lire.** Un captcha visible échoue justement quand on en a besoin : téléphone,
mains qui tremblent, réseau faible, lecteur d'écran. Et aucun service tiers : rien ne part chez
Google ou Cloudflare.

Le principe :

1. le serveur donne un **défi** signé : l'empreinte SHA-256 de `sel + nombre`, où `nombre` est
   tiré au hasard entre 0 et `maximum`. Le navigateur (ou l'application) retrouve `nombre` en
   essayant les valeurs une à une, pendant que la personne remplit le formulaire. Le travail est
   borné : jamais plus de `maximum` essais, la moitié en moyenne ;
2. trois niveaux — `NORMAL` (imperceptible), `ELEVE` (une à deux secondes sur un téléphone),
   `FORT` (dix à vingt). Le niveau monte avec le nombre d'inscriptions venues de la même
   adresse dans l'heure et avec deux signaux : formulaire envoyé trop vite, champ piège rempli ;
3. **un mauvais signal ne refuse jamais** : il rend le calcul suivant plus long. La personne
   lit « vérification en cours » ; elle n'a rien à résoudre ;
4. un défi ne sert qu'une fois.

**Ce que cela arrête, honnêtement.** Les robots ordinaires — ceux qui postent le formulaire
sans exécuter le site — sont arrêtés net. Un attaquant qui écrit un programme exprès résout le
calcul bien plus vite qu'un téléphone : pour lui, ce sont les compteurs ci-dessous qui
plafonnent, pas le calcul. Rien ici n'arrête quelqu'un qui crée dix comptes à la main.

**Qui est compté.** L'adresse publique vue par le relais (`X-Real-IP`, posé par ac_waf puis
ac_proxy — jamais `X-Forwarded-For`, que le visiteur peut écrire lui-même) ; en IPv6, le
préfixe /64, c'est-à-dire le foyer. Deux compteurs par heure :

- par adresse **et famille de navigateur** (système, navigateur, version majeure) : dans un
  gymnase en Wi-Fi partagé, les iPhone ne pâtissent pas des inscriptions faites sur Android.
  Ce n'est PAS une barrière — un robot change de signature à volonté — seulement une largesse
  pour les personnes ;
- par adresse seule, plus haut : c'est lui qui plafonne un robot qui change de signature.

Sur un satellite ou sur le réseau de la mairie, le serveur voit l'adresse locale de chaque
appareil (RFC 1918) : chacun a naturellement son compteur. À travers une box, il ne la voit pas
— aucun navigateur ne la révèle depuis 2019.

**Rien en clair** : la clé d'un compteur est une empreinte (HMAC) de l'adresse et de la
famille. Ni l'une ni l'autre ne sont lisibles en base, et tout s'efface au bout d'une heure.

**Clients sans défi.** L'application mobile publiée avant ce jour, un satellite ancien : ils
gardent un petit quota (`SANS_DEFI_PAR_ADRESSE`, `SANS_DEFI_EN_TOUT` par heure). À fermer
(`INSCRIPTION_SANS_DEFI_TOLEREE = False`) quand ces versions auront disparu.
"""
import hashlib
import hmac
import ipaddress
import re
import secrets
import time
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

NORMAL, ELEVE, FORT = "NORMAL", "ELEVE", "FORT"
ORDRE = (NORMAL, ELEVE, FORT)

# Nombre maximal d'essais par niveau. Un téléphone ordinaire fait de 100 000 à 300 000 essais
# par seconde avec le code du site ; il en faut la moitié du maximum en moyenne.
MAXIMUMS = {NORMAL: 50_000, ELEVE: 600_000, FORT: 3_000_000}

VALIDITE = 30 * 60           # secondes : on remplit lentement un formulaire, en crise
DELAI_MINIMAL = 3            # secondes entre l'émission du défi et l'envoi du formulaire
SUSPICION = timedelta(hours=1)
FENETRE = timedelta(hours=1)

# Défis consommés dans l'heure (un envoi de formulaire = un défi, réussi ou non).
SEUILS_PAR_FAMILLE = {ELEVE: 15, FORT: 60}      # même adresse, même famille de navigateur
SEUILS_PAR_ADRESSE = {ELEVE: 150, FORT: 400}    # même adresse, toutes familles
PLAFOND_PAR_ADRESSE = 1000                      # au-delà : refus pour le reste de l'heure

SANS_DEFI_PAR_ADRESSE = 3
SANS_DEFI_EN_TOUT = 30

CHAMP_PIEGE = "site_web"

# Verdicts de `controler`.
ACCEPTE = "ACCEPTE"
DEFI_REQUIS = "DEFI_REQUIS"
TROP_DE_DEMANDES = "TROP_DE_DEMANDES"


def _reglage(nom, defaut):
    return getattr(settings, nom, defaut)


def actif() -> bool:
    return bool(_reglage("INSCRIPTION_DEFI_ACTIF", True))


def maximum_de(niveau: str) -> int:
    return int(_reglage("INSCRIPTION_DEFI_MAXIMUMS", MAXIMUMS)[niveau])


def _hmac(texte: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), texte.encode(), hashlib.sha256).hexdigest()


# ── Qui appelle ───────────────────────────────────────────────────────────────────────────

def adresse_comptee(request) -> str:
    """L'adresse à laquelle rattacher les compteurs.

    `X-Real-IP` est écrit par ac_waf d'après la connexion réelle, puis recopié par ac_proxy :
    le visiteur ne peut pas le choisir. `X-Forwarded-For`, lui, commence par ce que le visiteur
    a bien voulu y mettre — s'y fier donnerait un compteur neuf à chaque requête."""
    brute = (request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR") or "").strip()
    try:
        adresse = ipaddress.ip_address(brute)
    except ValueError:
        return "inconnue"
    if adresse.version == 6:
        if adresse.ipv4_mapped is not None:
            return str(adresse.ipv4_mapped)
        # Un foyer reçoit un préfixe /64 et chaque appareil y change d'adresse à volonté.
        return str(ipaddress.ip_network(f"{adresse}/64", strict=False).network_address) + "/64"
    return str(adresse)


def famille_navigateur(agent: str) -> str:
    """« Chrome 142 sur Android » : système, navigateur, version majeure.

    Les navigateurs récents ne disent plus le modèle du téléphone ni la version exacte : on ne
    distingue pas les personnes, seulement les grandes familles. C'est voulu ainsi — et c'est
    falsifiable, voir l'en-tête du module."""
    from .frein_connexion import libelle_appareil

    agent = agent or ""
    version = ""
    for motif in (r"Edg/(\d+)", r"Firefox/(\d+)", r"Chrome/(\d+)", r"Version/(\d+)", r"ReserveResilience/(\d+)"):
        trouve = re.search(motif, agent)
        if trouve:
            version = trouve.group(1)
            break
    return f"{libelle_appareil(agent)} {version}".strip()


def _cles(request) -> dict:
    adresse = adresse_comptee(request)
    famille = famille_navigateur(request.META.get("HTTP_USER_AGENT", ""))
    return {
        "famille": _hmac(f"inscription|famille|{adresse}|{famille}"),
        "adresse": _hmac(f"inscription|adresse|{adresse}"),
        "suspect": _hmac(f"inscription|suspect|{adresse}|{famille}"),
        "sans_defi": _hmac(f"inscription|sans-defi|{adresse}"),
    }


# ── Compteurs (table CompteurInscription : une empreinte, un nombre, une échéance) ────────

def _lire(cle: str) -> int:
    from .models import CompteurInscription

    compteur = CompteurInscription.objects.filter(cle=cle, expire_le__gt=timezone.now()).first()
    return compteur.nombre if compteur else 0


def _compter(cle: str, duree: timedelta = FENETRE) -> int:
    """Ajoute un au compteur et rend sa nouvelle valeur. Un compteur échu repart de zéro."""
    from .models import CompteurInscription

    maintenant = timezone.now()
    CompteurInscription.objects.filter(cle=cle, expire_le__lte=maintenant).delete()
    try:
        with transaction.atomic():
            CompteurInscription.objects.create(cle=cle, nombre=1, expire_le=maintenant + duree)
        return 1
    except IntegrityError:
        CompteurInscription.objects.filter(cle=cle).update(nombre=F("nombre") + 1)
        return _lire(cle)


def purger() -> int:
    from .models import CompteurInscription

    supprimes, _ = CompteurInscription.objects.filter(expire_le__lte=timezone.now()).delete()
    return supprimes


# ── Niveau exigé ──────────────────────────────────────────────────────────────────────────

CLE_NIVEAU_IMPOSE = "niveau-impose"


def imposer_niveau(niveau: str, duree: timedelta) -> None:
    """Durcit le calcul pour tout le monde, pour une durée. S'efface tout seul : un réglage
    d'urgence oublié ne doit pas ralentir les inscriptions de la crise suivante."""
    from .models import CompteurInscription

    CompteurInscription.objects.filter(cle=CLE_NIVEAU_IMPOSE).delete()
    if niveau != NORMAL:
        CompteurInscription.objects.create(
            cle=CLE_NIVEAU_IMPOSE, nombre=ORDRE.index(niveau), expire_le=timezone.now() + duree)


def niveau_impose() -> str:
    return ORDRE[min(_lire(CLE_NIVEAU_IMPOSE), len(ORDRE) - 1)]


def _niveau_par_volume(nombre: int, seuils: dict) -> str:
    if nombre >= seuils[FORT]:
        return FORT
    if nombre >= seuils[ELEVE]:
        return ELEVE
    return NORMAL


def niveau_exige(request) -> str:
    cles = _cles(request)
    niveaux = [
        niveau_impose(),
        _niveau_par_volume(_lire(cles["famille"]), _reglage("INSCRIPTION_SEUILS_PAR_FAMILLE", SEUILS_PAR_FAMILLE)),
        _niveau_par_volume(_lire(cles["adresse"]), _reglage("INSCRIPTION_SEUILS_PAR_ADRESSE", SEUILS_PAR_ADRESSE)),
        ELEVE if _lire(cles["suspect"]) else NORMAL,
    ]
    return max(niveaux, key=ORDRE.index)


def plafond_atteint(request) -> bool:
    return _lire(_cles(request)["adresse"]) >= _reglage("INSCRIPTION_PLAFOND_PAR_ADRESSE", PLAFOND_PAR_ADRESSE)


# ── Le défi ───────────────────────────────────────────────────────────────────────────────

def _signature(sel: str, empreinte: str, maximum: int, emis: int, expire: int) -> str:
    return _hmac(f"inscription|defi|{sel}|{empreinte}|{maximum}|{emis}|{expire}")


def emettre(request, maintenant: float | None = None) -> dict:
    """Un défi au niveau exigé pour cet appelant. Rien n'est écrit en base : émettre un défi
    ne coûte presque rien au serveur, sans quoi cette adresse deviendrait elle-même une cible."""
    niveau = niveau_exige(request)
    maximum = maximum_de(niveau)
    emis = int(maintenant if maintenant is not None else time.time())
    expire = emis + VALIDITE
    sel = secrets.token_hex(12)
    nombre = secrets.randbelow(maximum + 1)
    empreinte = hashlib.sha256(f"{sel}{nombre}".encode()).hexdigest()
    try:
        from .metrics import INSCRIPTION_DEFIS
        INSCRIPTION_DEFIS.labels(niveau=niveau).inc()
    except Exception:  # la mesure ne doit jamais empêcher de s'inscrire
        pass
    return {
        "sel": sel, "empreinte": empreinte, "maximum": maximum, "emis": emis, "expire": expire,
        "niveau": niveau, "signature": _signature(sel, empreinte, maximum, emis, expire),
    }


def _defi_valable(defi, maintenant: float) -> bool:
    """Signé par nous, pas échu, et résolu."""
    if not isinstance(defi, dict):
        return False
    try:
        sel, empreinte = str(defi["sel"]), str(defi["empreinte"])
        maximum, emis, expire = int(defi["maximum"]), int(defi["emis"]), int(defi["expire"])
        nombre = int(defi["nombre"])
        signature = str(defi["signature"])
    except (KeyError, TypeError, ValueError):
        return False
    if not hmac.compare_digest(signature, _signature(sel, empreinte, maximum, emis, expire)):
        return False
    if maintenant > expire or not 0 <= nombre <= maximum:
        return False
    return hmac.compare_digest(hashlib.sha256(f"{sel}{nombre}".encode()).hexdigest(), empreinte)


def _mesurer(resultat: str) -> None:
    try:
        from .metrics import INSCRIPTIONS
        INSCRIPTIONS.labels(resultat=resultat).inc()
    except Exception:
        pass


def controler(request, maintenant: float | None = None) -> str:
    """Peut-on traiter cette demande de création de compte ?

    Rend `ACCEPTE`, `DEFI_REQUIS` (le client doit demander un défi — plus dur s'il y a lieu —
    et renvoyer le formulaire) ou `TROP_DE_DEMANDES` (plafond de l'adresse atteint)."""
    if not actif():
        return ACCEPTE
    maintenant = maintenant if maintenant is not None else time.time()
    cles = _cles(request)
    donnees = request.data if hasattr(request, "data") else {}
    defi = donnees.get("defi") if hasattr(donnees, "get") else None

    if plafond_atteint(request):
        _mesurer("plafond")
        return TROP_DE_DEMANDES

    if defi in (None, ""):
        # Client d'avant le défi (application mobile déjà installée) : un petit quota.
        if not _reglage("INSCRIPTION_SANS_DEFI_TOLEREE", True):
            _mesurer("defi_requis")
            return DEFI_REQUIS
        heure = timezone.now().strftime("%Y%m%d%H")
        if (_lire(cles["sans_defi"]) >= _reglage("INSCRIPTION_SANS_DEFI_PAR_ADRESSE", SANS_DEFI_PAR_ADRESSE)
                or _lire(_hmac(f"inscription|sans-defi|tout|{heure}"))
                >= _reglage("INSCRIPTION_SANS_DEFI_EN_TOUT", SANS_DEFI_EN_TOUT)):
            _mesurer("defi_requis")
            return DEFI_REQUIS
        _compter(cles["sans_defi"])
        _compter(_hmac(f"inscription|sans-defi|tout|{heure}"))
        _compter(cles["adresse"])
        _mesurer("sans_defi")
        return ACCEPTE

    if not _defi_valable(defi, maintenant):
        _mesurer("defi_invalide")
        return DEFI_REQUIS

    # Un défi ne sert qu'une fois : la contrainte d'unicité fait foi, même entre deux envois
    # simultanés.
    from .models import CompteurInscription
    try:
        with transaction.atomic():
            CompteurInscription.objects.create(
                cle=_hmac(f"inscription|utilise|{defi['sel']}"), nombre=1,
                expire_le=timezone.now() + timedelta(seconds=VALIDITE + 60))
    except IntegrityError:
        _mesurer("defi_rejoue")
        return DEFI_REQUIS

    # Le niveau exigé se lit AVANT de compter cette demande : sinon la personne qui fait
    # franchir un seuil verrait son propre défi refusé comme trop facile.
    exige = niveau_exige(request)
    _compter(cles["famille"])
    _compter(cles["adresse"])

    # Les signaux ne refusent rien : ils rendent le niveau exigé plus haut, pour une heure.
    trop_vite = maintenant - int(defi["emis"]) < _reglage("INSCRIPTION_DELAI_MINIMAL", DELAI_MINIMAL)
    piege = bool(str(donnees.get(CHAMP_PIEGE) or "").strip())
    if trop_vite or piege:
        _compter(cles["suspect"], SUSPICION)
        exige = max(exige, ELEVE, key=ORDRE.index)

    if ORDRE.index(_niveau_du_maximum(int(defi["maximum"]))) < ORDRE.index(exige):
        _mesurer("defi_trop_facile")
        return DEFI_REQUIS

    _mesurer("acceptee")
    return ACCEPTE


def _niveau_du_maximum(maximum: int) -> str:
    """Le niveau le plus haut que ce défi atteint, quel que soit le réglage du moment."""
    atteint = NORMAL
    for niveau in ORDRE:
        if maximum >= maximum_de(niveau):
            atteint = niveau
    return atteint
