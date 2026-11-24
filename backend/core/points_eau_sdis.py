"""Import d'un fichier de points d'eau incendie fourni par un SDIS (24/11/2026).

Format attendu : le schéma national `datakode/schema-pei` 1.0.1 (schema.data.gouv.fr), en CSV
(séparateur « ; » ou « , ») ou en GeoJSON (les mêmes champs dans `properties`). Coordonnées :
`lon`/`lat` (WGS 84) si elles sont données, sinon `x`/`y` en Lambert 93 (EPSG:2154), convertis
ici ; à défaut, la géométrie du GeoJSON.

Un import vaut pour UN département : il remplace les points SDIS de ce département (mis à jour
par `id_sdis`, les absents supprimés) et ne touche à rien d'autre — ni aux autres
départements, ni aux points OSM, ni aux points validés par les communes. Les états posés par un
signalement validé (`etat_terrain`) survivent à l'import.

Réservé à l'administrateur. Les lignes refusées sont rendues une à une, avec la raison.
"""
import csv
import datetime
import io
import json
import logging

from django.contrib.gis.geos import GEOSGeometry, Point
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

TAILLE_MAX = 60 * 1024 * 1024
TYPES = {"PI", "BI", "PA", "CI"}
SOURCES = {"citerne", "plan_eau", "piscine", "puits", "cours_eau", "reseau_aep", "reseau_irrigation",
           "reseau_brute"}
REFUS_MAX = 200


def _texte(valeur):
    return " ".join(str(valeur if valeur is not None else "").split())


def _nombre(valeur):
    texte = _texte(valeur).replace(",", ".")
    if not texte:
        return None
    try:
        return float(texte)
    except ValueError:
        return None


def _date(valeur):
    texte = _texte(valeur)[:10]
    if not texte:
        return None
    for forme in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(texte, forme).date()
        except ValueError:
            continue
    return None


def _booleen(valeur):
    texte = _texte(valeur).lower()
    if texte in ("1", "true", "vrai", "oui", "t", "o", "di", "disponible"):
        return True
    if texte in ("0", "false", "faux", "non", "f", "n", "in", "indisponible"):
        return False
    return None


def lignes_du_fichier(contenu, nom=""):
    """Octets du fichier → liste de dictionnaires (champs du schéma, en minuscules)."""
    if len(contenu) > TAILLE_MAX:
        raise ValueError("Fichier trop volumineux (60 Mo au plus).")
    texte = None
    for codage in ("utf-8-sig", "cp1252"):
        try:
            texte = contenu.decode(codage)
            break
        except UnicodeDecodeError:
            continue
    if texte is None:
        raise ValueError("Encodage du fichier illisible (UTF-8 attendu).")
    debut = texte.lstrip()[:1]
    if nom.lower().endswith((".geojson", ".json")) or debut == "{":
        donnees = json.loads(texte)
        lignes = []
        for entite in donnees.get("features", []):
            proprietes = {str(k).lower(): v for k, v in (entite.get("properties") or {}).items()}
            if entite.get("geometry"):
                proprietes["_geometrie"] = entite["geometry"]
            lignes.append(proprietes)
        return lignes
    premiere = texte.splitlines()[0] if texte else ""
    separateur = ";" if premiere.count(";") >= premiere.count(",") else ","
    return [{str(k).strip().lower(): v for k, v in ligne.items() if k}
            for ligne in csv.DictReader(io.StringIO(texte), delimiter=separateur)]


def position(ligne):
    """(Point WGS 84 ou None, raison du refus)."""
    lon, lat = _nombre(ligne.get("lon") or ligne.get("lng") or ligne.get("longitude")), _nombre(ligne.get("lat") or ligne.get("latitude"))
    if lon is not None and lat is not None:
        if -180 <= lon <= 180 and -90 <= lat <= 90:
            return Point(lon, lat, srid=4326), ""
        return None, "lon/lat hors des bornes"
    x, y = _nombre(ligne.get("x")), _nombre(ligne.get("y"))
    if x is not None and y is not None:
        if not (0 < x < 1_400_000 and 6_000_000 < y < 7_200_000):
            return None, "x/y hors de la France métropolitaine en Lambert 93"
        point = Point(x, y, srid=2154)
        point.transform(4326)
        return point, ""
    if ligne.get("_geometrie"):
        try:
            geometrie = GEOSGeometry(json.dumps(ligne["_geometrie"]), srid=4326)
        except Exception:   # noqa: BLE001 - géométrie illisible, ligne refusée
            return None, "géométrie illisible"
        if geometrie.geom_type == "Point":
            return geometrie, ""
        return geometrie.centroid, ""
    return None, "ni lon/lat, ni x/y, ni géométrie"


