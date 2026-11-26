"""Marqueurs terrain (26/11/2026) : feu, personne trouvée, route coupée… posés sur la carte par
le terrain, par la radio, l'application ou le site.

**Format radio** (celui de MeshCore SAR, lisible par l'application Assista-Crise et par SAR) :

    S:<émoji>:<couleur>:<latitude>,<longitude>:<note>

L'ancienne forme sans couleur est encore lue. Le marqueur peut suivre un ou deux préfixes
« Nom: » : la radio MeshCore ajoute le nom de l'émetteur, et le relais Meshtastic ↔ MeshCore du
canal de crise (routage_canaux.relayer_vers_autre_protocole) y ajoute l'auteur. Format relevé
dans les messages de SAR ; rien de son code n'est repris.

**Routes** : trois émojis, trois états — ⛔ coupée totalement, 🚧 une voie libérée, ✅ axe
libéré. Un état de route remplace le marqueur de route voisin (moins de 30 m) de la même crise
ou manifestation. Les autres genres s'ajoutent.

Décisions de Sylvain (26/11/2026) : affiché tout de suite ; le régulateur est prévenu et décide
du traitement ; terrain et PC peuvent changer l'état d'une route ; ce qui est posé par le site
ou l'application repart par la radio, sur les canaux de crise des deux protocoles.
"""
import datetime
import logging
import re

from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.utils import timezone

logger = logging.getLogger(__name__)

#: émoji → (code, libellé), hors routes. « Secours à personne » (27/11/2026) remplace « personne
#: trouvée » et « blessé » : 🧑, 👤 et 🚑 reçus d'autres applications sont lus ainsi.
GENRES = {
    "🆘": ("SECOURS", "Secours à personne"), "🧑": ("SECOURS", "Secours à personne"),
    "👤": ("SECOURS", "Secours à personne"), "🚑": ("SECOURS", "Secours à personne"),
    "🔥": ("FEU", "Feu"),
    "🏕️": ("REGROUPEMENT", "Zone de regroupement"), "⛺": ("REGROUPEMENT", "Zone de regroupement"),
    "📦": ("OBJET", "Objet"),
    "🌊": ("INONDATION", "Inondation"),
    "⚠️": ("DANGER", "Danger"),
    # Information (26/11/2026) : un signalement du public « Information utile » ou « Autre ».
    "ℹ️": ("INFO", "Information"), "ℹ": ("INFO", "Information"),
}

#: Signalement du public → (émoji, précision de la note), par libellé de type (26/11/2026).
#: Une route signalée n'a pas de sens précisé : le terrain le précise ensuite (5 états).
MARQUEUR_DU_SIGNALEMENT = {
    "route barrée": ("⛔", ""),
    "arbre sur la chaussée": ("⛔", "Arbre sur la chaussée"),
    "danger imminent": ("⚠️", ""),
}
SIGNALEMENT_PAR_DEFAUT = ("ℹ️", "")
#: Longueur d'une note de signalement : la radio n'a pas de place pour plus.
NOTE_SIGNALEMENT_MAX = 80

#: Les cinq états d'une route (décision de Sylvain du 27/11/2026) : code → (émoji, précision
#: qui ouvre la note, libellé). L'émoji porte la famille, la précision le sens : le texte reste
#: du SAR pur (« S:⛔:0:44.85000,-0.57000:1 sens · arbre en travers »).
ETATS_ROUTE = {
    "ROUTE_COUPEE_2S": ("⛔", "2 sens", "Route coupée dans les 2 sens"),
    "ROUTE_COUPEE_1S": ("⛔", "1 sens", "Route coupée dans 1 sens"),
    "ROUTE_FILE_1S": ("🚧", "1 file, 1 sens", "1 file fermée dans 1 sens"),
    "ROUTE_FILE_2S": ("🚧", "1 file, 2 sens", "1 file fermée dans les 2 sens"),
    "ROUTE_LIBEREE": ("✅", "", "Route : axe libéré"),
}
#: Marqueurs d'avant le 27/11/2026, sans précision de sens.
ROUTES_SANS_SENS = {"⛔": ("ROUTE_COUPEE", "Route coupée, sens non précisé"),
                    "🚧": ("ROUTE_UNE_VOIE", "1 file fermée, sens non précisé")}
