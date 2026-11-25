"""Ranger ce qui arrive par radio (23/11/2026). Règle de Sylvain : « je préfère des messages qui
tombent dans un pot commun et à trier manuellement que des messages perdus ».

Tout message de canal reçu — par une passerelle (`MessageCanalMeshtastic`/`MessageCanalMeshCore`
ENTRANT) ou par la radio d'un téléphone qui le remonte à son retour (`/api/radio/entendus/`) —
passe par `ranger()` :

- **canal de crise** (un par crise, clé publique, Meshtastic et son jumeau MeshCore) :
  1. toujours dans la conversation CRISE (le fil du canal, tel que les radios l'entendent) ;
  2. et rangé : étiquette de terrain `⚑` → conversation de l'équipe du message de terrain ;
     `@INDICATIF` d'une équipe engagée → conversation de l'équipe ; `@PC` (ou `@CELLULE`,
     `@REGUL`) → conversation de la cellule ; **sinon → pot commun (À trier)** ;
  3. relayé sur le canal de crise de l'autre protocole (« Nom: texte »), sauf l'écho de nos
     propres émissions et ce qu'un téléphone remonte après coup.
- **ancien canal d'une équipe** → conversation de l'équipe (transition : rien de perdu).
- **canal de la commune** → pot commun des crises ouvertes de l'institution.
- **Fr_EMCOM** → conversation communautaire. `Fr_Balise` (positions) n'est pas recopié.
"""
import logging
import re

from django.utils import timezone

from .models import GenreConversation, SourceMessage

logger = logging.getLogger(__name__)

ADRESSE = re.compile(r"^\s*@([A-Za-z0-9]{2,8})\b[\s:,]*(.*)$", re.DOTALL)
ADRESSES_CELLULE = {"PC", "CELLULE", "REGUL", "CODIS", "CDC"}
PREFIXE_NOM = re.compile(r"^\s*([^:\n@⚑]{1,32}):\s+(.*)$", re.DOTALL)
CANAUX_COMMUNAUTAIRES_RECOPIES = {"fr_emcom"}


def separer_auteur(texte):
    """MeshCore (et nos émissions préfixées) écrivent « Nom: texte » : rend (nom, texte)."""
    m = PREFIXE_NOM.match(texte or "")
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, (texte or "").strip()


def lire_adresse(texte):
    """« @ALPHA rdv au PC » → ("ALPHA", "rdv au PC") ; sans adresse → (None, texte)."""
    m = ADRESSE.match(texte or "")
    if not m:
        return None, (texte or "").strip()
    return m.group(1).upper(), m.group(2).strip()


def _equipe_par_indicatif(crise, indicatif):
    from .conversations import equipes_de_la_crise

    for equipe in equipes_de_la_crise(crise):
        if (equipe.indicatif or "").upper() == indicatif:
            return equipe
    return None


def ranger(canal, protocole, texte, *, auteur=None, auteur_libre=None, source=None, recu_par=None,
           emis_le=None, origine="", message_canal=None, terrain=None, relayer=True):
    """Range un message de canal (voir le module). Rend la liste des messages de conversation
    créés ou complétés. Ne lève jamais : le message radio d'origine est déjà enregistré."""
    try:
        return _ranger(canal, protocole, texte, auteur=auteur, auteur_libre=auteur_libre, source=source,
                       recu_par=recu_par, emis_le=emis_le, origine=origine, message_canal=message_canal,
                       terrain=terrain, relayer=relayer)
    except Exception:
        logger.exception("Message radio non rangé (canal %s).", getattr(canal, "id", None))
        return []


def _ranger(canal, protocole, texte, *, auteur, auteur_libre, source, recu_par, emis_le, origine,
            message_canal, terrain, relayer):
    from . import conversations as conv

    if canal is None or not (texte or "").strip():
        return []
    source = source or (SourceMessage.MESHTASTIC if protocole == "MESHTASTIC" else SourceMessage.MESHCORE)
    # MeshCore écrit toujours « Nom: texte » ; Meshtastic donne l'émetteur à part, et un texte
    # comme « Attention: route coupée » n'y porte pas de nom.
    corps = texte.strip()
    if protocole == "MESHCORE":
        nom, sans_nom = separer_auteur(texte)
        if nom:
            corps = sans_nom
            if auteur is None and not auteur_libre:
                auteur_libre = nom
    env = canal.environment
    lien = {"message_meshtastic" if protocole == "MESHTASTIC" else "message_meshcore": message_canal} if message_canal else {}
    commun = dict(auteur=auteur, auteur_libre=auteur_libre, source=source, recu_par=recu_par or [],
                  emis_le=emis_le, origine=origine, **lien)
    crees = []

    def ecrire(conversation, contenu, urgent=False):
        m, _ = conv.ecrire(conversation, contenu, urgent=urgent, **commun)
        crees.append(m)
        return m

    if getattr(canal, "equipe_id", None):
        ecrire(conv.conversation_du_contexte(canal.equipe, environment=env), corps)
        return crees

    if getattr(canal, "crise_id", None):
        crise = canal.crise
        ecrire(conv.conversation_crise(crise, environment=env), corps)
        indicatif, reste = lire_adresse(corps)
        cible = None
        if terrain is not None and getattr(terrain, "equipe_id", None):
            cible = conv.conversation_equipe(terrain.equipe, crise, environment=env)
        elif indicatif in ADRESSES_CELLULE:
            cible = conv.conversation_crise(crise, GenreConversation.CELLULE, environment=env)
        elif indicatif:
            equipe = _equipe_par_indicatif(crise, indicatif)
            if equipe is not None:
                cible = conv.conversation_equipe(equipe, crise, environment=env)
        if cible is None:
            cible = conv.conversation_crise(crise, GenreConversation.A_TRIER, environment=env)
            ecrire(cible, corps)
        else:
            ecrire(cible, reste if indicatif and terrain is None else corps,
                   urgent=bool(terrain is not None and getattr(terrain, "type", "") in ("DANGER", "PREMIERS_SECOURS")))
        if relayer:
            relayer_vers_autre_protocole(canal, protocole, auteur_libre or (conv.nom_auteur(crees[0]) if crees else ""), corps)
        return crees

    nom_canal = (getattr(canal, "nom", "") or "").lstrip("#").lower()
    if nom_canal in CANAUX_COMMUNAUTAIRES_RECOPIES:
        ecrire(conv.conversation_communautaire(canal.nom, env), corps)
        return crees

    if getattr(canal, "institution_id", None):
        from .canaux_locaux import crises_de
        for crise in crises_de(canal.institution):
            ecrire(conv.conversation_crise(crise, GenreConversation.A_TRIER, environment=env), corps)
    return crees


