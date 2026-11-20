"""Copie central -> satellite du référentiel d'adresses (lot B, 20/11/2026).

Un satellite coupé d'Internet doit pouvoir rattacher une fiche à son adresse, tracer les cercles
des personnes vulnérables et pointer les dégâts : il lui faut les adresses de son territoire.
Elles viennent du central, jamais de la Base Adresse Nationale directement (rien ne se charge
tout seul sur un satellite, voir core/apps.py).

QUELLES COMMUNES : celles du territoire de l'institution du satellite (communal, intercommunal),
et celles des crises ouvertes qui le concernent -- la même règle qu'au central.

COMMENT
- `GET /api/satellites/<id>/adresses/?communes_voulues=1` : la liste des communes à tenir ;
- `GET /api/satellites/<id>/adresses/?communes=a,b` : toutes les adresses de ces communes (celles
  que le satellite n'a pas encore : une commune chargée au central depuis longtemps a des
  adresses plus anciennes que le curseur du satellite, elle ne viendrait jamais autrement) ;
- `GET /api/satellites/<id>/adresses/?depuis=<horodatage>&apres=<ban_id>` : ce qui a changé
  depuis, par pages, dans l'ordre (modification, identifiant). Le satellite garde comme curseur
  la dernière ligne appliquée : une copie interrompue reprend où elle s'était arrêtée.

Même régime que le reste de la descente : le central fait autorité, copie à l'identique par
identifiant (`modifie_le` compris), adresses retirées comprises -- elles le sont aussi sur le
satellite, jamais effacées.
"""
import datetime
import logging

from django.db.models import Q

logger = logging.getLogger(__name__)

TAILLE_PAGE = 5000
PAGES_PAR_PASSAGE = 40
CHAMPS = ("commune_code", "commune_nom", "code_postal", "numero", "suffixe", "voie", "lieu_dit",
          "type_position", "parcelles")


# ── Côté central ──

def communes_pour_satellite(satellite, crises):
    from .referentiel_adresses import communes_d_institution, communes_de_crise

    communes = communes_d_institution(satellite.institution) if satellite.institution_id else set()
    for crise in crises:
        communes |= communes_de_crise(crise)
    return communes


def _ligne(adresse):
    return {
        "ban_id": adresse.ban_id, **{c: getattr(adresse, c) for c in CHAMPS},
        "lon": round(adresse.location.x, 6), "lat": round(adresse.location.y, 6),
        "retiree_le": adresse.retiree_le.isoformat() if adresse.retiree_le else None,
        "modifie_le": adresse.modifie_le.isoformat(),
    }


def page(communes, depuis=None, apres="", limite=None):
    """Une page d'adresses de ces communes, modifiées après le curseur (depuis, apres). Rend
    {"adresses": [...], "suivant": {"depuis", "apres"} ou None}."""
    from .models import AdresseBAN

    limite = limite or TAILLE_PAGE
    lignes = AdresseBAN.objects.filter(commune_code__in=communes)
    if depuis is not None:
        lignes = lignes.filter(Q(modifie_le__gt=depuis) | Q(modifie_le=depuis, ban_id__gt=apres or ""))
    lignes = list(lignes.order_by("modifie_le", "ban_id")[:limite + 1])
    suivant = None
    if len(lignes) > limite:
        lignes = lignes[:limite]
        suivant = {"depuis": lignes[-1].modifie_le.isoformat(), "apres": lignes[-1].ban_id}
    return {"adresses": [_ligne(a) for a in lignes], "suivant": suivant}


# ── Côté satellite ──

def curseur_local():
    """(modifie_le, ban_id) de la dernière adresse copiée, ou (None, "")."""
    from .models import AdresseBAN

    derniere = AdresseBAN.objects.order_by("-modifie_le", "-ban_id").first()
    return (derniere.modifie_le, derniere.ban_id) if derniere else (None, "")


def appliquer(adresses):
    """Copie à l'identique une page reçue du central. Rend le nombre de lignes écrites."""
    from django.contrib.gis.geos import Point
    from django.utils.dateparse import parse_datetime

    from .models import AdresseBAN

    if not adresses:
        return 0
    connues = set(AdresseBAN.objects.filter(ban_id__in=[a["ban_id"] for a in adresses]).values_list("ban_id", flat=True))
    a_creer, a_modifier = [], []
    for a in adresses:
        objet = AdresseBAN(
            ban_id=a["ban_id"], location=Point(a["lon"], a["lat"], srid=4326),
            retiree_le=parse_datetime(a["retiree_le"]) if a.get("retiree_le") else None,
            modifie_le=parse_datetime(a["modifie_le"]), **{c: a.get(c) or "" for c in CHAMPS})
        (a_modifier if objet.ban_id in connues else a_creer).append(objet)
    AdresseBAN.objects.bulk_create(a_creer, batch_size=TAILLE_PAGE, ignore_conflicts=True)
    AdresseBAN.objects.bulk_update(a_modifier, list(CHAMPS) + ["location", "retiree_le", "modifie_le"], batch_size=TAILLE_PAGE)
    return len(adresses)


def copier(lire):
    """Copie les adresses du central. `lire(params)` rend la réponse JSON de l'action `adresses`
    du satellite au central. Rend {"communes_nouvelles", "ecrites"}."""
    from .models import AdresseBAN

    # Le curseur AVANT toute écriture : copier d'abord une commune nouvelle (aux adresses
    # récentes) le repousserait au-delà d'un changement plus ancien d'une autre commune, qui ne
    # serait alors jamais copié.
    depuis, apres = curseur_local()
    voulues = set(lire({"communes_voulues": "1"}).get("communes", []))
    presentes = set(AdresseBAN.objects.filter(commune_code__in=voulues).values_list("commune_code", flat=True).distinct())
    # Première copie : la passe incrémentale depuis zéro prend tout, rien à faire à part.
    nouvelles = sorted(voulues - presentes) if depuis else []
    ecrites = 0
    # Les communes nouvelles en entier : leur copie ne dépend pas du curseur.
    if nouvelles:
        params = {"communes": ",".join(nouvelles)}
        for _ in range(PAGES_PAR_PASSAGE):
            reponse = lire(params)
            ecrites += appliquer(reponse.get("adresses", []))
            if not reponse.get("suivant"):
                break
            params = {"communes": ",".join(nouvelles), **reponse["suivant"]}
    # Puis ce qui a changé depuis la dernière ligne copiée avant ce passage, pour toutes.
    params = {"depuis": depuis.isoformat(), "apres": apres} if depuis else {}
    for _ in range(PAGES_PAR_PASSAGE):
        reponse = lire(params)
        ecrites += appliquer(reponse.get("adresses", []))
        if not reponse.get("suivant"):
            break
        params = dict(reponse["suivant"])
    return {"communes_nouvelles": len(nouvelles), "ecrites": ecrites}


def lire_curseur(params):
    """(depuis, apres, communes) lus dans les paramètres d'une requête."""
    from django.utils.dateparse import parse_datetime

    depuis = parse_datetime(params.get("depuis") or "") if params.get("depuis") else None
    if params.get("depuis") and depuis is None:
        raise ValueError("depuis : horodatage ISO attendu")
    if depuis is not None and depuis.tzinfo is None:
        depuis = depuis.replace(tzinfo=datetime.timezone.utc)
    communes = [c for c in (params.get("communes") or "").split(",") if c]
    return depuis, params.get("apres") or "", communes