ROUTES = set(ETATS_ROUTE) | {code for code, _l in ROUTES_SANS_SENS.values()}
EMOJIS_ROUTE = {"⛔", "🚧", "✅"}
_SEPARATEUR = " · "
#: Rayon où un nouvel état de route remplace l'ancien.
RAYON_ROUTE_M = 30
#: Un même marqueur réentendu (deux passerelles, relais entre protocoles) dans ce délai, à ce
#: rayon, n'est enregistré qu'une fois.
DOUBLON_MINUTES = 10
DOUBLON_RAYON_M = 5

_NOUVEAU = re.compile(r"^S:([^:]+):(\d):(-?\d+\.?\d*),(-?\d+\.?\d*):?(.*)$")
_ANCIEN = re.compile(r"^S:([^:]+):(-?\d+\.?\d*),(-?\d+\.?\d*):?(.*)$")
_PREFIXE = re.compile(r"^[^:\n]{1,40}: ")


def _precision(note):
    """(précision de sens reconnue en tête de la note, reste de la note)."""
    t = (note or "").strip()
    bas = t.lower()
    # Les plus longues d'abord : « 1 file, 1 sens » avant « 1 sens ».
    for precision in sorted({p for _e, p, _l in ETATS_ROUTE.values() if p}, key=len, reverse=True):
        if bas == precision:
            return precision, ""
        if bas.startswith(precision) and bas[len(precision)] in " ·-:":
            return precision, t[len(precision):].lstrip(" ·-:").strip()
    return "", t


def genre_de(emoji, note=""):
    """(code, libellé) d'un marqueur, d'après son émoji et, pour une route, la précision de sens
    qui ouvre sa note."""
    if emoji in EMOJIS_ROUTE:
        precision, _reste = _precision(note)
        for code, (e, p, libelle_route) in ETATS_ROUTE.items():
            if e == emoji and p == precision:
                return code, libelle_route
        return ROUTES_SANS_SENS.get(emoji, ("ROUTE_LIBEREE", ETATS_ROUTE["ROUTE_LIBEREE"][2]))
    return GENRES.get(emoji, ("AUTRE", "Marqueur"))


def note_libre(note):
    """La note sans la précision de sens d'une route."""
    return _precision(note)[1]


def note_de_route(code, note_libre_=""):
    """La note d'un état de route : sa précision, puis la note libre."""
    precision = ETATS_ROUTE[code][1]
    libre = (note_libre_ or "").strip()
    return f"{precision}{_SEPARATEUR}{libre}" if precision and libre else (precision or libre)


def lire(texte):
    """Rend {emoji, genre, latitude, longitude, note, couleur} si le texte porte un marqueur,
    sinon None."""
    t = (texte or "").strip()
    for _ in range(3):
        if t.startswith("S:"):
            break
        m = _PREFIXE.match(t)
        if not m:
            return None
        t = t[m.end():].lstrip()
    else:
        return None
    if not t.startswith("S:"):
        return None
    lignes = t.split("\n")
    premiere = lignes[0].strip()
    nouveau = _NOUVEAU.match(premiere)
    m = nouveau or _ANCIEN.match(premiere)
    if not m:
        return None
    g = m.groups()
    decalage = 1 if nouveau else 0
    emoji = g[0].strip()
    try:
        lat, lon = float(g[1 + decalage]), float(g[2 + decalage])
    except ValueError:
        return None
    if not emoji or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None
    note = "\n".join(x for x in [g[3 + decalage].strip()] + [l.strip() for l in lignes[1:]] if x)
    return {"emoji": emoji, "genre": genre_de(emoji, note)[0], "latitude": lat, "longitude": lon, "note": note,
            "couleur": int(g[1]) if nouveau else 0}


def ecrire(emoji, latitude, longitude, note=""):
    """Le texte radio d'un marqueur (cinq décimales : un mètre environ)."""
    base = f"S:{emoji}:0:{latitude:.5f},{longitude:.5f}"
    note = (note or "").replace("\n", " ").strip()
    return f"{base}:{note}" if note else base


#: La radio n'a besoin que de l'essentiel (Sylvain, 27/11/2026 : « ne sois pas aussi précis en
#: mesh qu'en data ») : émoji, position, sens d'une route, quelques mots. Le détail reste en IP.
NOTE_RADIO_MAX = 30


