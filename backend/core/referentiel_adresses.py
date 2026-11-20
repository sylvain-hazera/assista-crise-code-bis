"""Le référentiel d'adresses : la Base Adresse Nationale, copiée en local (20/11/2026).

POURQUOI
Les adresses servaient déjà partout -- rattachement du registre des personnes vulnérables, cercles
sur la carte, pointage des dégâts, simulation d'inondation -- mais n'arrivaient que par la
simulation ou par un relevé interrogeant la BAN RUE PAR RUE (80 appels pour une petite commune,
des milliers pour une ville), et l'adresse la plus proche d'un point était demandée à un service
extérieur. Désormais elles sont chargées une fois, en local, et tout s'appuie dessus. Voir
DOSSIER-ADRESSES-ET-DEGATS.md.

SOURCE
Le fichier complet de chaque département, publié chaque nuit par la BAN
(https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-<dép>.csv.gz, Licence
Ouverte 2.0) : 23 colonnes séparées par des points-virgules (format vérifié le 20/11/2026 sur
Mayotte et la Corse-du-Sud). Lu en flux, filtré sur les communes voulues : seul le numéro du
département part, aucune adresse de personne.

QUELLES COMMUNES (décision de Sylvain du 20/11/2026)
- le territoire des institutions communales et intercommunales, dès leur création ;
- pour tous, les communes d'une crise ouverte, à l'ouverture ou à l'ajout d'une commune ;
- une institution départementale ne charge donc pas tout son département d'avance.

MISE À JOUR
Chaque semaine (source ADRESSES_BAN de la tâche planifiée). Ajout et modification par
identifiant ; une adresse disparue est marquée `retiree_le`, jamais effacée. Une commune qui ne
rend AUCUNE ligne alors qu'elle en avait garde ses adresses : un fichier tronqué ne doit pas
retirer une commune entière.
"""
import csv
import datetime
import gzip
import io
import logging

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

URL = "https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-{departement}.csv.gz"
DELAI_REPONSE_S = 120
TAILLE_LOT = 2000
CHAMPS = ("commune_code", "commune_nom", "code_postal", "numero", "suffixe", "voie", "lieu_dit",
          "type_position", "parcelles", "lon", "lat")


def departement_de(commune_code):
    """« 33236 » -> « 33 » ; « 97411 » -> « 974 » ; « 2A004 » -> « 2A »."""
    code = (commune_code or "").strip().upper()
    return code[:3] if code.startswith("97") else code[:2]


