"""Sortir les couches de la carte, et faire entrer celles que la commune a déjà.

Une commune qui a un service d'information géographique, ou un bureau d'études qui lui a remis
des fichiers, ne doit ni redessiner ses quartiers à la main ici, ni rester prisonnière de ce
qu'elle a saisi ici. Les couches sortent et entrent en **GeoJSON**, le format que tous les
logiciels de cartographie lisent et écrivent sans réglage (QGIS, ArcGIS, geojson.io,
uMap) : coordonnées en longitude et latitude (WGS 84), comme le veut la norme.

**Ce qui sort** : les quartiers, les sites sensibles retenus au plan, les lieux et points des
dispositifs, les zones inondées simulées par niveau d'eau, les zones inondables officielles
relevées, et les enjeux avec le niveau d'eau qui les atteint.

**Ce qui ne sort jamais** : le registre des personnes vulnérables. Ni leurs adresses, ni leurs
secteurs. Un fichier de cartographie se copie, s'envoie, se retrouve sur une clé.

**Ce qui entre** : les quartiers (des polygones nommés). L'import commence toujours par un
aperçu qui ne crée rien, et ne remplace jamais un quartier existant sans qu'on le demande.
Beaucoup de fichiers français sont en Lambert 93 plutôt qu'en longitude et latitude : on le
reconnaît et on convertit, plutôt que de placer la commune au large du golfe de Guinée.
"""
import json

from django.contrib.gis.geos import GEOSGeometry

from .models import (
    PalierInondationSimule,
    Plan,
    StatutSiteSensible,
    SuiviSiteSensible,
    Zone,
    ZonageOfficiel,
)

#: Zone créée d'office avec la collectivité : ce n'est pas un quartier dessiné.
ZONE_AUTOMATIQUE = "Mon territoire"
MAX_OBJETS = 300
MAX_OCTETS = 5 * 1024 * 1024
#: Propriétés où l'on cherche le nom d'un quartier, dans l'ordre.
_CLES_DU_NOM = ("nom", "name", "libelle", "quartier", "nom_quartier", "label", "titre", "title")

COUCHES = {
    "quartiers": "Quartiers et zones de la commune",
    "sites-sensibles": "Sites sensibles retenus au plan",
    "points-du-plan": "Lieux d'accueil et points des dispositifs",
    "inondation-simulee": "Zones inondées simulées, par niveau d'eau",
    "zonages-officiels": "Zones inondables officielles (Géorisques)",
    "perimetres-ppr": "Périmètres des plans de prévention des risques (Géoportail de l'urbanisme)",
    "servitudes": "Servitudes d'utilité publique : réseaux, patrimoine, transports (Géoportail de l'urbanisme)",
    "zones-urbanisme": "Zones du plan local d'urbanisme (Géoportail de l'urbanisme)",
    "enjeux-exposes": "Enjeux et niveau d'eau qui les atteint",
}


def _objet(geometrie, **proprietes) -> dict:
    return {"type": "Feature", "geometry": json.loads(geometrie.geojson),
            "properties": {cle: valeur for cle, valeur in proprietes.items() if valeur not in (None, "")}}


def _quartiers(institution, environment):
    zones = (Zone.objects.filter(institution=institution, environment=environment, actif=True)
             .exclude(zone_precise__isnull=True).exclude(nom=ZONE_AUTOMATIQUE))
    return [_objet(z.zone_precise, nom=z.nom, description=z.description or "") for z in zones]


def _sites(institution, environment):
    suivis = (SuiviSiteSensible.objects
              .filter(institution=institution, environment=environment, statut=StatutSiteSensible.RETENU)
              .select_related("site"))
    return [_objet(s.site.location, nom=s.site.nom, categorie=s.site.get_categorie_display(),
                   adresse=s.site.adresse or "", effectif=s.site.effectif_estime)
            for s in suivis if s.site.location is not None]


