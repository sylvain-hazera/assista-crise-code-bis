"""Interroge DEUX catalogues sismiques (BCSF-Rénass/EOST français -- api.franceseisme.fr -- et
EMSC, le centre euro-méditerranéen -- seismicportal.eu -- demande utilisateur du 10/10 : "mettre
l'alerting... recouper avec EMSC"). Depuis le 24/11/2026, les alertes aux collectivités passent
par la matrice des alertes automatiques (core/alertes_naturelles.py, phénomène SEISME) : ce
cycle de deux minutes lui donne les séismes lus et fait passer ses phénomènes rapides ; reste
ici la diffusion communautaire décrite plus bas.

Pourquoi recouper deux catalogues plutôt qu'un seul : chaque réseau localise/estime la
magnitude d'un même séisme un peu différemment (traitement automatisé propre à chacun, pas un
identifiant commun) -- un faux négatif d'un seul réseau sur un évènement réel est pire qu'une
fausse alerte, donc _fusionner_evenements associe les deux lectures d'un même séisme par
proximité temps/position et retient la magnitude la PLUS HAUTE des deux pour la comparaison au
seuil. Un évènement vu par un seul des deux catalogues reste diffusé tel quel (ex: un séisme
très local que seul le réseau français capte finement).

Idée native, aucun projet open source équivalent trouvé pour la France (recherche du 10/10) --
seul le PRINCIPE (interroger un catalogue sismique public et diffuser sur le mesh) est inspiré
de meshcore-bot (github.com/agessaman/meshcore-bot), qui fait la même chose avec l'API
américaine USGS.

Un coup par exécution (pas de boucle interne), appelé par cron toutes les 2 minutes (voir
~/scripts/verifier-alertes-sismiques.sh, resserré depuis 10 min le 10/10 -- la fenêtre de
recherche de 6h côté API encaisse largement un passage manqué) -- ce projet n'a pas de
celery-beat, même patron que synchroniser_sortant.py/synchroniser_entrant.py.

La diffusion elle-même ne fait QUE créer un MessageCanalMeshCore/MessageCanalMeshtastic SORTANT
avec le texte brut, `expediteur=None` : le préfixe (nom de l'institution) et la découpe sous la
limite de charge utile du protocole sont déjà appliqués par les endpoints `a_envoyer` existants
au moment où le pont les récupère (voir _prefixe_expediteur_mesh_sortant/_decouper_message_mesh
dans core/views.py) -- jamais dupliqués ici.

En plus de la diffusion mesh : notification à chaque administrateur assista-crise à chaque
diffusion réelle (demande utilisateur du 10/10 ; par l'application et le site depuis l'arrêt de
Matrix, 24/11/2026 -- voir core.notifications_application.prevenir). Jamais d'email ici, contrairement à l'alerte
SOS : pas demandé, et une diffusion sismique peut survenir plusieurs fois par cycle de 2
minutes si plusieurs institutions/séismes se recoupent, l'email serait vite trop bruyant.

Diffusion COMMUNAUTAIRE additionnelle (demande utilisateur du 10/10) : tout séisme (fusionné)
dépassant EMCOM_MAGNITUDE_MIN ET concernant la France (voir _concerne_france) est AUSSI envoyé
sur le canal Meshtastic dédié aux communications d'urgence (convention "Fr_EMCOM", voir
core.views._canal_est_dedie_urgence) -- indépendamment de toute institution/
ConfigurationAlerteSismique, et sans scope par commune/rayon (le canal communautaire n'est
rattaché à aucune institution précise, juste à la France entière -- voir _concerne_france).

ET (demande utilisateur du 16/10 : "envoyer aussi les alertes séismes (les mêmes que
meshtastic) sur le public meshcore") sur le canal MeshCore "Public" (clé universelle connue de
tout appareil MeshCore de sortie d'usine, voir CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT) --
équivalent MeshCore du canal Fr_EMCOM, mais auto-provisionné (un row par companion dès qu'il
détecte son trafic, voir CompagnonMeshCoreViewSet.signaler_canaux_detectes) plutôt que nommé
par convention. Les deux diffusions sont indépendantes (l'absence de l'une n'empêche jamais
l'autre) mais partagent le même SeismeDiffuse/DM admin -- voir _diffuser_emcom.

Bug réel corrigé le 11/10 : l'API française (api.franceseisme.fr) remonte aussi des séismes
MONDIAUX significatifs (champ lieu suffixé "(Monde)") -- sans aucun filtre de position, à la
différence de la requête EMSC qui est bornée par EMSC_BBOX. Un séisme M5.3 près de Taipei a
ainsi été diffusé sur Fr_EMCOM. _concerne_france borne désormais explicitement tout évènement
retenu pour cette diffusion à la France métropolitaine + Corse + chaque DOM-TOM habité (liste
non exhaustive des territoires les plus reculés -- TAAF notamment -- mais couvrant tous ceux
avec une population mesh potentielle). Ce canal est "partagé" (CanalMeshtastic.compagnon
= None, voir sa docstring) : plusieurs companions actifs (ex: un companion TCP/SERIE local ET
le pont MQTT Gaulix) peuvent chacun le servir -- sans ciblage explicite, DEUX companions
actifs se disputeraient les mêmes lignes EN_ATTENTE et UN SEUL des deux transmettrait
réellement (l'autre ne verrait plus jamais la ligne, déjà marquée ENVOYE par le premier). Voir
MessageCanalMeshtastic.compagnon : une ligne CIBLÉE est créée par companion actif, pour
garantir que l'alerte parte bien par CHAQUE voie (locale ET MQTT)."""
import logging
import math

