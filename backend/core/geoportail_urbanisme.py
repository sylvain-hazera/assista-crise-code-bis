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


# ── Toutes les autres servitudes, et les zones du PLU (22/11/2026) ──
#
# Vérifié à la main le 22/11/2026 autour du Haillan et de Mérignac : `assiette_sup_s` porte aussi
# les lignes électriques (i4), monuments historiques (ac1), cours d'eau (a4), voies ferrées (t1),
# halage (el3)… On prend ce que chaque gestionnaire a déposé, sans promettre davantage (ni gaz
# ni captage publiés sur cette emprise). `wfs_du:zone_urba` porte les zones des PLU et PLUi.

#: Libellés des catégories de servitudes d'utilité publique (nomenclature nationale).
LIBELLES_SERVITUDES = {
    "ac1": "Monuments historiques", "ac2": "Sites inscrits et classés", "ac4": "Sites patrimoniaux remarquables",
    "a4": "Cours d'eau (passage, entretien)", "a5": "Canalisations d'eau et d'assainissement",
    "as1": "Captages d'eau potable", "el3": "Halage et marchepied", "el7": "Alignement des voies",
    "el11": "Voies express et déviations", "i1": "Canalisations d'hydrocarbures", "i3": "Canalisations de gaz",
    "i4": "Lignes électriques", "i6": "Mines et carrières", "int1": "Voisinage des cimetières",
    "js1": "Installations sportives", "pm1": "Risques naturels ou miniers", "pm2": "Installations classées",
    "pm3": "Risques technologiques", "pt1": "Télécommunications (perturbations)", "pt2": "Télécommunications (obstacles)",
    "pt3": "Réseaux de télécommunications", "t1": "Voies ferrées", "t4": "Aérodromes (balisage)",
    "t5": "Aérodromes (dégagement)", "t7": "Hors des aérodromes (dégagement)",
}
MAX_SERVITUDES = 500
MAX_ZONES = 2000


def _wfs(couche: str, filtre: str, nombre: int) -> dict:
    params = urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": couche,
        "outputFormat": "application/json", "srsName": "EPSG:4326", "count": nombre, "cql_filter": filtre})
    requete = urllib.request.Request(f"{WFS}?{params}", headers={"Accept": "application/json"})
    derniere = None
    for tentative in range(2):
        if tentative:
            time.sleep(6)
        with urllib.request.urlopen(requete, timeout=90) as reponse:
            if "json" not in (reponse.headers.get("Content-Type") or "").lower():
                derniere = ValueError("Le service cartographique n'a pas rendu de données (réponse inattendue).")
                continue
            return json.loads(reponse.read().decode("utf-8"))
    raise derniere


def _boite(emprise) -> str:
    ouest, sud, est, nord = emprise
    return f"BBOX(the_geom,{ouest:.5f},{sud:.5f},{est:.5f},{nord:.5f},'EPSG:4326')"


def interroger_servitudes(emprise) -> dict:
    """Toutes les servitudes hors plans de prévention (relevés à part), en un appel."""
    exclues = ",".join(f"'{c}'" for c in CATEGORIES)
    return _wfs("wfs_sup:assiette_sup_s", f"suptype NOT IN ({exclues}) AND {_boite(emprise)}", MAX_SERVITUDES)


def interroger_zones(emprise) -> dict:
    return _wfs("wfs_du:zone_urba", _boite(emprise), MAX_ZONES)


def _formes_dans(reponse, contour):
    """Les objets dont la surface touche vraiment la commune (l'emprise est un rectangle)."""
    for objet in (reponse or {}).get("features") or []:
        try:
            surface = _surface(GEOSGeometry(json.dumps(objet.get("geometry")), srid=4326))
        except Exception:  # noqa: BLE001
            surface = None
        if surface is not None and surface.intersects(contour):
            yield objet.get("properties") or {}, surface


def _tronque(reponse, plafond) -> bool:
    n = (reponse or {}).get("numberMatched")
    return isinstance(n, int) and n > plafond