def _points(institution, environment):
    points = {}
    for plan in Plan.objects.filter(institution=institution, environment=environment, actif=True).prefetch_related("points__type"):
        for point in plan.points.all():
            if point.location is not None:
                points.setdefault(point.id, (point, []))[1].append(plan.nom)
    return [_objet(p.location, nom=p.nom, type=p.type.libelle if p.type_id else "",
                   capacite=p.capacite_accueil, dispositifs=", ".join(sorted(plans)))
            for p, plans in points.values()]


def _inondation(institution, environment):
    paliers = (PalierInondationSimule.objects
               .filter(commune_code=institution.commune_code or "", environment=environment)
               .exclude(polygone__isnull=True).order_by("niveau_metres"))
    return [_objet(p.polygone, niveau_m=p.niveau_metres,
                   nature="simulation : niveau d'eau étendu sur le relief, sans digues ni courant")
            for p in paliers if not p.polygone.empty]


def _zonages(institution, environment):
    from .habitations import COUCHES_GEORISQUES

    zonages = ZonageOfficiel.objects.filter(
        commune_code=institution.commune_code or "", environment=environment).exclude(polygone__isnull=True)
    return [_objet(z.polygone, scenario=COUCHES_GEORISQUES.get(z.couche, z.couche), couche=z.couche,
                   source="Géorisques", releve_le=z.releve_le.date().isoformat()) for z in zonages]


from .geoportail_urbanisme import CATEGORIES as CATEGORIES_PPR  # noqa: E402


def _perimetres_ppr(institution, environment):
    from .models import ServitudePPR

    return [_objet(s.polygone, nom=s.nom, type=s.type_assiette, acte=s.url_acte, source="Géoportail de l'urbanisme",
                   releve_le=s.releve_le.date().isoformat())
            for s in ServitudePPR.objects.filter(commune_code=institution.commune_code or "", environment=environment,
                                                 categorie__in=list(CATEGORIES_PPR))]


def _servitudes(institution, environment):
    from .geoportail_urbanisme import LIBELLES_SERVITUDES
    from .models import ServitudePPR

    return [_objet(s.polygone, nom=s.nom, categorie=LIBELLES_SERVITUDES.get(s.categorie, s.categorie.upper()),
                   type=s.type_assiette, acte=s.url_acte, source="Géoportail de l'urbanisme",
                   releve_le=s.releve_le.date().isoformat())
            for s in ServitudePPR.objects.filter(commune_code=institution.commune_code or "", environment=environment)
            .exclude(categorie__in=list(CATEGORIES_PPR))]


def _zones_urbanisme(institution, environment):
    from .models import ZoneUrbanisme

    return [_objet(z.polygone, type=z.type_zone, nom=z.libelle, description=z.libelle_long, reglement=z.url_reglement,
                   source="Géoportail de l'urbanisme", releve_le=z.releve_le.date().isoformat())
            for z in ZoneUrbanisme.objects.filter(commune_code=institution.commune_code or "", environment=environment)]


def _enjeux(institution, environment):
    from . import enjeux_exposes, zonages_officiels

    commune_code = institution.commune_code or ""
    paliers = enjeux_exposes.paliers_de(commune_code, environment) if commune_code else []
    zonages = zonages_officiels.en_base(commune_code, environment) if commune_code else {}
    objets = []
    for objet in _sites(institution, environment) + _points(institution, environment):
        point = GEOSGeometry(json.dumps(objet["geometry"]), srid=4326)
        seuil = enjeux_exposes.seuil_d_un_point(point, paliers)
        if seuil is not None:
            objet["properties"]["atteint_a_partir_de_m"] = seuil
        zone = zonages_officiels.zone_d_un_point(point, zonages)
        if zone:
            objet["properties"]["zone_officielle"] = zone
        objets.append(objet)
    return objets


_EXPORTS = {"quartiers": _quartiers, "sites-sensibles": _sites, "points-du-plan": _points,
            "inondation-simulee": _inondation, "zonages-officiels": _zonages, "perimetres-ppr": _perimetres_ppr, "enjeux-exposes": _enjeux,
            "servitudes": _servitudes, "zones-urbanisme": _zones_urbanisme}


