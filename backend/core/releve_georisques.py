"""Un seul relevé Géorisques par commune, qui nourrit toutes les pages (18/11/2026).

Constat de Sylvain : Géorisques était interrogé séparément par la page des risques, par celle
des enjeux exposés, par les plans de prévention — « à partir du moment où j'appelle une fois ou
mets à jour Géorisques, ça doit nourrir, entre autres, ces deux pages ». Et : « tente aussi de
voir ce que tu peux récupérer d'autre de Géorisques, vois large ».

`relever_tout` est désormais LE point d'entrée : il relève en une passe

- les risques recensés sur la commune (ce que la page « Risques de la commune » propose) ;
- les arrêtés de catastrophe naturelle, l'atlas des zones inondables, le territoire à risque
  important d'inondation, les mouvements de terrain, les cavités, le potentiel radon et la zone
  de sismicité — rien de cela n'était repris ;
- les zones inondables officielles (core/zonages_officiels.py) et les plans de prévention
  (core/plans_prevention.py), inchangés : ils gardent leurs tables, on les appelle d'ici.

Tout est gardé en base (`ReleveGeorisques`, une ligne par commune et par rubrique) : les pages
lisent la copie, jamais le service. Les requêtes sont espacées (`_attendre_son_tour`, la même
file que les zonages : Géorisques demande qu'on ne l'interroge pas en rafale), et un relevé
récent n'est pas refait. Une rubrique en panne garde ce qu'on avait.

Tous les points d'accès ont été essayés à la main le 18/11/2026 sur une commune réelle avant
d'être écrits ici (réponses et formes vérifiées) — pas d'adaptateur écrit sur des suppositions.
"""
import datetime
import json
import logging
import urllib.parse
import urllib.request

from django.utils import timezone

from .models import ReleveGeorisques
from .zonages_officiels import FRAICHEUR_JOURS, _attendre_son_tour

logger = logging.getLogger(__name__)

API = "https://georisques.gouv.fr/api/v1"

#: rubrique -> (chemin, libellé). Toutes prennent `code_insee` et rendent `{"data": [...]}`.
RUBRIQUES = {
    "risques": ("gaspar/risques", "Risques recensés"),
    "catnat": ("gaspar/catnat", "Arrêtés de catastrophe naturelle"),
    "azi": ("gaspar/azi", "Atlas des zones inondables"),
    "tri": ("gaspar/tri", "Territoire à risque important d'inondation"),
    "mvt": ("mvt", "Mouvements de terrain recensés"),
    "cavites": ("cavites", "Cavités souterraines recensées"),
    "radon": ("radon", "Potentiel radon"),
    "sismicite": ("zonage_sismique", "Zone de sismicité"),
}
PAGE = 100
MAX_PAGES = 5


def _interroger(chemin: str, commune_code: str) -> list:
    """Toutes les lignes de cette rubrique pour la commune (pages suivies, espacées). Lève en cas d'échec."""
    lignes, page = [], 1
    while page <= MAX_PAGES:
        params = urllib.parse.urlencode({"code_insee": commune_code, "page": page, "page_size": PAGE})
        requete = urllib.request.Request(f"{API}/{chemin}?{params}", headers={"Accept": "application/json"})
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            corps = json.loads(reponse.read().decode("utf-8"))
        lignes += corps.get("data") or []
        if page >= int(corps.get("total_pages") or 1):
            break
        page += 1
        _attendre_son_tour()
    return lignes


def relever_tout(commune_code: str, environment, forcer: bool = False, interroger=_interroger) -> dict:
    """Le relevé complet de la commune, d'un seul geste. Rend le bilan de chaque partie."""
    from . import plans_prevention, zonages_officiels

    limite = timezone.now() - datetime.timedelta(days=FRAICHEUR_JOURS)
    deja = {r.rubrique: r for r in ReleveGeorisques.objects.filter(commune_code=commune_code, environment=environment)}
    bilan = {"relevees": [], "ignorees": [], "erreurs": {}}
    for rubrique, (chemin, _libelle) in RUBRIQUES.items():
        if not forcer and rubrique in deja and deja[rubrique].releve_le > limite:
            bilan["ignorees"].append(rubrique)
            continue
        _attendre_son_tour()
        try:
            lignes = interroger(chemin, commune_code)
        except Exception as erreur:  # noqa: BLE001 -- une panne de leur côté n'efface pas un relevé
            bilan["erreurs"][rubrique] = str(erreur)[:200]
            continue
        ReleveGeorisques.objects.update_or_create(
            commune_code=commune_code, rubrique=rubrique, environment=environment, defaults={"donnees": lignes})
        bilan["relevees"].append(rubrique)
    _reporter_les_risques(commune_code, environment)
    bilan["zonages"] = zonages_officiels.relever(commune_code, environment, forcer=forcer)
    bilan["plans_prevention"] = plans_prevention.relever(commune_code, environment, forcer=forcer)
    # Le tracé et l'acte des plans de prévention ne sont pas chez Géorisques : ils sont au
    # Géoportail de l'urbanisme. Même geste, pour que l'écran ait tout d'un coup.
    from . import geoportail_urbanisme
    try:
        bilan["perimetres_ppr"] = geoportail_urbanisme.relever(commune_code, environment, forcer=forcer)
    except Exception as erreur:  # noqa: BLE001 -- ne doit pas faire échouer le reste du relevé
        logger.exception("Relevé des périmètres de plans de prévention : échec pour %s", commune_code)
        bilan["perimetres_ppr"] = {"releves": 0, "erreurs": {"general": str(erreur)[:200]}}
    return bilan


