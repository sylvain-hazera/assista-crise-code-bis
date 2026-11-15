"""Vigilance Météo-France : relevé, copie en base, annonce aux institutions qui l'ont demandée.

SOURCE
API « DonneesPubliquesVigilance » du portail public de Météo-France
(https://portail-api.meteofrance.fr), Licence Ouverte 2.0 -- il suffit de citer la source. Elle
couvre la métropole (96 départements, bandes littorales comprises) ; la vigilance outre-mer est
un autre produit, non repris ici.

RÈGLE DE CONCEPTION (15/11/2026)
Seul le serveur appelle Météo-France, depuis une tâche planifiée, et toujours pour la France
entière. Aucun navigateur ne l'interroge, aucune requête d'utilisateur ne déclenche d'appel
sortant, et rien de ce qui part ne désigne une personne, une commune ni une institution : il
n'y a donc aucune fuite possible vers l'extérieur. Les pages lisent la copie en base
(`VigilanceMeteo`, `VignetteVigilanceMeteo`).

LA CLÉ
Un jeton signé par le portail, valable trois ans au plus, lu dans un secret Docker
(`/run/secrets/meteofrance_cle_api`) : jamais dans le dépôt, jamais dans une variable
d'environnement, jamais dans un journal. Son échéance est inscrite dans le jeton lui-même ;
`echeance_cle()` la lit pour que la supervision prévienne un mois avant -- une vigilance qui
cesserait d'arriver sans bruit serait le pire défaut de ce module.

Sans clé (poste de développement, satellite), tout le module se tait : la commande le dit et
s'arrête, les pages affichent « aucun relevé ».
"""
import base64
import binascii
import datetime
import json
import logging
import os
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .geo_reference import DEPARTEMENTS

logger = logging.getLogger(__name__)

URL_BASE = "https://public-api.meteofrance.fr/public/DPVigilance/v1"
DELAI_REPONSE_S = 20

# Numérotation de Météo-France (version 6 de la vigilance). Libellés sans accent ni majuscule :
# ils partent tels quels sur la radio, où chaque octet compte et où les accents se perdent.
PHENOMENES = {
    1: "vent violent",
    2: "pluie-inondation",
    3: "orages",
    4: "crues",
    5: "neige-verglas",
    6: "canicule",
    7: "grand froid",
    8: "avalanches",
    9: "vagues-submersion",
}
COULEURS = {1: "vert", 2: "jaune", 3: "orange", 4: "rouge"}
ECHEANCES = ("J", "J1")
FRANCE = "FRA"

# Au-delà, la copie en base est jugée trop vieille pour annoncer quoi que ce soit : Météo-France
# republie au moins quatre fois par jour, six heures sans relevé signifient une panne chez nous.
FRAICHEUR_MAX = datetime.timedelta(hours=6)

# Heure légale de métropole, écrite ici plutôt que lue dans la configuration : la vigilance de
# ce produit ne concerne que la métropole, quel que soit le fuseau du serveur.
FUSEAU = ZoneInfo("Europe/Paris")


class CleAbsente(Exception):
    """Aucune clé Météo-France sur cette machine : rien à relever."""


# ── La clé ──────────────────────────────────────────────────────────────────────────────────

def _chemin_cle() -> Path:
    return Path(os.environ.get("METEOFRANCE_CLE_API_FILE", "/run/secrets/meteofrance_cle_api"))


def lire_cle():
    """La clé, ou None si le secret n'est pas monté. Ne jamais journaliser la valeur."""
    try:
        cle = _chemin_cle().read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return cle or None


def echeance_cle():
    """Date d'expiration inscrite dans la clé, ou None si elle est absente ou illisible.

    La clé est un jeton en trois segments ; le deuxième, en base64, porte `exp`. On le LIT sans
    vérifier la signature : il ne s'agit pas de faire confiance au jeton, seulement de savoir
    quand le portail cessera de l'accepter."""
    cle = lire_cle()
    if not cle or cle.count(".") != 2:
        return None
    segment = cle.split(".")[1]
    try:
        charge = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
        return datetime.datetime.fromtimestamp(int(charge["exp"]), tz=datetime.timezone.utc)
    except (binascii.Error, ValueError, KeyError, TypeError, OverflowError, OSError):
        return None


