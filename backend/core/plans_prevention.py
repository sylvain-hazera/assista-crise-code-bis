"""Les plans de prévention des risques (PPR) de la commune, relevés auprès de Géorisques.

Un PPR est le document réglementaire de l'État qui dit où l'on ne construit pas et à quelles
conditions : c'est la référence du volet « risques » d'un plan communal de sauvegarde, et le
maire doit savoir lesquels couvrent sa commune, s'ils sont en révision, et quelles zones leur
règlement distingue.

**Ce que Géorisques sert, et ce qu'il ne sert pas** (vérifié sur leur description d'API et sur
une réponse réelle le 17/11/2026) : la liste des procédures par commune, pour les plans naturels
(`pprn`), technologiques (`pprt`) et miniers (`pprm`), avec les TYPES de zones de leur règlement
(« Rouge — interdiction », « Bleu — prescriptions »…). Il ne sert **pas le tracé** de ces zones :
celui-ci reste dans le dossier du plan, en préfecture et sur le Géoportail de l'urbanisme. On
n'invente donc aucune zone sur la carte.

Même discipline que `zonages_officiels` : relevé à la demande d'un agent, gardé en base, requêtes
espacées (le délai est partagé avec les autres appels à Géorisques), pas refait avant
`FRAICHEUR_JOURS`, et une panne de leur côté n'efface pas ce qu'on avait.
"""
import datetime
import json
import urllib.parse
import urllib.request

from django.utils import timezone

from .models import ProcedurePPR, RelevePPR
from .zonages_officiels import FRAICHEUR_JOURS, _attendre_son_tour

API = "https://www.georisques.gouv.fr/api/v1/gaspar"
FAMILLES = {
    "pprn": "Risques naturels",
    "pprt": "Risques technologiques",
    "pprm": "Risques miniers",
}
PAGE = 50


def _interroger(famille: str, commune_code: str) -> list:
    """Les procédures de cette famille pour la commune. Lève en cas d'échec."""
    params = urllib.parse.urlencode({"codeInsee": commune_code, "page": 1, "page_size": PAGE})
    requete = urllib.request.Request(f"{API}/{famille}?{params}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        return json.loads(reponse.read().decode("utf-8")).get("content") or []


def _date(texte):
    """« 17/02/2025 » → date, ou None."""
    try:
        return datetime.datetime.strptime(str(texte), "%d/%m/%Y").date()
    except (TypeError, ValueError):
        return None


def relever(commune_code: str, environment, forcer: bool = False, interroger=_interroger) -> dict:
    """Relève les plans de la commune, une requête par famille, espacées.
    Rend `{"relevees": [...], "ignorees": [...], "erreurs": {famille: message}}`."""
    limite = timezone.now() - datetime.timedelta(days=FRAICHEUR_JOURS)
    deja = {r.famille: r for r in RelevePPR.objects.filter(commune_code=commune_code, environment=environment)}
    bilan = {"relevees": [], "ignorees": [], "erreurs": {}}
    for famille in FAMILLES:
        if not forcer and famille in deja and deja[famille].releve_le > limite:
            bilan["ignorees"].append(famille)
            continue
        _attendre_son_tour()
        try:
            procedures = interroger(famille, commune_code)
        except Exception as erreur:
            # On garde ce qu'on avait : une panne de leur côté n'efface pas un relevé.
            bilan["erreurs"][famille] = str(erreur)[:200]
            continue
        garder(commune_code, famille, environment, procedures)
        bilan["relevees"].append(famille)
    return bilan


def garder(commune_code: str, famille: str, environment, procedures: list) -> None:
    """Remplace ce qu'on savait de cette famille par ce que Géorisques vient de rendre."""
    vus = []
    for brute in procedures:
        identifiant = str(brute.get("idGaspar") or "").strip()
        if not identifiant:
            continue
        zonage = brute.get("zonageReglementaire") or {}
        zones = [
            {"nom": str(z.get("codeZone") or z.get("nom") or "").strip()[:80],
             "regle": str(z.get("libelle") or "").strip()[:80]}
            for z in (zonage.get("listTypeReg") or [])
        ]
        ProcedurePPR.objects.update_or_create(
            commune_code=commune_code, id_gaspar=identifiant, environment=environment,
            defaults={
                "famille": famille,
                "libelle": str(brute.get("libPpr") or "").strip()[:255],
                "modele": str(brute.get("modeleProcedure") or "").strip()[:40],
                "bassin": str(brute.get("libBassinRisques") or "").strip()[:255],
                "en_revision": bool(brute.get("etatRevision")),
                "zonage_existe": bool(zonage.get("zoneRegExists")),
                "zones": [z for z in zones if z["nom"]],
                "modifie_le": _date(brute.get("dateModification")),
            },
        )
        vus.append(identifiant)
    # Une procédure que Géorisques ne rend plus pour cette commune n'y est plus.
    ProcedurePPR.objects.filter(
        commune_code=commune_code, famille=famille, environment=environment,
    ).exclude(id_gaspar__in=vus).delete()
    RelevePPR.objects.update_or_create(commune_code=commune_code, famille=famille, environment=environment)


def etat(commune_code: str, environment) -> dict:
    """Ce qu'on sait des plans de la commune, pour l'écran et le document du plan."""
    if not commune_code:
        return {"releve": False, "releve_le": None, "complet": False, "plans": []}
    releves = list(RelevePPR.objects.filter(commune_code=commune_code, environment=environment))
    plans = ProcedurePPR.objects.filter(commune_code=commune_code, environment=environment).order_by("famille", "libelle")
    return {
        "releve": bool(releves),
        "releve_le": min((r.releve_le for r in releves), default=None),
        "complet": len(releves) == len(FAMILLES),
        "plans": [
            {
                "id_gaspar": p.id_gaspar, "famille": FAMILLES.get(p.famille, p.famille),
                "libelle": p.libelle, "modele": p.modele, "bassin": p.bassin,
                "en_revision": p.en_revision, "zonage_existe": p.zonage_existe, "zones": p.zones,
                "modifie_le": p.modifie_le,
            }
            for p in plans
        ],
    }
