"""Interventions annoncées par radio (26/11/2026) : un intervenant sans 4G apprend qu'un dossier
est confié à son équipe, et peut demander le point par radio.

**Format** (une ligne, lisible sur n'importe quelle radio) :

    📋 D-0123 · Pompage · Talence · 44.80000,-0.59000

Numéro du dossier, grande famille (pas le besoin ni la compétence), commune, position. Rien sur l'habitant : ni nom, ni téléphone, ni
texte saisi (décision de Sylvain du 26/11/2026). Le détail arrive par le réseau dès qu'il revient.

**Quand** :
- un dossier est confié à une équipe (`populate_dossier_participants_and_notify`) : l'annonce part
  sur le canal de l'équipe, dans chaque protocole où elle en a un ;
- un intervenant envoie « @PC MAJ » sur le canal de son équipe (ou de la crise) : le central
  répond sur ce canal par les dossiers ouverts de l'équipe (5 au plus) et les marqueurs actifs de
  la crise (8 au plus), au plus une fois toutes les 10 minutes par canal.
"""
import logging
import re

logger = logging.getLogger(__name__)

PREFIXE = "📋"
SEPARATEUR = " · "
MAX_DOSSIERS = 5
MAX_MARQUEURS = 8
INTERVALLE_MAJ_S = 600
_NATURE_MAX = 20
_COMMUNE_MAX = 30
_POSITION = re.compile(r"^(-?\d+\.?\d*),(-?\d+\.?\d*)$")
_PREFIXE_NOM = re.compile(r"^[^:\n]{1,40}: ")
_DEMANDE_MAJ = re.compile(r"^\s*@(PC|CELLULE|REGUL)\b[\s:,]*MAJ\s*$", re.IGNORECASE)
_CLOS = {"RESOLU", "CLOTURE"}


def _court(texte, n):
    t = (texte or "").replace("\n", " ").replace(SEPARATEUR.strip(), "-").strip()
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def ecrire(numero, nature="", commune="", latitude=None, longitude=None):
    morceaux = [f"{PREFIXE} {numero}".strip()]
    morceaux += [_court(nature, _NATURE_MAX) or "-", _court(commune, _COMMUNE_MAX) or "-"]
    if latitude is not None and longitude is not None:
        morceaux.append(f"{latitude:.5f},{longitude:.5f}")
    return SEPARATEUR.join(morceaux)


def lire(texte):
    """{numero, nature, commune, latitude, longitude} si le texte est une annonce, sinon None.
    Tolère un ou deux préfixes « Nom: » (radio MeshCore, relais)."""
    t = (texte or "").strip()
    for _ in range(3):
        if t.startswith(PREFIXE):
            break
        m = _PREFIXE_NOM.match(t)
        if not m:
            return None
        t = t[m.end():].lstrip()
    if not t.startswith(PREFIXE):
        return None
    morceaux = [x.strip() for x in t[len(PREFIXE):].split(SEPARATEUR.strip())]
    if not morceaux or not morceaux[0]:
        return None
    lu = {"numero": morceaux[0], "nature": "", "commune": "", "latitude": None, "longitude": None}
    if len(morceaux) > 1 and morceaux[1] != "-":
        lu["nature"] = morceaux[1]
    if len(morceaux) > 2 and morceaux[2] != "-":
        lu["commune"] = morceaux[2]
    if len(morceaux) > 3:
        p = _POSITION.match(morceaux[3])
        if p:
            lat, lon = float(p.group(1)), float(p.group(2))
            if -90 <= lat <= 90 and -180 <= lon <= 180:
                lu["latitude"], lu["longitude"] = lat, lon
    return lu


def _origine(dossier):
    return dossier.demande or dossier.information


def nature(dossier):
    """La grande famille seulement (« Matériel », « Transport », « Route barrée ») : la radio n'a
    pas à détailler le besoin ni la compétence (Sylvain, 27/11/2026). Le détail arrive en IP."""
    if dossier.demande_id and dossier.demande.request_type_id:
        from .classement import libelle_radio

        return libelle_radio(dossier.demande.request_type, dossier.demande.beneficiaire)
    if dossier.information_id and dossier.information.information_type_id:
        return str(dossier.information.information_type)
    return ""


def commune(dossier):
    """Le nom de la commune, par le cache seul : jamais d'appel réseau pour une annonce."""
    from .geo_lookup import commune_from_code_cached, commune_from_point_cached

    origine = _origine(dossier)
    if origine is None:
        return ""
    code = getattr(origine, "commune_code", None)
    nom = commune_from_code_cached(code) if code else None
    if not nom and origine.location is not None:
        nom = commune_from_point_cached(origine.location)
    return nom or ""


