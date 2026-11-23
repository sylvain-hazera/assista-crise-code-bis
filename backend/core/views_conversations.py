"""API de la messagerie interne (23/11/2026, core/conversations.py) et remontée de ce que les
radios des téléphones ont entendu (core/routage_canaux.py).

- `GET  /api/conversations/` : mes conversations (titre, genre, non-lus, peut écrire).
- `GET  /api/conversations/<id>/messages/?depuis=` : les messages (et marque lu).
- `POST /api/conversations/<id>/messages/ {texte, urgent?, identifiant?, deja_emis_radio?}`.
- `POST /api/conversations/a-trier/<message>/ranger/ {equipe | dossier | classer, commentaire?}`.
- `POST /api/radio/entendus/ {messages: [...]}` : ce qu'un téléphone a entendu par radio.
- `GET  /api/radio/plan/?crise=` : le plan de canaux de la crise (clés publiques seulement).
"""
import hashlib

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import permissions, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from . import conversations as conv
from .audit import audit_log
from .models import Conversation, GenreConversation, MessageConversation, SourceMessage
from .permissions import get_active_environment

SOURCES_AFFICHEES = {
    SourceMessage.APPLICATION: "application", SourceMessage.SITE: "site", SourceMessage.MESHTASTIC: "meshtastic",
    SourceMessage.MESHCORE: "meshcore", SourceMessage.TELEPHONE_RADIO: "radio", SourceMessage.MATRIX: "historique",
    SourceMessage.SYSTEME: "systeme",
}


def _message(m, request):
    return {
        "id": str(m.id), "texte": m.texte, "auteur": conv.nom_auteur(m, request),
        "auteur_id": str(m.auteur_id) if m.auteur_id else None, "moi": m.auteur_id == request.user.id,
        "source": SOURCES_AFFICHEES.get(m.source, "site"), "recu_par": len(m.recu_par or []),
        "urgent": m.urgent, "emis_le": m.emis_le.isoformat(),
        "range_le": m.range_le.isoformat() if m.range_le else None, "range_vers": m.range_vers or None,
    }


def _conversation(c, request):
    return {
        "id": str(c.id), "genre": c.genre, "titre": conv.titre(c, request.user, request),
        "crise": str(c.crise_id) if c.crise_id else None, "equipe": str(c.equipe_id) if c.equipe_id else None,
        "indicatif": (c.equipe.indicatif or None) if c.equipe_id else None,
        "non_lus": conv.non_lus(request.user, c),
        "dernier_message_le": c.dernier_message_le.isoformat() if c.dernier_message_le else None,
        "peut_ecrire": conv.peut_ecrire(request.user, c),
    }


def _obtenir(request, ident):
    c = Conversation.objects.filter(pk=ident, environment=get_active_environment(request)).select_related(
        "equipe", "crise").first() if ident else None
    if c is None:
        raise NotFound("Conversation introuvable.")
    if not conv.peut_lire(request.user, c):
        raise PermissionDenied("Cette conversation ne vous est pas ouverte.")
    return c


class ConversationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response([_conversation(c, request)
                         for c in conv.mes_conversations(request.user, get_active_environment(request))])


class MessagesConversationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, ident):
        c = _obtenir(request, ident)
        qs = c.messages.select_related("auteur")
        depuis = parse_datetime(request.query_params.get("depuis") or "")
        if depuis is not None:
            qs = qs.filter(emis_le__gt=depuis).order_by("emis_le")[:500]
            messages = list(qs)
        else:
            messages = list(qs.order_by("-emis_le")[:200])
            messages.reverse()
        conv.marquer_lu(request.user, c)
        return Response({"conversation": _conversation(c, request), "messages": [_message(m, request) for m in messages]})

    def post(self, request, ident):
        from .routage_canaux import attribuer_indicatif

        c = _obtenir(request, ident)
        if not conv.peut_ecrire(request.user, c):
            raise PermissionDenied("On n'écrit pas ici.")
        texte = (request.data.get("texte") or "").strip()
        if not texte:
            raise ValidationError({"error": "texte requis."})
        deja = {p.strip() for p in str(request.data.get("deja_emis_radio") or "").upper().split(",") if p.strip()}
        source = SourceMessage.APPLICATION if request.data.get("source") == "APPLICATION" or deja else SourceMessage.SITE
        message, _ = conv.ecrire(c, texte, auteur=request.user, source=source, urgent=bool(request.data.get("urgent")),
                                 origine=str(request.data.get("identifiant") or "")[:120])
        if c.genre == GenreConversation.EQUIPE and c.crise_id:
            attribuer_indicatif(c.equipe, c.crise)
            conv.diffuser_radio(message, equipe=c.equipe, crise=c.crise, deja_emis=deja, auteur=request.user)
        elif c.genre == GenreConversation.EQUIPE:
            conv.diffuser_radio(message, equipe=c.equipe, deja_emis=deja, auteur=request.user)
        elif c.genre in (GenreConversation.CRISE, GenreConversation.CELLULE):
            conv.diffuser_radio(message, crise=c.crise, deja_emis=deja, auteur=request.user)
        conv.marquer_lu(request.user, c)
        return Response(_message(message, request), status=status.HTTP_201_CREATED)