def relever_servitudes(commune_code: str, environment, contour, interroger=interroger_servitudes) -> dict:
    """Les servitudes autres que les plans de prévention. Une panne garde ce qu'on avait."""
    from .zonages_officiels import _attendre_son_tour

    _attendre_son_tour()
    try:
        reponse = interroger(contour.extent)
    except Exception as erreur:  # noqa: BLE001
        return {"releves": 0, "erreurs": {"servitudes": str(erreur)[:200]}}
    gardes = []
    for proprietes, surface in _formes_dans(reponse, contour):
        categorie = (proprietes.get("suptype") or "")[:5]
        if not categorie or categorie in CATEGORIES:
            continue
        gardes.append(ServitudePPR(
            commune_code=commune_code, environment=environment, categorie=categorie,
            identifiant=(proprietes.get("idass") or proprietes.get("idgen") or "")[:120],
            nom=(proprietes.get("nomsuplitt") or proprietes.get("nomass")
                 or LIBELLES_SERVITUDES.get(categorie, categorie.upper()))[:255],
            type_assiette=(proprietes.get("typeass") or "")[:120],
            fichier=(proprietes.get("fichier") or "")[:255],
            url_acte=adresse_de_l_acte(proprietes.get("partition") or "", proprietes.get("gpu_doc_id") or "",
                                       proprietes.get("fichier") or "")[:500] if proprietes.get("fichier") else "",
            polygone=surface,
        ))
    ServitudePPR.objects.filter(commune_code=commune_code, environment=environment).exclude(
        categorie__in=list(CATEGORIES)).delete()
    ServitudePPR.objects.bulk_create(gardes)
    bilan = {"releves": len(gardes), "erreurs": {}}
    if _tronque(reponse, MAX_SERVITUDES):
        bilan["erreurs"]["incomplet"] = f"plus de {MAX_SERVITUDES} servitudes sur l'emprise : liste tronquée"
    return bilan


def relever_zones(commune_code: str, environment, contour, interroger=interroger_zones) -> dict:
    """Les zones du document d'urbanisme (PLU, PLUi) qui touchent la commune."""
    from .models import ZoneUrbanisme
    from .zonages_officiels import _attendre_son_tour

    _attendre_son_tour()
    try:
        reponse = interroger(contour.extent)
    except Exception as erreur:  # noqa: BLE001
        return {"releves": 0, "erreurs": {"zones": str(erreur)[:200]}}
    gardes = [ZoneUrbanisme(
        commune_code=commune_code, environment=environment, type_zone=(p.get("typezone") or "")[:10],
        libelle=(p.get("libelle") or "")[:120], libelle_long=(p.get("libelong") or "")[:255],
        url_reglement=(p.get("urlfic") or "")[:500] if str(p.get("urlfic") or "").startswith("http") else "",
        polygone=surface) for p, surface in _formes_dans(reponse, contour)]
    ZoneUrbanisme.objects.filter(commune_code=commune_code, environment=environment).delete()
    ZoneUrbanisme.objects.bulk_create(gardes)
    bilan = {"releves": len(gardes), "erreurs": {}}
    if _tronque(reponse, MAX_ZONES):
        bilan["erreurs"]["incomplet"] = f"plus de {MAX_ZONES} zones sur l'emprise : liste tronquée"
    return bilan


def servitudes_etat(commune_code: str, environment) -> list:
    """Les autres servitudes de la commune, par catégorie, pour la page « Risques de la commune » :
    leur nombre, quelques noms et les actes (22/11/2026)."""
    if not commune_code:
        return []
    par_categorie = {}
    for s in (ServitudePPR.objects.filter(commune_code=commune_code, environment=environment)
              .exclude(categorie__in=list(CATEGORIES)).order_by("categorie", "nom")):
        ligne = par_categorie.setdefault(s.categorie, {
            "categorie": s.categorie, "libelle": LIBELLES_SERVITUDES.get(s.categorie, s.categorie.upper()),
            "nombre": 0, "actes": []})
        ligne["nombre"] += 1
        if s.url_acte and s.url_acte not in [a["url"] for a in ligne["actes"]] and len(ligne["actes"]) < 3:
            ligne["actes"].append({"nom": s.nom, "url": s.url_acte})
    return sorted(par_categorie.values(), key=lambda l: l["libelle"])


def etat(commune_code: str, environment) -> list:
    """Les plans relevés pour la commune, pour l'écran : leur nom, ce qu'ils couvrent, leur acte."""
    return [{"nom": s.nom, "categorie": CATEGORIES.get(s.categorie, s.categorie), "type_assiette": s.type_assiette,
             "fichier": s.fichier, "url_acte": s.url_acte, "releve_le": s.releve_le}
            for s in ServitudePPR.objects.filter(commune_code=commune_code, environment=environment,
                                                 categorie__in=list(CATEGORIES)).order_by("nom")
            ] if commune_code else []


def plans_au_point(point, commune_code: str, environment) -> list:
    """Les plans de prévention dont le périmètre contient ce point."""
    return list(ServitudePPR.objects.filter(commune_code=commune_code, environment=environment, polygone__contains=point,
                                            categorie__in=list(CATEGORIES))
                .values_list("nom", flat=True)) if point is not None else []