def note_radio(marqueur):
    """La note qui part par radio : la précision de sens d'une route, puis quelques mots. Pour un
    signalement, son type seul (« Route barrée »), jamais le titre saisi."""
    precision, libre = _precision(marqueur.note)
    if marqueur.source == "SIGNALEMENT":
        morceaux = [x.strip() for x in libre.split(_SEPARATEUR.strip())]
        libre = morceaux[1] if len(morceaux) > 1 else ""
    libre = libre.replace("\n", " ").strip()
    if len(libre) > NOTE_RADIO_MAX:
        libre = libre[:NOTE_RADIO_MAX - 1].rstrip() + "…"
    return f"{precision}{_SEPARATEUR}{libre}" if precision and libre else (precision or libre)


def texte_radio(marqueur):
    """Le texte d'un marqueur tel que le central l'émet par radio."""
    return ecrire(marqueur.emoji, marqueur.location.y, marqueur.location.x, note_radio(marqueur))


def libelle(marqueur):
    return genre_de(marqueur.emoji, marqueur.note)[1]


def nom_auteur(marqueur):
    if marqueur.auteur_id:
        u = marqueur.auteur
        return (f"{u.first_name} {u.last_name}".strip() or u.username or "Intervenant")
    return marqueur.auteur_libre or "Radio"


def enregistrer(environment, emoji, latitude, longitude, note="", *, crise=None, manifestation=None, auteur=None,
                auteur_libre="", source, canal_nom="", diffuser_radio=False, sauf_protocole=None, prevenir=True,
                signalement_id=None):
    """Enregistre un marqueur. Rend (marqueur, créé). Un doublon récent rend l'existant, sans
    rien refaire. Un état de route remplace le marqueur de route voisin."""
    from .models import MarqueurTerrain

    point = Point(float(longitude), float(latitude), srid=4326)
    genre = genre_de(emoji, note)[0]
    portee = MarqueurTerrain.objects.filter(environment=environment, crise=crise, manifestation=manifestation)
    doublon = portee.filter(genre=genre, cree_le__gte=timezone.now() - datetime.timedelta(minutes=DOUBLON_MINUTES),
                            location__distance_lte=(point, D(m=DOUBLON_RAYON_M))).first()
    if doublon is not None:
        return doublon, False
    ancien = None
    if genre in ROUTES:
        ancien = (portee.filter(actif=True, genre__in=ROUTES, location__distance_lte=(point, D(m=RAYON_ROUTE_M)))
                  .order_by("-cree_le").first())
    m = MarqueurTerrain.objects.create(
        environment=environment, crise=crise, manifestation=manifestation, emoji=emoji, genre=genre, location=point,
        note=(note or "")[:500], auteur=auteur, auteur_libre=(auteur_libre or "")[:100], source=source,
        canal_nom=(canal_nom or "")[:100], remplace=ancien, signalement_id=signalement_id,
    )
    if ancien is not None:
        ancien.actif = False
        ancien.save(update_fields=["actif", "modifie_le"])
    if diffuser_radio:
        diffuser(m, sauf_protocole=sauf_protocole)
    if prevenir:
        prevenir_regulation(m)
    return m, True


def crise_du_canal(canal):
    """La crise d'un canal radio : canal de crise, canal d'une équipe engagée sur une mission en
    cours, ou canal de commune (la première crise ouverte de la commune)."""
    from .models import Mission

    if getattr(canal, "crise_id", None):
        return canal.crise
    if getattr(canal, "equipe_id", None):
        mission = (Mission.objects.filter(equipes=canal.equipe, statut=Mission.Statut.EN_COURS, crise__isnull=False)
                   .select_related("crise").order_by("-date_creation").first())
        return mission.crise if mission else None
    if getattr(canal, "institution_id", None):
        from .canaux_locaux import crises_de
        return next(iter(crises_de(canal.institution)), None)
    return None