class ATrierView(APIView):
    """GET /api/conversations/a-trier/?crise= : le pot commun d'une crise (messages non rangés),
    et les équipes vers lesquelles ranger. Réservé aux trieurs (403 sinon : le pilotage masque
    alors le bloc)."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .models import Crisis

        crise = Crisis.objects.filter(pk=request.query_params.get("crise") or None).first()
        if crise is None:
            raise ValidationError({"error": "Crise introuvable."})
        if not conv.peut_trier(request.user, crise):
            raise PermissionDenied("Le tri revient à l'équipe transmissions, à défaut à la régulation.")
        c = conv.conversation_crise(crise, GenreConversation.A_TRIER, environment=get_active_environment(request))
        messages = list(c.messages.filter(range_le__isnull=True).select_related("auteur").order_by("emis_le")[:300])
        mode, _ = conv.trieurs_de(crise)
        return Response({
            "conversation": str(c.id), "trie_par": mode,
            "messages": [_message(m, request) for m in messages],
            "equipes": [{"id": str(e.id), "nom": e.name, "indicatif": e.indicatif or None}
                        for e in conv.equipes_de_la_crise(crise).order_by("name")],
        })


class RangerMessageView(APIView):
    """Le tri du pot commun : vers une équipe de la crise, en commentaire d'un dossier, ou classé
    sans suite. Équipe transmissions, à défaut la régulation (core/conversations.peut_trier)."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, ident):
        from .models import Dossier, DossierCommentaire, Team

        m = MessageConversation.objects.filter(pk=ident, conversation__genre=GenreConversation.A_TRIER,
                                               environment=get_active_environment(request)).select_related(
            "conversation__crise").first()
        if m is None:
            raise NotFound("Message à trier introuvable.")
        crise = m.conversation.crise
        if not conv.peut_trier(request.user, crise):
            raise PermissionDenied("Le tri revient à l'équipe transmissions, à défaut à la régulation.")
        if m.range_le is not None:
            raise ValidationError({"error": f"Déjà rangé ({m.range_vers})."})
        if request.data.get("equipe"):
            equipe = conv.equipes_de_la_crise(crise).filter(pk=request.data["equipe"]).first()
            if equipe is None:
                raise ValidationError({"error": "Équipe inconnue ou non engagée sur la crise."})
            cible = conv.conversation_equipe(equipe, crise, environment=m.environment)
            conv.ecrire(cible, m.texte, auteur=m.auteur, auteur_libre=m.auteur_libre, source=m.source,
                        recu_par=m.recu_par, emis_le=m.emis_le, origine=f"tri:{m.id}")
            vers = f"Équipe {equipe.name}"
        elif request.data.get("dossier"):
            dossier = Dossier.objects.filter(pk=request.data["dossier"], environment=m.environment).first()
            if dossier is None:
                raise ValidationError({"error": "Dossier introuvable."})
            DossierCommentaire.objects.create(
                dossier=dossier, auteur=request.user, environment=m.environment,
                commentaire=f"Reçu par radio ({conv.nom_auteur(m, request)}, {timezone.localtime(m.emis_le):%d/%m %H:%M}) : {m.texte}")
            vers = f"Dossier {getattr(dossier, 'numero', '') or str(dossier.id)[:8]}"
        elif request.data.get("classer"):
            vers = "Classé sans suite"
        else:
            raise ValidationError({"error": "Indiquez une équipe, un dossier, ou classer."})
        commentaire = (request.data.get("commentaire") or "").strip()
        m.range_par, m.range_le, m.range_vers = request.user, timezone.now(), (vers + (f" — {commentaire}" if commentaire else ""))[:200]
        m.save(update_fields=["range_par", "range_le", "range_vers"])
        audit_log(request=request, action_code="MODIFICATION", objet_type="MessageConversation", objet_id=m.id,
                  crise=crise, commentaire=f"Pot commun : {vers}")
        return Response(_message(m, request))