# ── Les appels ──────────────────────────────────────────────────────────────────────────────

def _appeler(chemin):
    cle = lire_cle()
    if cle is None:
        raise CleAbsente()
    reponse = requests.get(
        f"{URL_BASE}/{chemin}", headers={"apikey": cle, "accept": "*/*"}, timeout=DELAI_REPONSE_S,
    )
    reponse.raise_for_status()
    return reponse


def telecharger_carte():
    """Couleur de chaque département, par phénomène, pour aujourd'hui et demain."""
    return _appeler("cartevigilance/encours").json()


def telecharger_textes():
    """Bulletins de suivi (national, zonaux, départementaux)."""
    return _appeler("textesvigilance/encours").json()


def telecharger_vignette(echeance):
    """Carte nationale officielle (image PNG) pour « J » ou « J1 »."""
    return _appeler(f"vignettenationale-{echeance}/encours").content


# ── La lecture des réponses ─────────────────────────────────────────────────────────────────

def _code_departement(domaine):
    """Code de département d'un domaine Météo-France, ou None s'il ne nous concerne pas.

    Les bandes littorales ont leur propre domaine (« 3010 » pour le littoral du Gard, « 2A10 »
    pour celui de la Corse-du-Sud) : elles portent le phénomène vagues-submersion et sont
    rattachées ici à leur département, qui est l'échelle à laquelle une mairie raisonne."""
    if domaine == FRANCE:
        return FRANCE
    if len(domaine) == 4 and domaine.endswith("10"):
        domaine = domaine[:2]
    return domaine if len(domaine) == 2 else None


def analyser_carte(donnees):
    """Réponse de `telecharger_carte` -> (heure de publication, {code: {"J": fiche, "J1": fiche}}).

    Une fiche : {"debut", "fin", "couleur", "phenomenes": [{"id", "couleur", "periodes"}]}, les
    phénomènes du plus grave au moins grave. Seul le jaune et au-delà est retenu : le vert est
    l'absence de vigilance, le recopier trente mille fois par jour n'apprendrait rien.

    Une entrée mal formée est ignorée, pas le relevé entier : mieux vaut 95 départements à jour
    qu'aucun."""
    produit = donnees["product"]
    publie_le = parse_datetime(produit["update_time"])
    if publie_le is None:
        raise ValueError("heure de publication illisible")

    departements = {}
    for periode in produit.get("periods") or []:
        echeance = periode.get("echeance")
        if echeance not in ECHEANCES:
            continue
        for domaine in (periode.get("timelaps") or {}).get("domain_ids") or []:
            code = _code_departement(str(domaine.get("domain_id", "")))
            if code is None:
                continue
            fiche = departements.setdefault(code, {}).setdefault(echeance, {
                "debut": periode.get("begin_validity_time"),
                "fin": periode.get("end_validity_time"),
                "couleur": 1,
                "phenomenes": {},
            })
            try:
                fiche["couleur"] = max(fiche["couleur"], int(domaine.get("max_color_id", 1)))
                for item in domaine.get("phenomenon_items") or []:
                    identifiant = int(item["phenomenon_id"])
                    couleur = int(item["phenomenon_max_color_id"])
                    if couleur < 2:
                        continue
                    periodes = [
                        {"debut": t["begin_time"], "fin": t["end_time"], "couleur": int(t["color_id"])}
                        for t in item.get("timelaps_items") or []
                        if int(t.get("color_id", 1)) >= 2
                    ]
                    connu = fiche["phenomenes"].get(identifiant)
                    if connu is None or couleur > connu["couleur"]:
                        fiche["phenomenes"][identifiant] = {
                            "id": identifiant, "couleur": couleur, "periodes": periodes,
                        }
            except (KeyError, ValueError, TypeError):
                logger.warning("Vigilance : domaine %s illisible, ignoré.", code)

    for fiches in departements.values():
        for fiche in fiches.values():
            fiche["phenomenes"] = sorted(
                fiche["phenomenes"].values(), key=lambda p: (-p["couleur"], p["id"]),
            )
    return publie_le, departements