def depuis_radio(message, protocole):
    """Un message de canal ENTRANT (déjà reconnu comme n'étant pas un écho des nôtres) : s'il
    porte un marqueur, il est enregistré. Ne lève jamais."""
    try:
        lu = lire(message.contenu)
        if lu is None:
            return None
        from .models import MarqueurTerrain
        from .routage_canaux import separer_auteur

        auteur, auteur_libre = message.expediteur, ""
        if auteur is None:
            nom, _reste = separer_auteur(message.contenu)
            auteur_libre = nom or ""
            if not auteur_libre and protocole == "MESHTASTIC" and getattr(message, "contact_node_num", None) is not None:
                from .routage_canaux import _nom_noeud_meshtastic
                auteur_libre = _nom_noeud_meshtastic(message.contact_node_num) or ""
        canal = message.canal
        crise = crise_du_canal(canal) if canal else None
        # Entendu ailleurs que sur le canal de crise (équipe, commune) : le central le rediffuse
        # sur le canal de crise des deux protocoles (26/11/2026). Sur le canal de crise, le relais
        # vers l'autre protocole est déjà fait par routage_canaux.
        hors_canal_de_crise = crise is not None and not (getattr(canal, "crise_id", None) and not getattr(canal, "equipe_id", None))
        m, _cree = enregistrer(
            message.environment, lu["emoji"], lu["latitude"], lu["longitude"], lu["note"],
            crise=crise, auteur=auteur, auteur_libre=auteur_libre,
            source=MarqueurTerrain.Source.MESHTASTIC if protocole == "MESHTASTIC" else MarqueurTerrain.Source.MESHCORE,
            canal_nom=getattr(canal, "nom", "") or "", diffuser_radio=hors_canal_de_crise,
        )
        return m
    except Exception:
        logger.exception("Marqueur radio non enregistré (message %s).", getattr(message, "id", None))
        return None


def _canaux_de_diffusion(marqueur, modele_canal):
    """Le canal où émettre : celui de la crise ; pour une manifestation, celui de l'institution
    organisatrice (26/11/2026), sans équipe ni crise."""
    if marqueur.crise_id:
        return modele_canal.objects.filter(crise_id=marqueur.crise_id, equipe__isnull=True, actif=True).first()
    if marqueur.manifestation_id:
        institution_id = marqueur.manifestation.institution_id
        if institution_id:
            return modele_canal.objects.filter(institution_id=institution_id, crise__isnull=True, equipe__isnull=True,
                                               actif=True).first()
    return None


def diffuser(marqueur, sauf_protocole=None):
    """Renvoie le marqueur par la radio, sur les canaux de crise des deux protocoles (messages
    SORTANTS que les passerelles émettent). Sans crise ou sans canal : rien. `sauf_protocole` :
    le téléphone l'a déjà émis sur le canal de crise de ce protocole ; l'autre réseau reste servi
    (comme `deja_emis_radio` de la messagerie d'équipe)."""
    from .models import (
        CanalMeshCore, CanalMeshtastic, DirectionMessageMesh, MessageCanalMeshCore, MessageCanalMeshtastic,
        StatutMessageMesh,
    )

    if not marqueur.crise_id and not marqueur.manifestation_id:
        return 0
    texte = texte_radio(marqueur)
    n = 0
    for protocole, modele_canal, modele_message in (("MESHTASTIC", CanalMeshtastic, MessageCanalMeshtastic),
                                                    ("MESHCORE", CanalMeshCore, MessageCanalMeshCore)):
        if protocole == sauf_protocole:
            continue
        canal = _canaux_de_diffusion(marqueur, modele_canal)
        if canal is None:
            continue
        modele_message.objects.create(canal=canal, direction=DirectionMessageMesh.SORTANT, expediteur=marqueur.auteur,
                                      contenu=texte, statut=StatutMessageMesh.EN_ATTENTE, environment=canal.environment)
        n += 1
    return n


def crise_du_signalement(info):
    """La crise d'un signalement : la sienne, sinon la crise ouverte la plus récente de même
    environnement dont la zone contient sa commune."""
    from .models import Crisis

    if info.crisis_id:
        return info.crisis if info.crisis.end_date is None else None
    if not info.commune_code:
        return None
    return (Crisis.objects.filter(environment=info.environment, end_date__isnull=True,
                                  zone_communes__contains=[info.commune_code])
            .order_by("-start_date").first())