import requests
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import (
    SeismeDiffuse,
    CanalMeshCore, CanalMeshtastic, MessageCanalMeshCore, MessageCanalMeshtastic,
    CompagnonMeshtastic, DirectionMessageMesh, StatutMessageMesh,
)
from core.notifications_application import prevenir_administrateurs
from core.views import _canal_est_dedie_urgence

logger = logging.getLogger(__name__)

FRANCESEISME_URL = "https://api.franceseisme.fr/fdsnws/event/1/query"
EMSC_URL = "https://www.seismicportal.eu/fdsnws/event/1/query"
FENETRE_RECHERCHE_HEURES = 6
# Seuil de la diffusion communautaire Fr_EMCOM -- demande utilisateur du 10/10 ("si séisme > 3,
# peux tu prévenir aussi sur Fr_EMCOM"), volontairement INDÉPENDANT du magnitude_min réglable
# par institution (voir ConfigurationAlerteSismique) : ce canal n'appartient à aucune
# institution, pas de raison de lier son seuil au réglage de l'une d'elles.
EMCOM_MAGNITUDE_MIN = 3.0
# Marge frontalière généreuse autour de la France métropolitaine -- un institution frontalière
# (Alpes, Pyrénées, Jura...) doit pouvoir recouper un séisme situé juste outre-frontière. Sert
# UNIQUEMENT à borner la requête EMSC (pas un critère de "concerne la France", voir
# _concerne_france pour ça) -- le filtrage par institution est de toute façon déjà fait par
# distance/rayon_km ensuite (filtrage en rayon autour d'une commune, pas d'un pays).
EMSC_BBOX = {"minlat": 41.0, "maxlat": 52.0, "minlon": -6.0, "maxlon": 11.0}
# Rectangles grossiers délimitant le territoire français -- approximation volontaire (pas de
# polygone de frontière réelle, juste de quoi écarter un évènement mondial ou clairement hors de
# France/ses DOM-TOM, voir docstring du module -- un faux positif occasionnel près d'une
# frontière est préférable à un bbox trop strict qui exclurait une vraie partie d'un territoire).
# Couvre la métropole + Corse et chaque DOM-TOM habité ; les TAAF (quasi inhabités, aucun usage
# mesh plausible) sont volontairement hors périmètre.
REGIONS_FRANCE = {
    "France metropolitaine + Corse": {"minlat": 41.2, "maxlat": 51.3, "minlon": -5.3, "maxlon": 9.6},
    "Guadeloupe": {"minlat": 15.8, "maxlat": 16.6, "minlon": -61.9, "maxlon": -60.8},
    "Martinique": {"minlat": 14.3, "maxlat": 15.0, "minlon": -61.3, "maxlon": -60.7},
    "Guyane": {"minlat": 2.0, "maxlat": 5.9, "minlon": -54.6, "maxlon": -51.5},
    "Saint-Martin / Saint-Barthelemy": {"minlat": 17.8, "maxlat": 18.2, "minlon": -63.2, "maxlon": -62.7},
    "Reunion": {"minlat": -21.5, "maxlat": -20.8, "minlon": 55.1, "maxlon": 55.9},
    "Mayotte": {"minlat": -13.1, "maxlat": -12.6, "minlon": 45.0, "maxlon": 45.4},
    "Saint-Pierre-et-Miquelon": {"minlat": 46.7, "maxlat": 47.2, "minlon": -56.5, "maxlon": -55.9},
    "Nouvelle-Caledonie": {"minlat": -22.7, "maxlat": -19.5, "minlon": 163.5, "maxlon": 168.2},
    "Polynesie francaise": {"minlat": -28.0, "maxlat": -7.8, "minlon": -155.0, "maxlon": -134.0},
    "Wallis-et-Futuna": {"minlat": -14.4, "maxlat": -13.1, "minlon": -178.3, "maxlon": -176.0},
}
# Fenêtre d'appariement entre les deux catalogues (même séisme, deux lectures) -- large par
# rapport à la précision réelle des locators automatiques (quelques secondes/dizaines de km en
# pratique, voir comparaison du 10/10 : même séisme à 3s/10km d'écart entre les deux réseaux).
APPARIEMENT_SECONDES = 300
APPARIEMENT_KM = 50


