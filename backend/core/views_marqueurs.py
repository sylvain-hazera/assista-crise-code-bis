"""API des marqueurs terrain (26/11/2026) — voir core/marqueurs_terrain.py.

- `GET marqueurs-terrain/?crise=…&manifestation=…` : les marqueurs actifs que je vois
  (`tous=1` : avec l'historique et les clos) ;
- `POST marqueurs-terrain/` : poser un marqueur (application ou site) ; il repart par la radio
  sur les canaux de la crise et prévient la régulation ;
- `PATCH marqueurs-terrain/<id>/` : changer l'état d'une route (`etat_route`, terrain et PC), ou
  la décision du régulateur (`decision`, encadrement seulement).
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from . import manifestations as mf
from . import marqueurs_terrain as mt
from .models import Crisis, Manifestation, MarqueurTerrain
from .permissions import INSTITUTIONAL_TYPES, get_active_environment, get_effective_role


def _coordonnee(valeur, champ, borne):
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        raise ValidationError({"detail": f"{champ} : nombre attendu."})
    if not -borne <= v <= borne:
        raise ValidationError({"detail": f"{champ} hors bornes."})
    return v


def _diffusion(d):
    """`deja_par_radio` : vrai (déjà parti partout, rien à rediffuser), ou le protocole sur le
    canal de crise duquel le téléphone l'a déjà émis (l'autre réseau reste servi)."""
    deja = d.get("deja_par_radio")
    if deja is True or deja in ("true", "1"):
        return False, None
    return True, deja if deja in ("MESHTASTIC", "MESHCORE") else None


def _encadre(request, m) -> bool:
    """Le régulateur décide : acteur institutionnel pour une crise, bureau pour une manifestation."""
    if m.manifestation_id and mf.organise(request.user, m.manifestation.institution_id):
        return True
    return get_effective_role(request) in INSTITUTIONAL_TYPES


class MarqueursTerrainView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        env = get_active_environment(request)
        qs = mt.visibles_par(request.user, env).select_related("manifestation")
        if request.query_params.get("crise"):
            qs = qs.filter(crise_id=request.query_params["crise"])
        if request.query_params.get("manifestation"):
            qs = qs.filter(manifestation_id=request.query_params["manifestation"])
        if request.query_params.get("tous") != "1":
            qs = qs.filter(actif=True).exclude(decision=MarqueurTerrain.Decision.CLOS)
        return Response([mt.en_dict(m) for m in qs[:500]])

    def post(self, request):
        env = get_active_environment(request)
        d = request.data
        emoji = str(d.get("emoji") or "").strip()[:16]
        if not emoji:
            raise ValidationError({"detail": "Choisissez le genre du marqueur."})
        lat = _coordonnee(d.get("latitude"), "Latitude", 90)
        lon = _coordonnee(d.get("longitude"), "Longitude", 180)
        crise = manifestation = None
        if d.get("crise"):
            crise = Crisis.objects.filter(id=d["crise"], environment=env).first()
            if crise is None:
                raise ValidationError({"detail": "Crise inconnue."})
            if not mt.voit_la_crise(request.user, crise):
                raise PermissionDenied("Réservé aux intervenants de cette crise.")
        if d.get("manifestation"):
            manifestation = mf.visibles_par(request.user, env).filter(id=d["manifestation"]).first()
            if manifestation is None:
                raise PermissionDenied("Manifestation introuvable, ou réservée aux membres de l'association.")
        if crise is None and manifestation is None:
            raise ValidationError({"detail": "Le marqueur doit appartenir à une crise ou à une manifestation."})
        source = MarqueurTerrain.Source.APPLICATION if d.get("source") == "APPLICATION" else MarqueurTerrain.Source.SITE
        # Depuis l'application, un marqueur se pose seulement en phase de crise ou de
        # manifestation (28/11/2026). Le site garde la main pour préparer une manifestation.
        if source == MarqueurTerrain.Source.APPLICATION:
            if crise is not None and crise.end_date is not None:
                raise ValidationError({"detail": "Cette crise est close : on n'y pose plus de marqueur."})
            if crise is None and not mf.en_cours(manifestation):
                raise ValidationError({"detail": "Cette manifestation n'est pas en cours : le marqueur se pose pendant qu'elle a lieu."})
        diffuser, sauf = _diffusion(d)
        m, cree = mt.enregistrer(env, emoji, lat, lon, str(d.get("note") or "")[:500], crise=crise,
                                 manifestation=manifestation, auteur=request.user, source=source,
                                 diffuser_radio=diffuser, sauf_protocole=sauf)
        return Response(mt.en_dict(m), status=status.HTTP_201_CREATED if cree else status.HTTP_200_OK)


class MarqueurTerrainView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        env = get_active_environment(request)
        m = mt.visibles_par(request.user, env).select_related("manifestation").filter(id=pk).first()
        if m is None:
            raise PermissionDenied("Marqueur introuvable.")
        d = request.data
        if "etat_route" in d:
            if m.genre not in mt.ROUTES:
                raise ValidationError({"detail": "Seule une route change d'état."})
            etat = mt.ETATS_ROUTE.get(d["etat_route"])
            if etat is None:
                raise ValidationError({"detail": "État de route inconnu."})
            # La précision de sens change, la note libre reste (ou celle donnée).
            libre = str(d["note"]) if "note" in d else mt.note_libre(m.note)
            nouveau, _cree = mt.enregistrer(
                env, etat[0], m.location.y, m.location.x, mt.note_de_route(d["etat_route"], libre)[:500], crise=m.crise,
                manifestation=m.manifestation, auteur=request.user,
                source=MarqueurTerrain.Source.APPLICATION if d.get("source") == "APPLICATION" else MarqueurTerrain.Source.SITE,
                diffuser_radio=_diffusion(d)[0], sauf_protocole=_diffusion(d)[1])
            return Response(mt.en_dict(nouveau))
        if "decision" in d:
            if not _encadre(request, m):
                raise PermissionDenied("Réservé à la régulation.")
            if d["decision"] not in (MarqueurTerrain.Decision.PRIS_EN_COMPTE, MarqueurTerrain.Decision.CLOS,
                                     MarqueurTerrain.Decision.A_TRAITER):
                raise ValidationError({"detail": "Décision inconnue."})
            m.decision = d["decision"]
            m.traite_par, m.traite_le = request.user, timezone.now()
            if m.decision == MarqueurTerrain.Decision.CLOS:
                m.actif = False
            m.save(update_fields=["decision", "traite_par", "traite_le", "actif", "modifie_le"])
            return Response(mt.en_dict(m))
        raise ValidationError({"detail": "Rien à modifier."})