def note_du_signalement(info):
    """« Signalement · <type> · <titre> » : ni nom, ni téléphone (décision de Sylvain du
    26/11/2026). La précision d'une route (aucune ici) resterait en tête."""
    type_ = (str(info.information_type) if info.information_type_id else "").strip()
    _emoji, precision = MARQUEUR_DU_SIGNALEMENT.get(type_.lower(), SIGNALEMENT_PAR_DEFAUT)
    titre = (info.title or "").replace("\n", " ").strip()
    morceaux = ["Signalement"] + [x for x in (precision or type_, titre) if x]
    # Pas deux fois la même chose (« Arbre sur la chaussée · Arbre sur la chaussée »).
    vus, uniques = set(), []
    for x in morceaux:
        if x.lower() not in vus:
            vus.add(x.lower())
            uniques.append(x)
    note = _SEPARATEUR.join(uniques)
    return note if len(note) <= NOTE_SIGNALEMENT_MAX else note[:NOTE_SIGNALEMENT_MAX - 1].rstrip() + "…"


def signalement_en_marqueur(info):
    """Un signalement du public devient un marqueur de sa crise (26/11/2026) : affiché sur les
    cartes (site, application) et émis par radio sur le canal de crise dès le dépôt. Sans crise,
    rien. Rend le marqueur ou None ; ne lève jamais."""
    try:
        from .models import MarqueurTerrain

        if not info.actif or info.location is None:
            return None
        deja = MarqueurTerrain.objects.filter(signalement_id=info.id).first()
        if deja is not None:
            return deja
        crise = crise_du_signalement(info)
        if crise is None:
            return None
        type_ = (str(info.information_type) if info.information_type_id else "").strip().lower()
        emoji, _precision = MARQUEUR_DU_SIGNALEMENT.get(type_, SIGNALEMENT_PAR_DEFAUT)
        m, cree = enregistrer(
            info.environment, emoji, info.location.y, info.location.x, note_du_signalement(info), crise=crise,
            auteur_libre="Signalement du public", source=MarqueurTerrain.Source.SIGNALEMENT,
            diffuser_radio=True, prevenir=False, signalement_id=info.id,
        )
        if cree and m.genre != "INFO":
            prevenir_regulation(m)
        return m
    except Exception:
        logger.exception("Signalement %s non posé sur la carte.", getattr(info, "id", None))
        return None


def signalement_retire(info):
    """Le signalement désactivé : son marqueur aussi (sans rien émettre)."""
    try:
        from .models import MarqueurTerrain

        for m in MarqueurTerrain.objects.filter(signalement_id=info.id, actif=True):
            m.actif = False
            m.save(update_fields=["actif", "modifie_le"])
    except Exception:
        logger.exception("Marqueur du signalement %s non retiré.", getattr(info, "id", None))


def signalement_enregistre(sender, instance, created, raw=False, **kwargs):
    """post_save d'un signalement : posé sur la carte à la création, retiré à la désactivation.
    Après la validation de la transaction, pour lire le type et la crise enregistrés."""
    if raw:
        return
    from django.db import transaction

    if instance.actif:
        if created:
            transaction.on_commit(lambda: signalement_en_marqueur(instance))
    else:
        transaction.on_commit(lambda: signalement_retire(instance))


def _destinataires(marqueur):
    """Le régulateur et le chef des équipes engagées sur la crise, et les acteurs des
    institutions de ses missions en cours (comme messages_terrain.alerter) ; le bureau pour une
    manifestation. En formation, l'auteur seul."""
    from django.db.models import Q

    from .models import ContactInstitution, Environment, Mission, User
    from .permissions import INSTITUTIONAL_TYPES

    if marqueur.environment == Environment.DEMO:
        return {marqueur.auteur} if marqueur.auteur_id else set()
    gens = set()
    if marqueur.crise_id:
        missions = Mission.objects.filter(crise_id=marqueur.crise_id, statut=Mission.Statut.EN_COURS).prefetch_related("equipes")
        institutions = set()
        for mission in missions:
            if mission.institution_id:
                institutions.add(mission.institution_id)
            for equipe in mission.equipes.all():
                gens |= {u for u in (equipe.regulateur, equipe.leader) if u is not None}
        if institutions:
            membres = ContactInstitution.objects.filter(institution_id__in=institutions, actif=True).values("utilisateur_id")
            gens |= set(User.objects.filter(Q(institution_id__in=institutions) | Q(id__in=membres),
                                            type__in=INSTITUTIONAL_TYPES, is_active=True))
    if marqueur.manifestation_id:
        bureau = ContactInstitution.objects.filter(institution_id=marqueur.manifestation.institution_id, actif=True,
                                                   membre_bureau=True).values("utilisateur_id")
        gens |= set(User.objects.filter(id__in=bureau, is_active=True))
    gens.discard(marqueur.auteur)
    return {u for u in gens if u is not None}