def lire(lignes):
    """Lignes du schéma → (points {id: champs}, refus [(numéro, raison)])."""
    points, refus = {}, []
    for numero, ligne in enumerate(lignes, start=2):
        insee = _texte(ligne.get("insee"))
        type_pei = _texte(ligne.get("type_pei")).upper()
        if not insee:
            refus.append((numero, "insee manquant"))
            continue
        if type_pei not in TYPES:
            refus.append((numero, f"type_pei « {type_pei or 'vide'} » : attendu PI, BI, PA ou CI"))
            continue
        point, raison = position(ligne)
        if point is None:
            refus.append((numero, raison))
            continue
        ref_terr = _texte(ligne.get("ref_terr"))
        identifiant = (_texte(ligne.get("id_sdis")) or _texte(ligne.get("id_gestion"))
                       or (f"{insee}-{ref_terr}" if ref_terr else ""))
        if not identifiant:
            identifiant = f"{insee}-{point.x:.6f}-{point.y:.6f}"
        source = _texte(ligne.get("source_pei")).lower()
        diametre = _nombre(ligne.get("diam_pei"))
        statut = _texte(ligne.get("statut")).lower()
        points[identifiant[:64]] = {
            "insee": insee[:10], "type_pei": type_pei, "type_rd": _texte(ligne.get("type_rd"))[:60],
            "source_eau": source if source in SOURCES else "",
            "diametre": int(diametre) if diametre and 0 < diametre < 1000 else None,
            "debit": _nombre(ligne.get("debit")), "volume": _nombre(ligne.get("volume")),
            "pression": _nombre(ligne.get("press_stat")),
            "statut": statut if statut in ("public", "prive") else "",
            "nom_etab": _texte(ligne.get("nom_etab"))[:200],
            "ref_terrain": _texte(ligne.get("ref_terr"))[:40],
            "gestionnaire": _texte(ligne.get("nom_gest"))[:120],
            "disponible": _booleen(ligne.get("disponible")),
            "date_dispo": _date(ligne.get("date_dispo")), "date_controle": _date(ligne.get("date_ct")),
            "location": point,
        }
    return points, refus


def importer(departement, contenu, nom="", maintenant=None):
    """Remplace les points SDIS d'un département par ceux du fichier. Rend un rapport."""
    from .models import PointEauIncendie, ReleveDepartementPEI, SourcePEI
    from .points_eau_osm import DEPARTEMENTS

    if departement not in DEPARTEMENTS:
        raise ValueError("Département inconnu.")
    maintenant = maintenant or timezone.now()
    points, refus = lire(lignes_du_fichier(contenu, nom))
    if not points:
        raise ValueError("Aucune ligne utilisable dans le fichier." + (f" Première raison : {refus[0][1]}." if refus else ""))
    with transaction.atomic():
        existants = {p.ref_source: p for p in PointEauIncendie.objects.filter(source=SourcePEI.SDIS, departement_code=departement)}
        nouveaux = []
        for identifiant, champs in points.items():
            point = existants.pop(identifiant, None)
            if point is None:
                nouveaux.append(PointEauIncendie(source=SourcePEI.SDIS, ref_source=identifiant,
                                                 departement_code=departement, releve_le=maintenant, **champs))
                continue
            for champ, valeur in champs.items():
                setattr(point, champ, valeur)
            point.releve_le = maintenant
            point.save()
        PointEauIncendie.objects.bulk_create(nouveaux, batch_size=1000)
        supprimes = len(existants)
        PointEauIncendie.objects.filter(pk__in=[p.pk for p in existants.values()]).delete()
        etat, _ = ReleveDepartementPEI.objects.get_or_create(departement_code=departement)
        etat.sdis_importe_le, etat.sdis_nombre = maintenant, len(points)
        etat.save(update_fields=["sdis_importe_le", "sdis_nombre"])
    return {"departement": departement, "importes": len(points), "nouveaux": len(nouveaux),
            "supprimes": supprimes, "refuses": len(refus),
            "refus": [{"ligne": n, "raison": r} for n, r in refus[:REFUS_MAX]]}