def analyser_textes(donnees):
    """Réponse de `telecharger_textes` -> {code: [{"rubrique", "alea", "titre", "lignes"}]}.

    Seuls le bulletin national (« FRA ») et les bulletins départementaux sont repris. Les
    bulletins zonaux (zones de défense) redisent le national à une échelle qu'aucun écran
    n'affiche ici."""
    bulletins = {}
    for bloc in (donnees.get("product") or {}).get("text_bloc_items") or []:
        code = str(bloc.get("domain_id", ""))
        if code != FRANCE and len(code) != 2:
            continue
        sections = []
        for item in bloc.get("bloc_items") or []:
            for texte in item.get("text_items") or []:
                alea = texte.get("hazard_name") if texte.get("hazard_code") else ""
                for terme in texte.get("term_items") or []:
                    for partie in terme.get("subdivision_text") or []:
                        titre = (partie.get("bold_text") or partie.get("underline_text") or "")
                        titre = titre.strip().rstrip(":").strip()
                        lignes = [ligne.strip() for ligne in partie.get("text") or [] if ligne and ligne.strip()]
                        if not lignes:
                            continue
                        sections.append({
                            "rubrique": item.get("type_name") or "",
                            "alea": alea or "",
                            "titre": titre,
                            "lignes": lignes,
                        })
        bulletins[code] = sections
    return bulletins


# ── La copie en base ────────────────────────────────────────────────────────────────────────

def enregistrer(publie_le, departements, bulletins=None, maintenant=None):
    """Réécrit `VigilanceMeteo` d'après un relevé. `bulletins=None` (les textes n'ont pas pu
    être relevés) laisse les bulletins déjà connus en place plutôt que de les effacer."""
    from .models import VigilanceMeteo

    maintenant = maintenant or timezone.now()
    with transaction.atomic():
        for code, fiches in departements.items():
            valeurs = {
                "couleur_j": (fiches.get("J") or {}).get("couleur", 1),
                "couleur_j1": (fiches.get("J1") or {}).get("couleur", 1),
                "detail": fiches,
                "publie_le": publie_le,
                "releve_le": maintenant,
            }
            if bulletins is not None:
                valeurs["bulletin"] = bulletins.get(code, [])
            VigilanceMeteo.objects.update_or_create(departement_code=code, defaults=valeurs)
    return len(departements)


def enregistrer_vignette(echeance, image, maintenant=None):
    from .models import VignetteVigilanceMeteo

    VignetteVigilanceMeteo.objects.update_or_create(
        echeance=echeance, defaults={"image": image, "releve_le": maintenant or timezone.now()},
    )


def relever():
    """Un relevé complet. Renvoie le nombre de départements écrits.

    La carte est indispensable : son échec remonte à l'appelant. Les bulletins et les images
    sont un complément : leur échec est journalisé et le relevé de la carte est gardé."""
    publie_le, departements = analyser_carte(telecharger_carte())

    try:
        bulletins = analyser_textes(telecharger_textes())
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        logger.warning("Vigilance : bulletins non relevés (%s), les précédents sont gardés.", exc)
        bulletins = None

    nombre = enregistrer(publie_le, departements, bulletins)

    for echeance in ECHEANCES:
        try:
            enregistrer_vignette(echeance, telecharger_vignette(echeance))
        except requests.RequestException as exc:
            logger.warning("Vigilance : carte nationale %s non relevée (%s).", echeance, exc)
    return nombre


# ── L'annonce aux institutions ──────────────────────────────────────────────────────────────

def nom_departement(code):
    return DEPARTEMENTS.get(code) or code