def exporter(couche: str, institution, environment) -> dict:
    """La couche en GeoJSON (WGS 84). `name` est le nom que les logiciels donnent au calque."""
    return {"type": "FeatureCollection", "name": COUCHES[couche], "features": _EXPORTS[couche](institution, environment)}


def inventaire(institution, environment) -> list[dict]:
    """Ce qu'il y a à sortir, couche par couche."""
    return [{"couche": couche, "libelle": libelle, "objets": len(_EXPORTS[couche](institution, environment))}
            for couche, libelle in COUCHES.items()]


# ─────────────────────────────── import des quartiers ───────────────────────────────

class FichierIllisible(ValueError):
    """Le fichier n'est pas une couche qu'on sait lire ; le message dit pourquoi, pour l'agent."""


def _premier_point(coordonnees):
    while isinstance(coordonnees, list) and coordonnees and isinstance(coordonnees[0], list):
        coordonnees = coordonnees[0]
    return coordonnees if isinstance(coordonnees, list) and len(coordonnees) >= 2 else None


def _systeme(donnees: dict, objets: list) -> int:
    """4326 (longitude, latitude) ou 2154 (Lambert 93). La norme GeoJSON ne connaît que le
    premier, mais les fichiers français sont souvent dans le second, parfois sans le dire."""
    nom = json.dumps(donnees.get("crs") or "")
    if "2154" in nom:
        return 2154
    for objet in objets:
        point = _premier_point(((objet.get("geometry") or {}).get("coordinates")))
        if point:
            if abs(point[0]) <= 180 and abs(point[1]) <= 90:
                return 4326
            if 0 < point[0] < 1_400_000 and 6_000_000 < point[1] < 7_200_000:
                return 2154
            raise FichierIllisible(
                "Les coordonnées de ce fichier ne sont ni des longitudes et latitudes (WGS 84), ni du Lambert 93. "
                "Réexportez la couche en WGS 84 (EPSG:4326) depuis votre logiciel de cartographie.")
    return 4326


def _nom_de(proprietes: dict, rang: int) -> str:
    minuscules = {str(cle).lower(): valeur for cle, valeur in (proprietes or {}).items()}
    for cle in _CLES_DU_NOM:
        valeur = minuscules.get(cle)
        if valeur not in (None, ""):
            return str(valeur).strip()[:255]
    return f"Quartier importé {rang}"