def prevenir_regulation(marqueur):
    """Le régulateur est prévenu tout de suite (notification qui s'impose) pour décider du
    traitement ; la cellule de crise le voit aussi dans sa conversation. Une route libérée
    prévient sans urgence. Ne lève jamais."""
    from . import conversations as conv
    from .models import Environment, GenreConversation, SourceMessage
    from .notifications_application import prevenir

    try:
        nom = libelle(marqueur)
        urgent = marqueur.genre != "ROUTE_LIBEREE"
        prefixe = "[DEMO] " if marqueur.environment == Environment.DEMO else ""
        titre = f"{prefixe}{marqueur.emoji} {nom} signalé sur le terrain"
        corps = (f"{nom}{' — ' + marqueur.note if marqueur.note else ''}\n"
                 f"Par : {nom_auteur(marqueur)} ({marqueur.get_source_display()})\n"
                 f"Position : {marqueur.location.y:.5f}, {marqueur.location.x:.5f}\n"
                 "À traiter sur la page Terrain du pilotage.")
        lien = "/pilotage/terrain" if marqueur.crise_id else (
            f"/manifestations?m={marqueur.manifestation_id}" if marqueur.manifestation_id else "")
        for u in _destinataires(marqueur):
            prevenir(u, titre, corps, urgent=urgent, lien=lien, crise=marqueur.crise, environment=marqueur.environment)
        if marqueur.crise_id and marqueur.environment != Environment.DEMO:
            cellule = conv.conversation_crise(marqueur.crise, GenreConversation.CELLULE, environment=marqueur.environment)
            conv.ecrire(cellule, f"{titre} — {corps}", auteur_libre="Marqueurs terrain", source=SourceMessage.SYSTEME,
                        urgent=urgent, dedupliquer=False)
    except Exception:
        logger.exception("Régulation non prévenue du marqueur %s.", marqueur.id)


def _missions_de(utilisateur):
    from django.db.models import Q

    from .models import Mission
    return Mission.objects.filter(
        Q(equipes__members=utilisateur) | Q(equipes__leader=utilisateur) | Q(equipes__regulateur=utilisateur),
        crise__isnull=False)


def voit_la_crise(utilisateur, crise) -> bool:
    """Acteur institutionnel, ou membre (chef, régulateur) d'une équipe engagée sur une mission de la crise."""
    from .permissions import INSTITUTIONAL_TYPES
    if getattr(utilisateur, "type", None) in INSTITUTIONAL_TYPES:
        return True
    return _missions_de(utilisateur).filter(crise=crise).exists()


def visibles_par(utilisateur, environment):
    """Les marqueurs qu'une personne voit : ceux des crises (acteur institutionnel, ou membre
    d'une équipe engagée sur une mission de la crise) et ceux des manifestations qu'elle voit."""
    from django.db.models import Q

    from . import manifestations as mf
    from .models import MarqueurTerrain
    from .permissions import INSTITUTIONAL_TYPES

    qs = MarqueurTerrain.objects.filter(environment=environment).select_related("auteur")
    if getattr(utilisateur, "type", None) in INSTITUTIONAL_TYPES:
        crises = Q(crise__isnull=False)
    else:
        crises = Q(crise_id__in=_missions_de(utilisateur).values("crise_id"))
    manifs = Q(manifestation_id__in=mf.visibles_par(utilisateur, environment).values("id"))
    return qs.filter(crises | manifs).distinct()


def en_dict(m):
    return {
        "id": str(m.id), "crise": str(m.crise_id) if m.crise_id else None,
        "manifestation": str(m.manifestation_id) if m.manifestation_id else None,
        "emoji": m.emoji, "genre": m.genre, "libelle": libelle(m), "route": m.genre in ROUTES,
        "latitude": m.location.y, "longitude": m.location.x, "note": m.note,
        "auteur_nom": nom_auteur(m), "source": m.source, "source_libelle": m.get_source_display(),
        "canal_nom": m.canal_nom, "signalement": str(m.signalement_id) if m.signalement_id else None, "cree_le": m.cree_le, "actif": m.actif,
        "decision": m.decision, "decision_libelle": m.get_decision_display(),
        "traite_le": m.traite_le, "remplace": str(m.remplace_id) if m.remplace_id else None,
        "texte_radio": texte_radio(m),
    }