def departement_de(institution):
    """Département d'une institution : le sien s'il est renseigné, sinon celui de sa commune."""
    from .models import Commune

    if institution.departement_code:
        return institution.departement_code
    if institution.commune_code:
        return (Commune.objects.filter(code=institution.commune_code)
                .values_list("departement_code", flat=True).first())
    return None


def _instant(texte):
    return parse_datetime(texte) if texte else None


def niveaux_en_cours(detail, maintenant=None):
    """{phénomène: {"couleur", "debut", "fin"}} : le niveau le plus haut annoncé pour aujourd'hui
    ou demain, échéances déjà terminées exclues. À couleur égale, la première échéance gagne --
    c'est son horaire qu'il faut annoncer."""
    maintenant = maintenant or timezone.now()
    niveaux = {}
    for echeance in ECHEANCES:
        fiche = (detail or {}).get(echeance) or {}
        fin_echeance = _instant(fiche.get("fin"))
        if fin_echeance is not None and fin_echeance <= maintenant:
            continue
        for phenomene in fiche.get("phenomenes") or []:
            couleur = phenomene["couleur"]
            connu = niveaux.get(phenomene["id"])
            if connu is not None and connu["couleur"] >= couleur:
                continue
            # Horaire : les tranches à la couleur maximale ; à défaut (les crues n'en ont pas),
            # toute l'échéance.
            tranches = [p for p in phenomene.get("periodes") or [] if p["couleur"] == couleur]
            debuts = [d for d in (_instant(p["debut"]) for p in tranches) if d]
            fins = [f for f in (_instant(p["fin"]) for p in tranches) if f]
            niveaux[phenomene["id"]] = {
                "couleur": couleur,
                "debut": min(debuts) if debuts else _instant(fiche.get("debut")),
                "fin": max(fins) if fins else fin_echeance,
            }
    return niveaux


def _sans_accent(texte):
    return "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))


def _heure(instant):
    local = instant.astimezone(FUSEAU)
    if local.hour == 0 and local.minute == 0:
        return "minuit"
    return f"{local.hour}h" if local.minute == 0 else f"{local.hour}h{local.minute:02d}"


def _jour(instant, maintenant):
    ecart = (instant.astimezone(FUSEAU).date() - maintenant.astimezone(FUSEAU).date()).days
    if ecart <= 0:
        return "aujourd'hui"
    if ecart == 1:
        return "demain"
    return instant.astimezone(FUSEAU).strftime("le %d/%m")


def texte_alerte(code, phenomene, niveau, maintenant=None):
    """Phrase d'annonce, sans accent : elle part telle quelle sur la radio (voir PHENOMENES)."""
    maintenant = maintenant or timezone.now()
    quand = ""
    debut, fin = niveau.get("debut"), niveau.get("fin")
    if debut and fin:
        if debut <= maintenant:
            quand = f", en cours jusqu'a {_heure(fin)}"
        else:
            quand = f", {_jour(debut, maintenant)} de {_heure(debut)} a {_heure(fin)}"
    return (
        f"Vigilance {COULEURS[niveau['couleur']].upper()} {PHENOMENES.get(phenomene, 'meteo')} - "
        f"{_sans_accent(nom_departement(code))} ({code}){quand}. Source Meteo-France."
    )


def _annoncer(institution, texte):
    """Dépose l'annonce sur les canaux radio de l'institution et l'envoie en message privé aux
    personnes qui lui sont rattachées. Un échec de messagerie n'empêche jamais le reste."""
    from .matrix import envoyer_dm
    from .models import (
        CanalMeshCore, CanalMeshtastic, ContactInstitution, DirectionMessageMesh,
        MessageCanalMeshCore, MessageCanalMeshtastic, StatutMessageMesh,
    )

    # Même mécanisme que les alertes sismiques : une ligne sortante en attente, le préfixe et la
    # découpe sont appliqués par le pont au moment de l'envoi.
    for modele_canal, modele_message in (
        (CanalMeshCore, MessageCanalMeshCore), (CanalMeshtastic, MessageCanalMeshtastic),
    ):
        for canal in modele_canal.objects.filter(institution=institution, actif=True):
            modele_message.objects.create(
                canal=canal, direction=DirectionMessageMesh.SORTANT,
                statut=StatutMessageMesh.EN_ATTENTE, contenu=texte, environment=canal.environment,
            )

    contacts = (ContactInstitution.objects
                .filter(institution=institution, actif=True, utilisateur__is_active=True)
                .select_related("utilisateur"))
    for contact in contacts:
        try:
            envoyer_dm(contact.utilisateur, f"[assista-crise] {texte}")
        except Exception:
            logger.exception("Vigilance : message non remis (destinataire %s).", contact.utilisateur_id)