def relayer_vers_autre_protocole(canal, protocole, auteur, corps):
    """Recopie sur le canal de crise de l'autre protocole (décision du 23/11/2026). L'écho de
    cette recopie, réentendu par l'autre passerelle, est reconnu par `_echo_de_nos_messages`
    (le texte émis est enregistré SORTANT)."""
    from .models import (
        CanalMeshCore, CanalMeshtastic, DirectionMessageMesh, MessageCanalMeshCore, MessageCanalMeshtastic,
        StatutMessageMesh,
    )

    if protocole == "MESHTASTIC":
        autre, modele = CanalMeshCore.objects.filter(crise_id=canal.crise_id, equipe__isnull=True, actif=True).first(), MessageCanalMeshCore
    else:
        autre, modele = CanalMeshtastic.objects.filter(crise_id=canal.crise_id, equipe__isnull=True, actif=True).first(), MessageCanalMeshtastic
    if autre is None:
        return None
    contenu = f"{auteur}: {corps}" if auteur else corps
    return modele.objects.create(canal=autre, direction=DirectionMessageMesh.SORTANT, expediteur=None, contenu=contenu,
                                 statut=StatutMessageMesh.EN_ATTENTE, environment=autre.environment)


def ranger_message_canal(message, protocole, terrain=None, recu_par=None):
    """Un message de canal ENTRANT posé par une passerelle : rangé, sauf l'écho des nôtres."""
    from .models import MessageCanalMeshCore, MessageCanalMeshtastic
    from .views import _echo_de_nos_messages

    modele = MessageCanalMeshtastic if protocole == "MESHTASTIC" else MessageCanalMeshCore
    if _echo_de_nos_messages(modele, message.contenu):
        return []
    auteur_libre = None
    auteur = message.expediteur
    if terrain is not None and getattr(terrain, "auteur_id", None):
        auteur = terrain.auteur
    if auteur is None:
        if protocole == "MESHTASTIC" and message.contact_node_num is not None:
            auteur_libre = _nom_noeud_meshtastic(message.contact_node_num)
    return ranger(message.canal, protocole, message.contenu, auteur=auteur, auteur_libre=auteur_libre,
                  recu_par=recu_par, emis_le=message.date_creation or timezone.now(), message_canal=message,
                  terrain=terrain)


def _nom_noeud_meshtastic(node_num):
    from .models import ContactMeshtastic

    contact = ContactMeshtastic.objects.filter(node_num=node_num).order_by("-id").first()
    nom = (contact.long_name if contact else "") or ""
    return nom or f"!{node_num:08x}"


# ══ Indicatifs ════════════════════════════════════════════════════════════════

def proposer_indicatif(nom, pris=()):
    """« Équipe Alpha » → « ALPH » ; « Bénévoles — Rive-de-Gier » → « BENE »… unique parmi `pris`."""
    import unicodedata

    sans_accents = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode()
    mots = [re.sub(r"[^A-Za-z0-9]", "", m).upper() for m in sans_accents.split()]
    mots = [m for m in mots if m and m not in {"EQUIPE", "TEAM", "LA", "LE", "LES", "DE", "DU", "DES"}]
    # 4 caractères au plus (25/11/2026, conseil d'Olivier F4GLD) : l'indicatif voyage dans
    # chaque message, sur ~200 octets utiles. Saisi à la main, il peut aller jusqu'à 6.
    base = (mots[0] if mots else "EQ")[:4]
    if len(base) < 2:
        base = (base + "".join(mots[1:2]) + "EQ")[:4]
    if base not in pris:
        return base
    for n in range(2, 100):
        candidat = base[:4 - len(str(n))] + str(n)
        if candidat not in pris:
            return candidat
    return base


def attribuer_indicatif(equipe, crise):
    """Donne à l'équipe un indicatif unique parmi les équipes de la crise, s'il lui en manque un
    ou si le sien est déjà pris par une autre. Rend l'indicatif."""
    from .conversations import equipes_de_la_crise

    autres = {(e.indicatif or "").upper() for e in equipes_de_la_crise(crise).exclude(pk=equipe.pk)} | ADRESSES_CELLULE
    actuel = (equipe.indicatif or "").upper()
    if actuel and actuel not in autres:
        return actuel
    equipe.indicatif = proposer_indicatif(equipe.name, autres)
    equipe.save(update_fields=["indicatif"])
    return equipe.indicatif