def texte_du_dossier(dossier):
    origine = _origine(dossier)
    lieu = origine.location if origine is not None else None
    return ecrire(dossier.numero, nature(dossier), commune(dossier),
                  lieu.y if lieu is not None else None, lieu.x if lieu is not None else None)


def _emettre(canal, texte):
    from .models import (
        CanalMeshtastic, DirectionMessageMesh, MessageCanalMeshCore, MessageCanalMeshtastic, StatutMessageMesh,
    )

    modele = MessageCanalMeshtastic if isinstance(canal, CanalMeshtastic) else MessageCanalMeshCore
    return modele.objects.create(canal=canal, direction=DirectionMessageMesh.SORTANT, expediteur=None, contenu=texte,
                                 statut=StatutMessageMesh.EN_ATTENTE, environment=canal.environment)


def canaux_de_l_equipe(equipe):
    from .radio_equipe import MESHCORE, MESHTASTIC, canal_de

    return [c for c in (canal_de(equipe, MESHTASTIC), canal_de(equipe, MESHCORE)) if c is not None and c.actif]


def annoncer(dossier, equipe):
    """Annonce le dossier sur le canal de l'équipe (deux protocoles). Rend le nombre de messages
    mis en file. Ne lève jamais."""
    try:
        if equipe is None or dossier.statut in _CLOS:
            return 0
        texte = texte_du_dossier(dossier)
        n = 0
        for canal in canaux_de_l_equipe(equipe):
            _emettre(canal, texte)
            n += 1
        return n
    except Exception:
        logger.exception("Dossier %s non annoncé par radio.", getattr(dossier, "id", None))
        return 0


def annoncer_apres_validation(dossier, equipe):
    from django.db import transaction

    transaction.on_commit(lambda: annoncer(dossier, equipe))


def est_demande_maj(texte):
    from .routage_canaux import separer_auteur

    _nom, corps = separer_auteur(texte)
    return bool(_DEMANDE_MAJ.match(corps or ""))


def _dossiers_ouverts(equipe):
    from django.db.models import Case, IntegerField, Value, When

    from .models import Dossier

    rang = Case(When(priorite="URGENTE", then=Value(0)), When(priorite="NORMALE", then=Value(1)),
                default=Value(2), output_field=IntegerField())
    return (Dossier.objects.filter(equipe=equipe, environment=equipe.environment).exclude(statut__in=_CLOS)
            .select_related("demande__request_type__parent", "information__information_type")
            .annotate(_rang=rang).order_by("-important", "_rang", "ordre", "date_creation")[:MAX_DOSSIERS])


def marqueurs_a_rappeler(crise, environment):
    """Les marqueurs actifs d'une crise à redire par radio : routes (dernier état), secours et
    dangers non clos, puis les plus récents."""
    from .marqueurs_terrain import ROUTES
    from .models import MarqueurTerrain

    actifs = list(MarqueurTerrain.objects.filter(crise=crise, environment=environment, actif=True)
                  .exclude(decision=MarqueurTerrain.Decision.CLOS).order_by("-cree_le")[:100])

    def rang(m):
        if m.genre in ("SECOURS", "DANGER"):
            return 0
        if m.genre in ROUTES and m.genre != "ROUTE_LIBEREE":
            return 1
        return 2

    return sorted(actifs, key=rang)[:MAX_MARQUEURS]


def repondre_maj(message, protocole):
    """« @PC MAJ » entendu sur un canal : le point par radio, sur ce même canal. Rend le nombre de
    messages mis en file (0 : pas une demande, trop tôt, ou rien à dire). Ne lève jamais."""
    try:
        if not est_demande_maj(message.contenu):
            return 0
        canal = message.canal
        if canal is None:
            return 0
        from django.core.cache import cache

        if not cache.add(f"maj-radio:{protocole}:{canal.pk}", 1, INTERVALLE_MAJ_S):
            return 0
        from .marqueurs_terrain import crise_du_canal, texte_radio

        lignes = []
        if getattr(canal, "equipe_id", None):
            lignes += [texte_du_dossier(d) for d in _dossiers_ouverts(canal.equipe)]
        crise = crise_du_canal(canal)
        if crise is not None:
            lignes += [texte_radio(m) for m in marqueurs_a_rappeler(crise, message.environment)]
        if not lignes:
            lignes = ["PC: rien en cours pour ce canal."]
        for texte in lignes:
            _emettre(canal, texte)
        return len(lignes)
    except Exception:
        logger.exception("Demande de mise à jour radio non servie (message %s).", getattr(message, "id", None))
        return 0
