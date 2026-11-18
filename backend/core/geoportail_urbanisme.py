"""Les plans de prévention des risques tels que le Géoportail de l'urbanisme les publie : leur
périmètre, et l'adresse de leur acte (le règlement, en PDF) — 18/11/2026.

Géorisques dit QUELS plans couvrent une commune (core/plans_prevention.py) mais n'en publie ni
le tracé ni les documents. Ceux-ci sont des servitudes d'utilité publique, catégories PM1 (plans
de prévention des risques naturels et miniers) et PM3 (risques technologiques), déposées au
Géoportail de l'urbanisme et servies par le service cartographique de l'IGN.

Vérifié à la main le 18/11/2026 avant d'être écrit ici — pas d'adaptateur sur des suppositions :

- `data.geopf.fr/wfs/ows`, couche `wfs_sup:assiette_sup_s`, filtrée par catégorie et par emprise,
  rend pour une commune réelle ses deux plans (inondation et minier), chacun avec sa surface
  (« enveloppe des zonages réglementaires »), le nom du plan, celui du fichier de l'acte, la
  partition et l'identifiant du document ;
- l'acte se lit à `data.geopf.fr/annexes/gpu/documents/<partition>/<document>/<fichier>`.

**L'acte n'est pas recopié chez nous** : celui d'un plan d'inondation de vallée pèse plus de
100 Mo. On garde son adresse ; c'est un document public de l'État, que la personne ouvre
elle-même d'un clic. Le périmètre, lui, est gardé en base : c'est lui qu'on montre sur la carte.

Appelé par le relevé unique (core/releve_georisques.py), avec les mêmes pauses.
"""
import json
import logging
import time
import urllib.parse
import urllib.request

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon

from .models import ServitudePPR

logger = logging.getLogger(__name__)

WFS = "https://data.geopf.fr/wfs/ows"
ANNEXES = "https://data.geopf.fr/annexes/gpu/documents"
#: catégorie de servitude -> ce qu'elle couvre.
CATEGORIES = {"pm1": "Risques naturels ou miniers", "pm3": "Risques technologiques"}
MAX_OBJETS = 60


def contour_de_la_commune(commune_code: str):
    """Le contour de la commune (geo.api.gouv.fr), en géométrie. None s'il ne se lit pas."""
    url = f"https://geo.api.gouv.fr/communes/{urllib.parse.quote(commune_code)}?fields=contour"
    try:
        with urllib.request.urlopen(url, timeout=15) as reponse:
            contour = json.loads(reponse.read().decode("utf-8")).get("contour")
        return GEOSGeometry(json.dumps(contour), srid=4326) if contour else None
    except Exception:  # noqa: BLE001
        logger.warning("Contour de la commune %s illisible.", commune_code)
        return None


def _interroger(categorie: str, emprise) -> list:
    """Les surfaces de servitude de cette catégorie dans l'emprise (lon/lat). Lève en cas d'échec."""
    ouest, sud, est, nord = emprise
    filtre = f"suptype='{categorie}' AND BBOX(the_geom,{ouest:.5f},{sud:.5f},{est:.5f},{nord:.5f},'EPSG:4326')"
    params = urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": "wfs_sup:assiette_sup_s",
        "outputFormat": "application/json", "srsName": "EPSG:4326", "count": MAX_OBJETS, "cql_filter": filtre})
    requete = urllib.request.Request(f"{WFS}?{params}", headers={"Accept": "application/json"})
    # Constaté le 18/11/2026 : le service rend parfois, avec un code 200, une page qui n'a rien
    # à voir (des métriques internes). On réessaie une fois, puis on lève : `relever` garde
    # alors ce qu'on avait.
    derniere = None
    for tentative in range(2):
        if tentative:
            time.sleep(6)
        with urllib.request.urlopen(requete, timeout=60) as reponse:
            if "json" not in (reponse.headers.get("Content-Type") or "").lower():
                derniere = ValueError("Le service cartographique n'a pas rendu de données (réponse inattendue).")
                continue
            return json.loads(reponse.read().decode("utf-8")).get("features") or []
    raise derniere


