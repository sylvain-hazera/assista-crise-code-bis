"""Antennes de téléphonie mobile déclarées en panne ou en maintenance : relevé du fichier
quotidien de l'Arcep, copie en base.

SOURCE
Jeu « Sites indisponibles » de l'Arcep (https://www.data.gouv.fr/datasets/sites-indisponibles),
Licence Ouverte, aucune clé. Depuis le « New Deal mobile » de 2018, les quatre opérateurs
doivent déclarer leurs sites en panne ou en maintenance ; l'Arcep en publie l'instantané chaque
jour, vers 10 heures. Pour chaque site : position, opérateur, état de la voix et des données,
par technologie, motif (incident ou maintenance) et date de début.

CE QUE C'EST, ET CE QUE CE N'EST PAS
- Un état QUOTIDIEN : une panne de l'après-midi n'apparaît que le lendemain. En crise, c'est
  la situation de la veille au matin, pas du temps réel. L'écran doit donner la date du fichier.
- Des DÉCLARATIONS d'opérateurs. Certaines ne sont jamais refermées (des sites « en panne »
  depuis 2022 figuraient encore dans le fichier du 15/11/2026).
- Une antenne en panne n'est pas une zone sans réseau : une antenne voisine peut couvrir.

LE FILTRE DES SIX MOIS (décision du 15/11/2026)
Une panne déclarée depuis plus de six mois n'est plus montrée : ce n'est plus une panne, c'est
une déclaration oubliée ou un site abandonné, et elle noierait les vraies. Conséquence constatée
le jour même : TOUTES les déclarations de Bouygues Telecom datent de décembre 2021 et janvier
2022 (son flux semble figé depuis) et sont donc écartées. L'écran doit le dire, opérateur par
opérateur : « aucune panne Bouygues » ne veut pas dire que son réseau va bien. L'âge se compte depuis
la date de début déclarée ; quand l'opérateur n'en donne pas, depuis le jour où CE serveur a vu
le site en panne pour la première fois. Les lignes écartées restent en base (pour garder cette
date de première vue) et sont comptées à part.

Même règle que le reste de la veille : seul le serveur appelle, pour la France entière, depuis
la tâche planifiée. Rien de ce qui part ne désigne un utilisateur ni un territoire.
"""
import datetime
import logging
from zoneinfo import ZoneInfo

import requests
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

URL_FICHIER = "https://arcep.s3.rbx.io.cloud.ovh.net/sites-indisponibles/all/{jour}/raw{jour}.geojson"
DELAI_REPONSE_S = 60
TAILLE_MAX = 40 * 1024 * 1024
# Le fichier du jour paraît vers 10 h, et certains jours n'en ont pas (aucun le 13 ni le
# 14/11/2026) : on remonte jusqu'à trouver le dernier paru.
JOURS_ESSAYES = 6
FUSEAU = ZoneInfo("Europe/Paris")

DUREE_MAX_AFFICHEE = datetime.timedelta(days=183)

INCIDENT, MAINTENANCE = "INCIDENT", "MAINTENANCE"
_MOTIFS = {"INT": INCIDENT, "MAINT": MAINTENANCE}
# « Voix et données coupées » d'abord : c'est ce qui isole un secteur.
TOTALE, PARTIELLE, DECLAREE = "TOTALE", "PARTIELLE", "DECLAREE"
ORDRE_GRAVITES = (TOTALE, PARTIELLE, DECLAREE)


def _hors_service(valeur):
    """« HS » -> True, « OK » -> False, autre chose (non renseigné) -> None."""
    return {"HS": True, "OK": False}.get(valeur)


def _debut(texte):
    """« 2026-11-11 06:21:00 » (heure de Paris) -> instant, ou None."""
    try:
        return datetime.datetime.strptime(texte, "%Y-%m-%d %H:%M:%S").replace(tzinfo=FUSEAU)
    except (TypeError, ValueError):
        return None