def diffuser_alertes(maintenant=None):
    """Annonce à chaque institution abonnée ce qui a franchi son seuil depuis le dernier relevé.

    Une annonce par épisode et par phénomène : à l'entrée dans le seuil, puis seulement si la
    couleur MONTE. Une baisse qui reste au-dessus du seuil est notée sans bruit ; un retour sous
    le seuil efface la mémoire, pour que l'épisode suivant soit annoncé. Il n'y a pas de message
    de levée : sur la radio, chaque message coûte, et la fin d'une vigilance n'appelle aucun
    geste urgent.

    Renvoie la liste des annonces faites (« Institution : texte »)."""
    from .models import ConfigurationAlerteVigilance, VigilanceDiffusee, VigilanceMeteo

    maintenant = maintenant or timezone.now()
    annonces = []
    configurations = (ConfigurationAlerteVigilance.objects.filter(actif=True)
                      .select_related("institution"))
    for configuration in configurations:
        institution = configuration.institution
        code = departement_de(institution)
        if not code:
            continue
        ligne = VigilanceMeteo.objects.filter(pk=code).first()
        if ligne is None or maintenant - ligne.releve_le > FRAICHEUR_MAX:
            # Pas de relevé récent : ni annonce, ni effacement de mémoire sur une donnée périmée.
            continue

        # Une institution qui a changé de département repart d'une mémoire vide.
        VigilanceDiffusee.objects.filter(institution=institution).exclude(departement_code=code).delete()
        memoire = {v.phenomene: v for v in VigilanceDiffusee.objects.filter(institution=institution)}

        for phenomene, niveau in niveaux_en_cours(ligne.detail, maintenant).items():
            couleur = niveau["couleur"]
            connu = memoire.pop(phenomene, None)
            if couleur < configuration.couleur_min:
                if connu is not None:
                    connu.delete()
                continue
            if connu is not None and couleur <= connu.couleur:
                if couleur < connu.couleur:
                    connu.couleur = couleur
                    connu.save(update_fields=["couleur"])
                continue

            texte = texte_alerte(code, phenomene, niveau, maintenant)
            _annoncer(institution, texte)
            VigilanceDiffusee.objects.update_or_create(
                institution=institution, phenomene=phenomene,
                defaults={"couleur": couleur, "departement_code": code,
                          "environment": configuration.environment},
            )
            annonces.append(f"{institution.nom} : {texte}")
            logger.info("Vigilance annoncée à %s : %s", institution.nom, texte)

        # Phénomènes qui ne sont plus signalés du tout.
        for oublie in memoire.values():
            oublie.delete()

    if annonces:
        _prevenir_administrateurs(annonces)
    return annonces


def _prevenir_administrateurs(annonces):
    """Un seul message par relevé aux administrateurs, quel que soit le nombre d'institutions
    touchées : un épisode orange sur un département peut en concerner des dizaines."""
    from .matrix import envoyer_dm
    from .models import User, UserRole

    texte = "[assista-crise] Vigilance annoncée :\n" + "\n".join(annonces[:20])
    if len(annonces) > 20:
        texte += f"\n… et {len(annonces) - 20} autres."
    for administrateur in User.objects.filter(type=UserRole.ADMINISTRATOR, is_active=True):
        try:
            envoyer_dm(administrateur, texte)
        except Exception:
            logger.exception("Vigilance : résumé non remis (destinataire %s).", administrateur.id)