def lire(flux, communes):
    """Les lignes du fichier départemental dont la commune est voulue, en dictionnaires."""
    texte = io.TextIOWrapper(flux, encoding="utf-8", newline="")
    for ligne in csv.DictReader(texte, delimiter=";"):
        code = ligne.get("code_insee") or ""
        if code not in communes:
            continue
        try:
            lon, lat = float(ligne["lon"]), float(ligne["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        yield ligne["id"], {
            "commune_code": code, "commune_nom": (ligne.get("nom_commune") or "")[:100],
            "code_postal": (ligne.get("code_postal") or "")[:5],
            "numero": (ligne.get("numero") or "")[:10], "suffixe": (ligne.get("rep") or "")[:10],
            "voie": (ligne.get("nom_voie") or "")[:200], "lieu_dit": (ligne.get("nom_ld") or "")[:200],
            "type_position": (ligne.get("type_position") or "")[:30],
            "parcelles": (ligne.get("cad_parcelles") or "")[:300],
            "lon": round(lon, 6), "lat": round(lat, 6),
        }


def telecharger(departement):
    """Le flux décompressé du fichier d'un département."""
    reponse = requests.get(URL.format(departement=departement), stream=True, timeout=DELAI_REPONSE_S,
                           headers={"User-Agent": "assista-crise-referentiel"})
    reponse.raise_for_status()
    reponse.raw.decode_content = False
    return gzip.GzipFile(fileobj=reponse.raw)


def _valeurs(adresse):
    return {"commune_code": adresse.commune_code, "commune_nom": adresse.commune_nom,
            "code_postal": adresse.code_postal, "numero": adresse.numero, "suffixe": adresse.suffixe,
            "voie": adresse.voie, "lieu_dit": adresse.lieu_dit, "type_position": adresse.type_position,
            "parcelles": adresse.parcelles, "lon": round(adresse.location.x, 6), "lat": round(adresse.location.y, 6)}


def charger_departement(departement, communes, maintenant=None, flux=None):
    """Charge les adresses des `communes` (codes INSEE) d'un département. Rend les comptes
    {lues, creees, modifiees, retirees}."""
    from django.contrib.gis.geos import Point

    from .models import AdresseBAN

    maintenant = maintenant or timezone.now()
    communes = set(communes)
    comptes = {"lues": 0, "creees": 0, "modifiees": 0, "retirees": 0}
    if not communes:
        return comptes
    existantes = {a.ban_id: a for a in AdresseBAN.objects.filter(commune_code__in=communes)}
    vues, communes_lues, a_creer, a_modifier = set(), set(), [], []

    def ecrire():
        if a_creer:
            AdresseBAN.objects.bulk_create(a_creer, batch_size=TAILLE_LOT, ignore_conflicts=True)
            a_creer.clear()
        if a_modifier:
            AdresseBAN.objects.bulk_update(a_modifier, [c for c in CHAMPS if c not in ("lon", "lat")]
                                           + ["location", "retiree_le", "modifie_le"], batch_size=TAILLE_LOT)
            a_modifier.clear()

    for ban_id, valeurs in lire(flux if flux is not None else telecharger(departement), communes):
        if not ban_id or ban_id in vues:
            continue
        vues.add(ban_id)
        communes_lues.add(valeurs["commune_code"])
        comptes["lues"] += 1
        existante = existantes.get(ban_id)
        champs = {c: v for c, v in valeurs.items() if c not in ("lon", "lat")}
        if existante is None:
            a_creer.append(AdresseBAN(ban_id=ban_id, location=Point(valeurs["lon"], valeurs["lat"], srid=4326),
                                      modifie_le=maintenant, **champs))
            comptes["creees"] += 1
        elif _valeurs(existante) != valeurs or existante.retiree_le is not None:
            for champ, valeur in champs.items():
                setattr(existante, champ, valeur)
            existante.location = Point(valeurs["lon"], valeurs["lat"], srid=4326)
            existante.retiree_le = None
            existante.modifie_le = maintenant
            a_modifier.append(existante)
            comptes["modifiees"] += 1
        if len(a_creer) + len(a_modifier) >= TAILLE_LOT:
            ecrire()

    with transaction.atomic():
        ecrire()
        # Retirées : connues, d'une commune présente dans le fichier, et absentes de ce fichier.
        disparues = [b for b, a in existantes.items()
                     if b not in vues and a.retiree_le is None and a.commune_code in communes_lues]
        for debut in range(0, len(disparues), TAILLE_LOT):
            comptes["retirees"] += AdresseBAN.objects.filter(ban_id__in=disparues[debut:debut + TAILLE_LOT]).update(
                retiree_le=maintenant, modifie_le=maintenant)
    absentes = communes - communes_lues
    if absentes:
        logger.warning("Adresses : aucune ligne pour %s dans le fichier %s.", ", ".join(sorted(absentes)), departement)
    return comptes


def charger_communes(communes, maintenant=None):
    """Charge les adresses de communes de départements quelconques : un téléchargement par
    département. Rend le total des comptes."""
    par_departement = {}
    for code in communes:
        if code:
            par_departement.setdefault(departement_de(code), set()).add(code)
    total = {"lues": 0, "creees": 0, "modifiees": 0, "retirees": 0}
    for departement, codes in sorted(par_departement.items()):
        for cle, valeur in charger_departement(departement, codes, maintenant).items():
            total[cle] += valeur
    return total


# ── Quelles communes ──

def communes_d_institution(institution):
    """Le territoire d'une institution communale ou intercommunale ; vide au-delà."""
    from .models import Commune, Institution

    niveau = institution.secteur_niveau_effectif
    if niveau == Institution.SecteurNiveau.COMMUNE and institution.commune_code:
        return {institution.commune_code}
    if niveau == Institution.SecteurNiveau.EPCI and institution.epci_code:
        return set(Commune.objects.filter(epci_code=institution.epci_code).values_list("code", flat=True))
    return set()


def communes_de_crise(crise):
    """Les communes de la zone d'une crise : communes et départements ajoutés, à défaut celles
    dont le centre tombe dans le polygone dessiné."""
    from django.contrib.gis.geos import Point

    from .models import Commune

    communes = set(crise.zone_communes or [])
    if crise.zone_departements:
        communes |= set(Commune.objects.filter(departement_code__in=crise.zone_departements).values_list("code", flat=True))
    if not communes and crise.zone is not None:
        emprise = crise.zone.extent
        for code, lat, lon in (Commune.objects.filter(centre_latitude__range=(emprise[1], emprise[3]),
                                                      centre_longitude__range=(emprise[0], emprise[2]))
                               .values_list("code", "centre_latitude", "centre_longitude")):
            if crise.zone.contains(Point(lon, lat, srid=4326)):
                communes.add(code)
    return communes


def communes_voulues():
    """Toutes les communes à tenir à jour : territoires communaux et intercommunaux, communes
    des crises ouvertes."""
    from .models import Crisis, Institution

    communes = set()
    for institution in Institution.objects.filter(secteur_niveau_effectif__in=("commune", "epci")):
        communes |= communes_d_institution(institution)
    for crise in Crisis.objects.filter(end_date__isnull=True):
        communes |= communes_de_crise(crise)
    return communes


def communes_manquantes(communes):
    from .models import AdresseBAN

    connues = set(AdresseBAN.objects.filter(commune_code__in=communes).values_list("commune_code", flat=True).distinct())
    return set(communes) - connues


def demander(communes):
    """Charge en tâche de fond les communes qui n'ont encore aucune adresse. Rend celles demandées."""
    manquantes = sorted(communes_manquantes(communes))
    if manquantes and getattr(settings, "CHARGEMENT_ADRESSES_AUTO", True):
        from .tasks import charger_adresses_task

        transaction.on_commit(lambda: charger_adresses_task.delay(manquantes))
    return manquantes


def institution_enregistree(sender, instance, **kwargs):
    """Signal : une institution créée ou modifiée charge les adresses de son territoire."""
    demander(communes_d_institution(instance))


def crise_enregistree(sender, instance, **kwargs):
    """Signal : une crise ouverte (ou une commune ajoutée à sa zone) charge ses communes."""
    if instance.end_date is None:
        demander(communes_de_crise(instance))


def relever(maintenant=None):
    """Mise à jour hebdomadaire de toutes les communes voulues. Rend le nombre d'adresses actives."""
    from .models import AdresseBAN

    communes = communes_voulues()
    charger_communes(communes, maintenant)
    return AdresseBAN.objects.filter(commune_code__in=communes, retiree_le__isnull=True).count()


# ── Lecture ──

def proches(latitude, longitude, rayon_m=100, nombre=10):
    """Les adresses actives les plus proches d'un point, de la plus proche à la plus lointaine,
    chacune avec sa distance (`distance_m`). Calculé chez nous : aucune question ne sort."""
    import math

    from django.contrib.gis.db.models.functions import Distance
    from django.contrib.gis.geos import Point, Polygon

    from .models import AdresseBAN

    point = Point(longitude, latitude, srid=4326)
    ecart_lat = rayon_m / 111_320
    ecart_lon = rayon_m / (111_320 * max(0.1, math.cos(math.radians(latitude))))
    emprise = Polygon.from_bbox((longitude - ecart_lon, latitude - ecart_lat, longitude + ecart_lon, latitude + ecart_lat))
    trouvees = (AdresseBAN.objects.filter(retiree_le__isnull=True, location__within=emprise)
                .annotate(distance=Distance("location", point)).order_by("distance")[:nombre])
    resultat = []
    for adresse in trouvees:
        adresse.distance_m = round(adresse.distance.m, 1)
        if adresse.distance_m <= rayon_m:
            resultat.append(adresse)
    return resultat


def la_plus_proche(latitude, longitude, rayon_m=60):
    """L'adresse active la plus proche à moins de `rayon_m`, ou None. Au-delà de 60 m,
    « l'adresse la plus proche » est celle d'un voisin, pas la sienne."""
    trouvees = proches(latitude, longitude, rayon_m=rayon_m, nombre=1)
    return trouvees[0] if trouvees else None