def _reporter_les_risques(commune_code: str, environment) -> None:
    """La page « Risques de la commune » propose ce que Géorisques recense : elle lit
    `Commune.risques_territoire`. On l'alimente depuis CE relevé, pour qu'il n'y ait plus deux
    appels pour la même donnée (l'ancien, dans geo_lookup, ne sert plus que de repli)."""
    from .models import Commune

    releve = ReleveGeorisques.objects.filter(commune_code=commune_code, rubrique="risques", environment=environment).first()
    if releve is None or not releve.donnees:
        return
    detail = (releve.donnees[0] or {}).get("risques_detail") or []
    commune, _ = Commune.objects.get_or_create(code=commune_code)
    commune.risques_territoire = [
        {"num_risque": r.get("num_risque"), "libelle_risque_long": r.get("libelle_risque_long")} for r in detail]
    commune.derniere_tentative_risques = timezone.now()
    commune.save(update_fields=["risques_territoire", "derniere_tentative_risques", "date_maj"])


def _date(texte):
    try:
        return datetime.datetime.strptime(str(texte), "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def etat(commune_code: str, environment) -> dict:
    """Ce que les écrans montrent : la copie en base, mise en forme. Aucun appel extérieur."""
    from . import plans_prevention, zonages_officiels

    releves = {r.rubrique: r for r in ReleveGeorisques.objects.filter(commune_code=commune_code, environment=environment)} \
        if commune_code else {}
    donnees = {rubrique: (releves[rubrique].donnees if rubrique in releves else None) for rubrique in RUBRIQUES}
    dates = [r.releve_le for r in releves.values()]

    catnat = sorted(donnees["catnat"] or [], key=lambda a: _date(a.get("date_debut_evt")) or datetime.date.min, reverse=True)
    sismicite = (donnees["sismicite"] or [{}])[0] if donnees["sismicite"] else {}
    radon = (donnees["radon"] or [{}])[0] if donnees["radon"] else {}
    return {
        "commune_code": commune_code,
        "releve": bool(releves),
        "releve_le": min(dates) if dates else None,
        "complet": len(releves) == len(RUBRIQUES),
        "rubriques": [{"code": code, "libelle": libelle, "relevee": code in releves,
                       "nombre": len(donnees[code]) if donnees[code] is not None else None}
                      for code, (_chemin, libelle) in RUBRIQUES.items()],
        "sismicite": sismicite.get("zone_sismicite") or "",
        "radon": {"1": "faible", "2": "moyen", "3": "significatif"}.get(str(radon.get("classe_potentiel") or ""), ""),
        "catnat": {
            "nombre": len(catnat),
            "derniers": [{"risque": a.get("libelle_risque_jo") or "", "debut": a.get("date_debut_evt") or "",
                          "fin": a.get("date_fin_evt") or "", "arrete": a.get("date_publication_arrete") or ""} for a in catnat[:8]],
        },
        "azi": [a.get("libelle_azi") or "" for a in donnees["azi"] or []],
        "tri": [{"nom": t.get("libelle_tri") or "",
                 "risques": [r.get("libelle_risque_long") or "" for r in t.get("liste_libelle_risque") or []]}
                for t in donnees["tri"] or []],
        "mouvements": [{"type": m.get("type") or "", "date": m.get("date_debut") or "", "lieu": m.get("commentaire_lieu") or m.get("lieu") or ""}
                       for m in (donnees["mvt"] or [])[:12]],
        "cavites": len(donnees["cavites"] or []),
        "zonages": zonages_officiels.etat(commune_code, environment),
        "plans_prevention": plans_prevention.etat(commune_code, environment),
        "perimetres_ppr": __import__("core.geoportail_urbanisme", fromlist=["etat"]).etat(commune_code, environment),
    }


def rapport_pdf(commune_code: str) -> bytes:
    """Le rapport « état des risques » de la commune, tel que Géorisques le fabrique (PDF).
    Demandé par le serveur : le navigateur de la personne n'interroge aucun service extérieur."""
    _attendre_son_tour()
    params = urllib.parse.urlencode({"code_insee": commune_code})
    requete = urllib.request.Request(f"{API}/rapport_pdf?{params}", headers={"Accept": "application/pdf"})
    with urllib.request.urlopen(requete, timeout=90) as reponse:
        contenu = reponse.read()
    if not contenu.startswith(b"%PDF-"):
        raise ValueError("Géorisques n'a pas rendu un PDF.")
    return contenu