def analyser(donnees):
    """Fichier de l'Arcep -> {clé: description}. La clé réunit l'opérateur et le numéro de
    station de l'ANFR (deux opérateurs peuvent partager un même pylône) ; quand deux lignes
    portent la même clé, la dernière du fichier est gardée."""
    sites = {}
    for element in donnees.get("features") or []:
        proprietes = element.get("properties") or {}
        coordonnees = (element.get("geometry") or {}).get("coordinates") or []
        operateur = (proprietes.get("operateur") or "").strip()
        station = str(proprietes.get("station_anfr") or "").strip()
        if not operateur or len(coordonnees) < 2:
            continue
        longitude, latitude = coordonnees[0], coordonnees[1]
        if not (isinstance(longitude, (int, float)) and isinstance(latitude, (int, float))
                and -180 <= longitude <= 180 and -90 <= latitude <= 90):
            continue
        technologies = {nom: proprietes.get(nom) for nom in
                        ("voix2g", "voix3g", "voix4g", "data3g", "data4g", "data5g")
                        if proprietes.get(nom) in ("OK", "HS")}
        # Sans numéro de station (79 sites sur 1 134 le 15/11/2026), la position en tient lieu.
        repere = station or f"@{latitude:.5f},{longitude:.5f}"
        sites[f"{operateur}|{repere}"[:80]] = {
            "operateur": operateur[:40], "station": station[:20],
            "commune": (proprietes.get("commune") or "").strip()[:120],
            "code_insee": (proprietes.get("code_insee") or "").strip()[:5],
            "voix_hs": _hors_service(proprietes.get("voix")),
            "donnees_hs": _hors_service(proprietes.get("data")),
            "technologies": technologies,
            "motif": _MOTIFS.get(proprietes.get("raison"), ""),
            "debut": _debut(proprietes.get("debut")),
            "longitude": longitude, "latitude": latitude,
        }
    return sites


def telecharger(maintenant):
    """Le dernier fichier paru : (jour du fichier, contenu). Lève ValueError si aucun des
    derniers jours n'en a."""
    aujourd_hui = maintenant.astimezone(FUSEAU).date()
    for recul in range(JOURS_ESSAYES):
        jour = aujourd_hui - datetime.timedelta(days=recul)
        reponse = requests.get(URL_FICHIER.format(jour=jour.isoformat()), timeout=DELAI_REPONSE_S)
        if reponse.status_code in (403, 404):
            continue        # pas (encore) de fichier ce jour-là
        reponse.raise_for_status()
        if len(reponse.content) > TAILLE_MAX:
            raise ValueError(f"{len(reponse.content)} octets : ce n'est pas le fichier attendu")
        return jour, reponse.json()
    raise ValueError(f"aucun fichier de sites indisponibles sur les {JOURS_ESSAYES} derniers jours")


def gravite(antenne):
    """TOTALE : voix et données coupées. PARTIELLE : l'un des deux, ou une technologie.
    DECLAREE : site déclaré indisponible sans qu'un service soit dit coupé."""
    if antenne.voix_hs and antenne.donnees_hs:
        return TOTALE
    if antenne.voix_hs or antenne.donnees_hs or "HS" in (antenne.technologies or {}).values():
        return PARTIELLE
    return DECLAREE


def depuis(antenne):
    """Début de la panne : celui que l'opérateur déclare, à défaut le jour où nous l'avons vue."""
    return antenne.debut or antenne.premiere_vue_le


def trop_ancienne(antenne, maintenant=None):
    """Vrai pour une panne déclarée depuis plus de six mois (voir l'en-tête du module)."""
    return (maintenant or timezone.now()) - depuis(antenne) > DUREE_MAX_AFFICHEE


def relever(maintenant=None):
    """Copie le dernier fichier paru. Rend le nombre de sites indisponibles qu'il porte."""
    from .models import AntenneIndisponible

    maintenant = maintenant or timezone.now()
    jour, donnees = telecharger(maintenant)
    sites = analyser(donnees)
    if not sites:
        raise ValueError("fichier de sites indisponibles vide")

    connues = {antenne.cle: antenne for antenne in AntenneIndisponible.objects.all()}
    a_creer, a_modifier = [], []
    for cle, site in sites.items():
        champs = {
            "operateur": site["operateur"], "station": site["station"], "commune": site["commune"],
            "code_insee": site["code_insee"], "voix_hs": site["voix_hs"], "donnees_hs": site["donnees_hs"],
            "technologies": site["technologies"], "motif": site["motif"], "debut": site["debut"],
            "location": Point(site["longitude"], site["latitude"], srid=4326),
            "jour_du_fichier": jour, "releve_le": maintenant,
        }
        antenne = connues.get(cle)
        if antenne is None:
            a_creer.append(AntenneIndisponible(cle=cle, premiere_vue_le=maintenant, **champs))
        else:
            for nom, valeur in champs.items():
                setattr(antenne, nom, valeur)
            a_modifier.append(antenne)
    with transaction.atomic():
        AntenneIndisponible.objects.bulk_create(a_creer, batch_size=500)
        AntenneIndisponible.objects.bulk_update(
            a_modifier, ["operateur", "station", "commune", "code_insee", "voix_hs", "donnees_hs",
                         "technologies", "motif", "debut", "location", "jour_du_fichier", "releve_le"],
            batch_size=500)
        # Un site absent du fichier est rétabli : il part, et sa date de première vue avec lui.
        AntenneIndisponible.objects.exclude(cle__in=sites).delete()
    return len(sites)