class RadioEntendusView(APIView):
    """Ce que la radio d'un téléphone a entendu, remis au retour du réseau (lot 4). Chaque entrée :
    `protocole` (MESHTASTIC/MESHCORE), `canal` (nom), `auteur`, `texte`, `entendu_le` (ISO),
    `identifiant` (local, pour qu'un renvoi ne double rien). Rend les identifiants acceptés."""
    permission_classes = [permissions.IsAuthenticated]
    MAX = 500

    def post(self, request):
        from .models import CanalMeshCore, CanalMeshtastic, MessageCanalMeshCore, MessageCanalMeshtastic
        from .routage_canaux import ranger
        from .views import _echo_de_nos_messages

        entrees = request.data.get("messages")
        if not isinstance(entrees, list):
            raise ValidationError({"error": "messages : liste attendue."})
        appareil = (str(request.data.get("appareil") or "") or "téléphone")[:60]
        acceptes = []
        for e in entrees[: self.MAX]:
            if not isinstance(e, dict):
                continue
            ident = str(e.get("identifiant") or "")[:80]
            texte = str(e.get("texte") or "").strip()
            protocole = str(e.get("protocole") or "").upper()
            nom = str(e.get("canal") or "").strip()
            if not texte or protocole not in ("MESHTASTIC", "MESHCORE"):
                acceptes.append(ident)
                continue
            entendu = parse_datetime(str(e.get("entendu_le") or "")) or timezone.now()
            if timezone.is_naive(entendu):
                entendu = timezone.make_aware(entendu)
            entendu = min(entendu, timezone.now())
            modele_canal, modele_msg = ((CanalMeshtastic, MessageCanalMeshtastic) if protocole == "MESHTASTIC"
                                        else (CanalMeshCore, MessageCanalMeshCore))
            canal = _canal_par_nom(modele_canal, nom)
            if canal is not None and not _echo_de_nos_messages(modele_msg, texte, minutes=24 * 60):
                origine = "tel:" + hashlib.sha256(f"{request.user.id}|{ident or texte}|{entendu:%Y%m%d%H%M}".encode()).hexdigest()[:40]
                ranger(canal, protocole, texte, auteur_libre=(str(e.get("auteur") or "").strip()[:60] or None),
                       source=SourceMessage.TELEPHONE_RADIO, recu_par=[appareil], emis_le=entendu,
                       origine=origine, relayer=False)
            acceptes.append(ident)
        return Response({"acceptes": acceptes})


def _canal_par_nom(modele, nom):
    """Le canal Assista-Crise de ce nom (canal de crise ou ancien canal d'équipe, actif) ; les noms
    MeshCore se comparent sans le « # ». Comparaison sur `nom` (en clair : un nom de canal radio
    est public), jamais sur une clé chiffrée."""
    if not nom:
        return None
    cle = nom.lstrip("#").lower()
    for canal in modele.objects.filter(actif=True).filter(nom__iendswith=cle).select_related("crise", "equipe"):
        if canal.nom.lstrip("#").lower() == cle:
            return canal
    return None


class PlanRadioView(APIView):
    """Le plan de canaux d'une crise (lot 5) : Fr_Balise, Fr_EMCOM et le canal de crise, par
    protocole, avec une version (empreinte du plan). Clés publiques seulement."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .canaux_locaux import CANAUX_COMMUNAUTAIRES, canal_communautaire, canaux_de_crise
        from .models import Crisis

        crise = Crisis.objects.filter(pk=request.query_params.get("crise") or None).first()
        if crise is None:
            raise ValidationError({"error": "Crise introuvable."})
        if not conv.dans_la_crise(request.user, crise):
            raise PermissionDenied("Vous n'êtes pas engagé sur cette crise.")
        meshtastic, meshcore = canaux_de_crise(crise, get_active_environment(request))
        canaux_mt = []
        for nom in CANAUX_COMMUNAUTAIRES:
            c = canal_communautaire(nom)
            if c is not None and c.psk_hex:
                canaux_mt.append({"nom": c.nom, "psk_hex": c.psk_hex, "role": "communautaire"})
        canaux_mt.append({"nom": meshtastic.nom, "psk_hex": meshtastic.psk_hex, "role": "crise"})
        canaux_mc = [{"nom": meshcore.nom, "cle_hex": meshcore.cle_partagee_hex, "role": "crise"}]
        empreinte = hashlib.sha256(repr((canaux_mt, canaux_mc)).encode()).hexdigest()[:12]
        return Response({
            "crise": str(crise.id), "version": empreinte,
            "meshtastic": canaux_mt, "meshcore": canaux_mc,
            "adresse_cellule": "@PC",
            "avertissement": "Canal de crise lisible par tous : aucune donnée personnelle (nom, adresse, santé).",
        })