def _concerne_france(lat, lon):
    """Vrai si (lat, lon) tombe dans la métropole/Corse ou un DOM-TOM habité -- voir
    REGIONS_FRANCE. Sert à écarter un évènement mondial (ex: Taipei) de la diffusion
    communautaire Fr_EMCOM, qui n'a par ailleurs aucun autre filtre géographique (voir docstring
    du module)."""
    return any(
        r["minlat"] <= lat <= r["maxlat"] and r["minlon"] <= lon <= r["maxlon"]
        for r in REGIONS_FRANCE.values()
    )


def _distance_km(lat1, lon1, lat2, lon2):
    """Distance orthodromique (haversine) -- pas besoin de PostGIS ici : les coordonnées
    viennent d'APIs externes (pas d'objet géométrique Django côté évènement), et les échelles en
    jeu (rayon de couverture d'une institution, appariement entre deux catalogues) restent de
    l'ordre de quelques dizaines à centaines de km, largement dans la marge d'erreur de
    l'approximation sphérique."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _recuperer_evenements_france(magnitude_min, depuis):
    reponse = requests.get(
        FRANCESEISME_URL,
        params={"format": "text", "limit": 100, "orderby": "time", "minmagnitude": magnitude_min, "starttime": depuis},
        timeout=15,
    )
    reponse.raise_for_status()
    evenements = []
    for ligne in reponse.text.splitlines():
        if not ligne.strip() or ligne.startswith("#"):
            continue
        champs = ligne.split("|")
        if len(champs) < 13:
            continue
        try:
            evenements.append({
                "event_id": champs[0],
                "date": parse_datetime(champs[1]),
                "latitude": float(champs[2]),
                "longitude": float(champs[3]),
                "magnitude": float(champs[10]),
                "lieu": champs[12],
                "sources": {"FR"},
            })
        except (ValueError, IndexError, TypeError):
            # Ligne malformée (champ vide/non numérique) -- ignorée plutôt que de faire
            # planter tout le cycle pour un seul évènement mal formaté côté catalogue.
            continue
    return evenements


def _recuperer_evenements_emsc(magnitude_min, depuis):
    reponse = requests.get(
        EMSC_URL,
        params={
            "format": "json", "limit": 100, "orderby": "time", "minmagnitude": magnitude_min,
            "starttime": depuis, **EMSC_BBOX,
        },
        timeout=15,
    )
    reponse.raise_for_status()
    # EMSC répond 204 sans corps quand il n'y a aucun séisme : ce n'est pas une panne.
    if reponse.status_code == 204 or not reponse.content.strip():
        return []
    evenements = []
    for feature in reponse.json().get("features", []):
        props = feature.get("properties", {})
        try:
            evenements.append({
                "event_id": f"emsc-{props['unid']}",
                "date": parse_datetime(props["time"]),
                "latitude": float(props["lat"]),
                "longitude": float(props["lon"]),
                "magnitude": float(props["mag"]),
                "lieu": (props.get("flynn_region") or "").title() or "Lieu inconnu",
                "sources": {"EMSC"},
            })
        except (KeyError, ValueError, TypeError):
            continue
    return evenements


def _fusionner_evenements(fr_evenements, emsc_evenements):
    """Recoupe les deux catalogues -- voir docstring du module. Retourne une liste fusionnée,
    un évènement par séisme physique (pas par lecture de catalogue)."""
    fusion = []
    emsc_apparies = set()

    for fr in fr_evenements:
        meilleure_correspondance = None
        for i, emsc in enumerate(emsc_evenements):
            if i in emsc_apparies or fr["date"] is None or emsc["date"] is None:
                continue
            if abs((fr["date"] - emsc["date"]).total_seconds()) > APPARIEMENT_SECONDES:
                continue
            if _distance_km(fr["latitude"], fr["longitude"], emsc["latitude"], emsc["longitude"]) > APPARIEMENT_KM:
                continue
            meilleure_correspondance = i
            break

        if meilleure_correspondance is not None:
            emsc = emsc_evenements[meilleure_correspondance]
            emsc_apparies.add(meilleure_correspondance)
            fusion.append({
                **fr,
                # La magnitude la plus haute des deux lectures : mieux vaut diffuser une alerte
                # sur une estimation un peu haute que manquer un évènement réel parce qu'un des
                # deux réseaux l'a initialement sous-estimé (voir docstring du module).
                "magnitude": max(fr["magnitude"], emsc["magnitude"]),
                "sources": fr["sources"] | emsc["sources"],
            })
        else:
            fusion.append(fr)

    for i, emsc in enumerate(emsc_evenements):
        if i not in emsc_apparies:
            fusion.append(emsc)

    return fusion


class Command(BaseCommand):
    help = "Diffuse une alerte mesh pour tout séisme récent (France + recoupement EMSC) dépassant le seuil configuré par une institution."

    def handle(self, *args, **options):
        from core import alertes_naturelles
        from core.models import RegleAlerte

        # Le minimum à récupérer couvre à la fois les seuils des collectivités (matrice des
        # alertes automatiques, 24/11/2026) et le seuil fixe de la diffusion communautaire.
        seuils = [r.seuil("ALERTE") for r in RegleAlerte.objects.filter(actif=True, phenomene="SEISME")]
        magnitude_min_globale = min(seuils + [EMCOM_MAGNITUDE_MIN])
        depuis = (timezone.now() - timezone.timedelta(hours=FENETRE_RECHERCHE_HEURES)).strftime("%Y-%m-%dT%H:%M:%S")

        try:
            evenements_fr = _recuperer_evenements_france(magnitude_min_globale, depuis)
        except requests.RequestException as exc:
            logger.warning("Échec de requête à l'API sismique française (%s) -- retentée au prochain passage.", exc)
            evenements_fr = None

        try:
            evenements_emsc = _recuperer_evenements_emsc(magnitude_min_globale, depuis)
        except requests.RequestException as exc:
            logger.warning("Échec de requête à l'API sismique EMSC (%s) -- retentée au prochain passage.", exc)
            evenements_emsc = None

        repondu = evenements_fr is not None or evenements_emsc is not None
        evenements = _fusionner_evenements(evenements_fr or [], evenements_emsc or []) if repondu else []

        # Les phénomènes rapides de la matrice (séisme, orages, foudre, feux suivis, pluie) passent
        # à chaque cycle de deux minutes, qu'il y ait eu un séisme ou non.
        alertes = alertes_naturelles.evaluer(alertes_naturelles.PHENOMENES_RAPIDES,
                                             contexte={"seismes": evenements if repondu else None})

        if not repondu:
            self.stdout.write(f"Alertes sismiques : aucune des deux API n'a répondu ; {len(alertes)} alerte(s) automatique(s).")
            return

        diffusions_emcom = 0
        for evt in evenements:
            if evt["magnitude"] < EMCOM_MAGNITUDE_MIN:
                continue
            if not _concerne_france(evt["latitude"], evt["longitude"]):
                continue
            if SeismeDiffuse.objects.filter(institution__isnull=True, event_id=evt["event_id"]).exists():
                continue
            if self._diffuser_emcom(evt):
                diffusions_emcom += 1

        self.stdout.write(
            f"Alertes sismiques : {len(evenements_fr or [])} évènement(s) FR, {len(evenements_emsc or [])} EMSC, "
            f"{len(evenements)} après fusion, {len(alertes)} alerte(s) automatique(s), "
            f"{diffusions_emcom} diffusion(s) Fr_EMCOM."
        )

    def _diffuser_emcom(self, evt) -> bool:
        """Diffusion communautaire, à la fois sur le canal Meshtastic "Fr_EMCOM" (ou équivalent)
        ET sur le canal MeshCore "Public" (demande utilisateur du 16/10 : "envoyer aussi les
        alertes séismes sur le public meshcore") -- les deux protocoles ont chacun leur propre
        notion de canal communautaire universel, voir _diffuser_emcom_meshtastic/
        _diffuser_emcom_meshcore. Retourne False sans rien faire si NI L'UN NI L'AUTRE n'existe
        (phase de test) : pas une erreur, juste rien à diffuser. Un seul SeismeDiffuse/DM Matrix
        créé au total, même si les deux protocoles diffusent effectivement -- le dédoublonnage
        (SeismeDiffuse) et la notification admin portent sur l'ÉVÈNEMENT, pas sur chaque canal."""
        lieu_brut = evt["lieu"]
        lieu = lieu_brut.split("near ", 1)[1] if "near " in lieu_brut else lieu_brut
        texte = f"Seisme M{evt['magnitude']:.1f} pres de {lieu}."

        canal_meshtastic_nom, environment_mt = self._diffuser_emcom_meshtastic(texte)
        canaux_meshcore_noms, environment_mc = self._diffuser_emcom_meshcore(texte)
        if canal_meshtastic_nom is None and not canaux_meshcore_noms:
            return False

        canaux_touches = ([canal_meshtastic_nom] if canal_meshtastic_nom else []) + canaux_meshcore_noms
        environment = environment_mt or environment_mc

        SeismeDiffuse.objects.create(
            institution=None, event_id=evt["event_id"], magnitude=evt["magnitude"], lieu=evt["lieu"],
            latitude=evt["latitude"], longitude=evt["longitude"], date_evenement=evt["date"],
            environment=environment,
        )
        logger.info(
            "Alerte sismique diffusée sur %s : %s (sources : %s)",
            ", ".join(canaux_touches), texte, ", ".join(sorted(evt["sources"])),
        )

        prevenir_administrateurs(
            f"Séisme M{evt['magnitude']:.1f} près de {lieu}",
            f"{texte} (canaux {', '.join(canaux_touches)}, sources : {', '.join(sorted(evt['sources']))})",
            urgent=evt["magnitude"] >= 4.5, lien="/admin/veille",
        )

        return True

    def _diffuser_emcom_meshtastic(self, texte) -> tuple:
        """Diffusion sur le canal Meshtastic "Fr_EMCOM" (ou équivalent -- voir
        _canal_est_dedie_urgence) -- voir docstring du module pour le détail du ciblage par
        companion. Renvoie (nom_du_canal, environment) si diffusé, (None, None) sinon (aucun
        canal de ce type, ou aucun companion actif pour le servir)."""
        canaux = CanalMeshtastic.objects.filter(actif=True)
        canal_emcom = next((c for c in canaux if _canal_est_dedie_urgence(c.nom)), None)
        if canal_emcom is None:
            return None, None

        compagnons = list(CompagnonMeshtastic.objects.filter(actif=True))
        if not compagnons:
            return None, None

        # Une ligne CIBLÉE par companion actif (voir MessageCanalMeshtastic.compagnon) : sans
        # ça, plusieurs companions servant ce même canal "partagé" se disputeraient les mêmes
        # lignes EN_ATTENTE et un seul transmettrait réellement (voir docstring du module).
        for compagnon in compagnons:
            MessageCanalMeshtastic.objects.create(
                canal=canal_emcom, compagnon=compagnon, direction=DirectionMessageMesh.SORTANT,
                statut=StatutMessageMesh.EN_ATTENTE, contenu=texte, environment=canal_emcom.environment,
            )
        return canal_emcom.nom, canal_emcom.environment

    def _diffuser_emcom_meshcore(self, texte) -> tuple:
        """Diffusion sur le(s) canal(aux) MeshCore "Public" -- clé universelle connue de tout
        appareil MeshCore de sortie d'usine (voir CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT),
        auto-provisionné par companion dès qu'il détecte son trafic radio (voir
        CompagnonMeshCoreViewSet.signaler_canaux_detectes) -- pendant MeshCore de
        _diffuser_emcom_meshtastic. Contrairement au canal Meshtastic partagé, pas de risque de
        collision multi-companion ici : CHAQUE CanalMeshCore "Public" est déjà lié à SON propre
        companion (un row par companion l'ayant détecté), donc un simple message par canal
        suffit, sans champ de ciblage dédié (MessageCanalMeshCore n'en a pas, contrairement à
        MessageCanalMeshtastic.compagnon). Renvoie (liste des noms de canal touchés,
        environment du premier) -- liste vide/environment None si aucun canal public connu."""
        # Comparaison en Python et non en SQL : cle_partagee_hex est chiffrée au repos
        # (EncryptedTextField, Fernet) et Fernet n'est pas déterministe -- deux lignes de même clé
        # ont deux chiffrés différents, donc `filter(cle_partagee_hex=...)` ne trouverait JAMAIS
        # rien et les alertes séisme cesseraient d'être diffusées, sans erreur. La table est
        # minuscule (un canal par companion l'ayant détecté), le filtrage Python est sans coût.
        canaux_publics = [
            c for c in CanalMeshCore.objects.filter(actif=True)
            if c.cle_partagee_hex == CanalMeshCore.SECRET_PUBLIC_PAR_DEFAUT
        ]
        if not canaux_publics:
            return [], None

        for canal in canaux_publics:
            MessageCanalMeshCore.objects.create(
                canal=canal, direction=DirectionMessageMesh.SORTANT, statut=StatutMessageMesh.EN_ATTENTE,
                contenu=texte, environment=canal.environment,
            )
        return [c.nom for c in canaux_publics], canaux_publics[0].environment