def adresse_de_l_acte(partition: str, document: str, fichier: str) -> str:
    if not (partition and document and fichier):
        return ""
    return f"{ANNEXES}/{urllib.parse.quote(partition)}/{urllib.parse.quote(document)}/{urllib.parse.quote(fichier)}"


def _surface(geometrie):
    """Une surface multiple valide, ou None."""
    if geometrie is None:
        return None
    if isinstance(geometrie, Polygon):
        geometrie = MultiPolygon(geometrie, srid=4326)
    if not isinstance(geometrie, MultiPolygon) or geometrie.empty:
        return None
    return geometrie


def relever(commune_code: str, environment, forcer: bool = False, interroger=_interroger, contour=None) -> dict:
    """Relève les plans de prévention qui touchent la commune : périmètre et adresse de l'acte.
    Rend `{"releves": n, "erreurs": {catégorie: message}}`. Une catégorie en panne garde ce
    qu'on avait ; une catégorie relevée remplace ses lignes."""
    from .zonages_officiels import _attendre_son_tour

    bilan = {"releves": 0, "erreurs": {}}
    contour = contour if contour is not None else contour_de_la_commune(commune_code)
    if contour is None:
        bilan["erreurs"]["contour"] = "Le contour de la commune n'a pas pu être lu."
        return bilan
    for categorie in CATEGORIES:
        _attendre_son_tour()
        try:
            objets = interroger(categorie, contour.extent)
        except Exception as erreur:  # noqa: BLE001
            bilan["erreurs"][categorie] = str(erreur)[:200]
            continue
        gardes = []
        for objet in objets:
            proprietes = objet.get("properties") or {}
            try:
                surface = _surface(GEOSGeometry(json.dumps(objet.get("geometry")), srid=4326))
            except Exception:  # noqa: BLE001
                surface = None
            # L'emprise est un rectangle : on ne garde que ce qui touche vraiment la commune.
            if surface is None or not surface.intersects(contour):
                continue
            gardes.append(ServitudePPR(
                commune_code=commune_code, environment=environment, categorie=categorie,
                identifiant=(proprietes.get("idass") or proprietes.get("idgen") or "")[:120],
                nom=(proprietes.get("nomsuplitt") or proprietes.get("nomass") or "Plan de prévention")[:255],
                type_assiette=(proprietes.get("typeass") or "")[:120],
                fichier=(proprietes.get("fichier") or "")[:255],
                url_acte=adresse_de_l_acte(proprietes.get("partition") or "", proprietes.get("gpu_doc_id") or "",
                                           proprietes.get("fichier") or "")[:500],
                polygone=surface,
            ))
        ServitudePPR.objects.filter(commune_code=commune_code, environment=environment, categorie=categorie).delete()
        ServitudePPR.objects.bulk_create(gardes)
        bilan["releves"] += len(gardes)
    return bilan


def etat(commune_code: str, environment) -> list:
    """Les plans relevés pour la commune, pour l'écran : leur nom, ce qu'ils couvrent, leur acte."""
    return [{"nom": s.nom, "categorie": CATEGORIES.get(s.categorie, s.categorie), "type_assiette": s.type_assiette,
             "fichier": s.fichier, "url_acte": s.url_acte, "releve_le": s.releve_le}
            for s in ServitudePPR.objects.filter(commune_code=commune_code, environment=environment).order_by("nom")
            ] if commune_code else []


def plans_au_point(point, commune_code: str, environment) -> list:
    """Les plans de prévention dont le périmètre contient ce point."""
    return list(ServitudePPR.objects.filter(commune_code=commune_code, environment=environment, polygone__contains=point)
                .values_list("nom", flat=True)) if point is not None else []