def lire_quartiers(contenu) -> list[dict]:
    """Les quartiers d'un fichier GeoJSON : `[{"nom", "polygone" (GEOS, 4326), "remarque"}]`.
    Lève `FichierIllisible` avec un message pour l'agent."""
    if isinstance(contenu, (bytes, bytearray)):
        if len(contenu) > MAX_OCTETS:
            raise FichierIllisible("Ce fichier dépasse 5 Mo : simplifiez les contours avant de l'importer.")
        try:
            contenu = contenu.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise FichierIllisible("Ce fichier n'est pas du texte : attendez-vous un GeoJSON (et non un shapefile) ?") from exc
    try:
        donnees = json.loads(contenu) if isinstance(contenu, str) else contenu
    except ValueError as exc:
        raise FichierIllisible(
            "Ce fichier n'est pas un GeoJSON. Depuis QGIS : clic droit sur la couche, Exporter, format GeoJSON.") from exc
    if not isinstance(donnees, dict):
        raise FichierIllisible("Ce fichier n'est pas un GeoJSON.")
    if donnees.get("type") == "FeatureCollection":
        objets = donnees.get("features") or []
    elif donnees.get("type") == "Feature":
        objets = [donnees]
    else:
        raise FichierIllisible("Ce GeoJSON ne contient pas de liste d'objets (FeatureCollection).")
    if len(objets) > MAX_OBJETS:
        raise FichierIllisible(f"Ce fichier contient {len(objets)} objets ; l'import en accepte {MAX_OBJETS} au plus.")

    systeme = _systeme(donnees, objets)
    quartiers = []
    for rang, objet in enumerate(objets, start=1):
        geometrie = (objet or {}).get("geometry")
        nom = _nom_de((objet or {}).get("properties"), rang)
        if not geometrie or geometrie.get("type") not in ("Polygon", "MultiPolygon"):
            quartiers.append({"nom": nom, "polygone": None, "remarque": "ce n'est pas une surface : ignoré"})
            continue
        try:
            # Lu sans système puis étiqueté : la lecture d'un GeoJSON suppose d'office du WGS 84,
            # et refuserait qu'on lui annonce autre chose.
            geos = GEOSGeometry(json.dumps(geometrie))
            geos.srid = systeme
            if systeme != 4326:
                geos.transform(4326)
            if not geos.valid:
                geos = geos.buffer(0)
        except Exception:
            quartiers.append({"nom": nom, "polygone": None, "remarque": "contour illisible : ignoré"})
            continue
        remarque = "converti depuis le Lambert 93" if systeme == 2154 else ""
        if geos.geom_type == "MultiPolygon":
            # Un quartier est une surface d'un seul tenant : on garde le plus grand morceau.
            if len(geos) > 1:
                remarque = (remarque + " ; " if remarque else "") + f"{len(geos)} morceaux : le plus grand est gardé"
            geos = max(geos, key=lambda morceau: morceau.area)
        if geos.empty or geos.geom_type != "Polygon":
            quartiers.append({"nom": nom, "polygone": None, "remarque": "contour vide : ignoré"})
            continue
        geos.srid = 4326
        quartiers.append({"nom": nom, "polygone": geos, "remarque": remarque})
    return quartiers


def importer_quartiers(quartiers: list[dict], institution, environment, *, remplacer: bool, enregistrer: bool) -> dict:
    """Crée les quartiers lus (ou dit seulement ce qui se passerait, si `enregistrer` est faux).
    Un quartier du même nom existe déjà : laissé tel quel, sauf si `remplacer`."""
    existants = {z.nom.casefold(): z for z in Zone.objects.filter(institution=institution, environment=environment)}
    # « Mon territoire » est la zone de la commune entière, créée d'office : un fichier ne la redessine pas.
    reserve = ZONE_AUTOMATIQUE.casefold()
    lignes, crees, remplaces = [], 0, 0
    vus = set()
    for quartier in quartiers:
        nom, polygone = quartier["nom"], quartier["polygone"]
        if polygone is None:
            lignes.append({"nom": nom, "action": "IGNORE", "remarque": quartier["remarque"]})
            continue
        cle = nom.casefold()
        if cle == reserve:
            lignes.append({"nom": nom, "action": "IGNORE", "remarque": "nom réservé à la commune entière : ignoré"})
            continue
        if cle in vus:
            lignes.append({"nom": nom, "action": "IGNORE", "remarque": "nom en double dans le fichier : ignoré"})
            continue
        vus.add(cle)
        existant = existants.get(cle)
        if existant is not None and not remplacer:
            lignes.append({"nom": nom, "action": "EXISTE", "remarque": "un quartier de ce nom existe déjà : laissé tel quel"})
            continue
        if existant is not None:
            if enregistrer:
                existant.zone_precise = polygone
                existant.actif = True
                existant.save(update_fields=["zone_precise", "actif"])
            remplaces += 1
            lignes.append({"nom": nom, "action": "REMPLACE", "remarque": quartier["remarque"]})
        else:
            if enregistrer:
                Zone.objects.create(institution=institution, environment=environment, nom=nom, zone_precise=polygone,
                                    communes=[institution.commune_code] if institution.commune_code else [])
            crees += 1
            lignes.append({"nom": nom, "action": "CREE", "remarque": quartier["remarque"]})
    return {"enregistre": enregistrer, "crees": crees, "remplaces": remplaces,
            "laisses": sum(1 for ligne in lignes if ligne["action"] == "EXISTE"),
            "ignores": sum(1 for ligne in lignes if ligne["action"] == "IGNORE"), "lignes": lignes}
