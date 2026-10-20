"""Valeurs foncières (DVF, open data DGFiP, fichiers « geo-dvf » d'Etalab) pour le référencement
des dégâts : prix médian au m² de la commune et ventes connues sur la parcelle d'une habitation.

Toujours une valeur INDICATIVE (ventes passées, sans l'état du bien) -- jamais une expertise.
Un fichier par commune et par année : https://files.data.gouv.fr/geo-dvf/latest/csv/<année>/
communes/<département>/<code INSEE>.csv. Seules les ventes d'UN seul logement (maison ou
appartement, dépendances admises) servent au prix au m² : une vente groupée n'a qu'une valeur
globale, impossible à répartir entre ses logements.
"""
import csv
import io
import statistics
import urllib.request
from collections import defaultdict

from django.core.cache import cache
from django.utils import timezone

URL_DVF = "https://files.data.gouv.fr/geo-dvf/latest/csv/{annee}/communes/{dep}/{code}.csv"
NB_ANNEES = 3
TYPES_LOGEMENT = ("Maison", "Appartement")
# Bornes de vraisemblance d'un prix au m² (ventes symboliques, erreurs de saisie, ruines)
PRIX_M2_MIN, PRIX_M2_MAX = 200, 25_000
SURFACE_MIN = 9
DUREE_CACHE = 7 * 24 * 3600   # publication DVF semestrielle
SOURCE = "DVF (DGFiP / Etalab)"


def _departement(code_commune: str) -> str:
    if code_commune.startswith("97"):
        return code_commune[:3]
    return code_commune[:2]


def _telecharger(code_commune: str, annee: int):
    url = URL_DVF.format(annee=annee, dep=_departement(code_commune), code=code_commune)
    try:
        with urllib.request.urlopen(url, timeout=20) as reponse:
            return reponse.read().decode("utf-8")
    except Exception:
        return None


def _ventes(code_commune: str):
    """Lignes DVF des NB_ANNEES dernières années publiées (mise en cache), et ces années."""
    cle = f"dvf:ventes:{code_commune}"
    en_cache = cache.get(cle)
    if en_cache is not None:
        return en_cache
    lignes, annees = [], []
    annee = timezone.now().year
    # l'année en cours n'est publiée qu'en partie (ou pas) : on remonte jusqu'à trouver NB_ANNEES
    while len(annees) < NB_ANNEES and annee >= timezone.now().year - NB_ANNEES - 2:
        texte = _telecharger(code_commune, annee)
        if texte:
            annees.append(annee)
            lignes.extend(csv.DictReader(io.StringIO(texte)))
        annee -= 1
    resultat = {"lignes": lignes, "annees": sorted(annees)}
    if annees:
        cache.set(cle, resultat, DUREE_CACHE)
    return resultat


def _nombre(valeur):
    try:
        return float(valeur)
    except (TypeError, ValueError):
        return None


def _ventes_logement_unique(lignes):
    """Une entrée par vente d'un seul logement : {id, date, type, valeur, surface, parcelle}."""
    par_mutation = defaultdict(list)
    for ligne in lignes:
        if ligne.get("nature_mutation") == "Vente":
            par_mutation[ligne.get("id_mutation")].append(ligne)
    ventes = []
    for id_mutation, groupe in par_mutation.items():
        logements = [l for l in groupe if l.get("type_local") in TYPES_LOGEMENT]
        # un même local peut apparaître sur plusieurs lignes (une par nature de culture du terrain)
        distincts = {(l.get("id_parcelle"), l.get("type_local"), l.get("surface_reelle_bati")) for l in logements}
        autres_bati = [l for l in groupe if l.get("type_local") == "Local industriel. commercial ou assimilé"]
        if len(distincts) != 1 or autres_bati:
            continue
        logement = logements[0]
        valeur = _nombre(logement.get("valeur_fonciere"))
        surface = _nombre(logement.get("surface_reelle_bati"))
        if not valeur or not surface or surface < SURFACE_MIN:
            continue
        ventes.append({
            "id": id_mutation,
            "date": logement.get("date_mutation"),
            "type": logement.get("type_local"),
            "valeur": valeur,
            "surface": surface,
            "parcelle": logement.get("id_parcelle"),
        })
    return ventes


def _mediane(ventes):
    prix = [v["valeur"] / v["surface"] for v in ventes]
    prix = [p for p in prix if PRIX_M2_MIN <= p <= PRIX_M2_MAX]
    if not prix:
        return {"prix_m2_median": None, "nb_ventes": 0}
    return {"prix_m2_median": round(statistics.median(prix)), "nb_ventes": len(prix)}


def prix_commune(code_commune: str) -> dict:
    """Prix médian au m² de la commune (maisons, appartements, ensemble) sur les dernières années."""
    donnees = _ventes(code_commune)
    if not donnees["annees"]:
        return {"erreur": "Données DVF indisponibles pour cette commune (Alsace-Moselle et Mayotte ne "
                          "sont pas couvertes, ou service injoignable).", "source": SOURCE}
    ventes = _ventes_logement_unique(donnees["lignes"])
    return {
        "erreur": None,
        "source": SOURCE,
        "annees": donnees["annees"],
        "ensemble": _mediane(ventes),
        "maison": _mediane([v for v in ventes if v["type"] == "Maison"]),
        "appartement": _mediane([v for v in ventes if v["type"] == "Appartement"]),
    }


def ventes_parcelle(code_commune: str, parcelle: str) -> list:
    """Ventes de logement connues sur cette parcelle (la plus récente d'abord)."""
    if not parcelle:
        return []
    ventes = [v for v in _ventes_logement_unique(_ventes(code_commune)["lignes"]) if v["parcelle"] == parcelle]
    return sorted(
        ({k: v[k] for k in ("date", "type", "valeur", "surface")} for v in ventes),
        key=lambda v: v["date"] or "", reverse=True,
    )


def estimation_habitation(habitation) -> dict:
    """Prix communal, ventes de la parcelle et valeur indicative = surface habitable totale ×
    prix médian (maisons si connu, sinon ensemble). Sans surface saisie : pas d'estimation."""
    if not habitation.commune_code:
        return {"erreur": "Commune inconnue pour cette habitation.", "source": SOURCE}
    commune = prix_commune(habitation.commune_code)
    if commune["erreur"]:
        return commune
    reference = commune["maison"] if commune["maison"]["prix_m2_median"] else commune["ensemble"]
    estimation = None
    if habitation.surface_habitable_totale and reference["prix_m2_median"]:
        estimation = round(habitation.surface_habitable_totale * reference["prix_m2_median"], -2)
    return {
        **commune,
        "ventes_parcelle": ventes_parcelle(habitation.commune_code, habitation.parcelle_cadastrale),
        "valeur_indicative": estimation,
        "base_estimation": (
            f"{habitation.surface_habitable_totale:g} m² × {reference['prix_m2_median']} €/m² (médiane communale)"
            if estimation else None
        ),
    }
