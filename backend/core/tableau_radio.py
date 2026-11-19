"""Tableau radio d'une passerelle Meshtastic (19/11/2026).

Inspiré du rendu de l'intégration Home Assistant « Meshtastic UI » (Daring-Designs/meshtastic-ui-ha,
appréciée par Sylvain) : occupation du canal, temps d'antenne, batterie, paquets émis et reçus en
séries compactes, répartition du trafic par type, tableau des nœuds entendus, traceroutes. Seul le
principe est repris ; les données sont celles d'Assista-Crise :

- `MesureTelemetrieMeshtastic` : télémétrie reçue (DeviceMetrics de chaque nœud, LocalStats de la
  passerelle) ;
- `CompteurPaquetsMeshtastic` : paquets reçus par heure et par type ;
- `ContactMeshtastic` (sauts, dernière écoute), `LiaisonMeshtastic` (meilleur SNR reçu en direct) ;
- `TacheAdminMeshtastic` de type TRACEROUTE terminées.
"""
import datetime
import json

from django.utils import timezone

#: fenêtre -> (durée, pas de regroupement des séries)
FENETRES = {
    "1h": (datetime.timedelta(hours=1), datetime.timedelta(minutes=2)),
    "6h": (datetime.timedelta(hours=6), datetime.timedelta(minutes=10)),
    "24h": (datetime.timedelta(hours=24), datetime.timedelta(minutes=30)),
    "7j": (datetime.timedelta(days=7), datetime.timedelta(hours=3)),
}


def _seau(instant, debut, pas):
    return debut + ((instant - debut) // pas) * pas


def _moyennes(points, debut, pas):
    """[(instant, valeur)] -> [{t, v}] : moyenne par pas de temps, dans l'ordre."""
    seaux = {}
    for instant, valeur in points:
        if valeur is None:
            continue
        seaux.setdefault(_seau(instant, debut, pas), []).append(valeur)
    return [{"t": t.isoformat(), "v": round(sum(v) / len(v), 2)} for t, v in sorted(seaux.items())]


def _ecarts(points, debut, pas):
    """Compteurs cumulés depuis le démarrage du nœud -> paquets par pas de temps. Un compteur qui
    redescend signale un redémarrage : on repart de sa nouvelle valeur."""
    seaux, precedent = {}, None
    for instant, valeur in points:
        if valeur is None:
            continue
        if precedent is not None:
            ecart = valeur - precedent if valeur >= precedent else valeur
            cle = _seau(instant, debut, pas)
            seaux[cle] = seaux.get(cle, 0) + ecart
        precedent = valeur
    return [{"t": t.isoformat(), "v": v} for t, v in sorted(seaux.items())]


def construire_tableau(compagnon, fenetre="6h"):
    from .models import (
        CompteurPaquetsMeshtastic, ContactMeshtastic, LiaisonMeshtastic, MesureTelemetrieMeshtastic,
        SourceLiaisonMeshtastic, StatutTacheAdminMeshtastic, TacheAdminMeshtastic, TypeTacheAdminMeshtastic,
    )

    fenetre = fenetre if fenetre in FENETRES else "6h"
    duree, pas = FENETRES[fenetre]
    maintenant = timezone.now()
    debut = maintenant - duree
    moi = compagnon.node_num

    # ── Séries de la passerelle elle-même ───────────────────────────────────
    mesures = list(MesureTelemetrieMeshtastic.objects.filter(
        compagnon=compagnon, node_num=moi, horodatage__gte=debut).order_by("horodatage").values(
        "horodatage", "occupation_canal", "temps_antenne_tx", "batterie", "paquets_tx", "paquets_rx"))
    serie = lambda champ: [(m["horodatage"], m[champ]) for m in mesures]  # noqa: E731
    series = {
        "occupation_canal": _moyennes(serie("occupation_canal"), debut, pas),
        "temps_antenne_tx": _moyennes(serie("temps_antenne_tx"), debut, pas),
        "batterie": _moyennes(serie("batterie"), debut, pas),
        "paquets_tx": _ecarts(serie("paquets_tx"), debut, pas),
        "paquets_rx": _ecarts(serie("paquets_rx"), debut, pas),
    }

    # ── Trafic par type (compteurs horaires de la passerelle) ───────────────
    compteurs = CompteurPaquetsMeshtastic.objects.filter(
        compagnon=compagnon, heure__gte=debut - datetime.timedelta(hours=1))
    par_type = {}
    par_heure = {}
    for c in compteurs.values("type_paquet", "nombre", "heure"):
        par_type[c["type_paquet"]] = par_type.get(c["type_paquet"], 0) + c["nombre"]
        par_heure[c["heure"]] = par_heure.get(c["heure"], 0) + c["nombre"]
    types_paquets = sorted(({"type": t, "nombre": n} for t, n in par_type.items()), key=lambda x: -x["nombre"])
    series["paquets_recus_par_heure"] = [{"t": h.isoformat(), "v": n} for h, n in sorted(par_heure.items())]

    # ── Nœuds entendus ──────────────────────────────────────────────────────
    contacts = list(ContactMeshtastic.objects.filter(compagnon=compagnon))
    nums = [c.node_num for c in contacts]
    batteries = {}
    for m in MesureTelemetrieMeshtastic.objects.filter(
            compagnon=compagnon, node_num__in=nums, batterie__isnull=False,
            horodatage__gte=maintenant - datetime.timedelta(days=7)).order_by("-horodatage").values(
            "node_num", "batterie", "tension", "horodatage"):
        batteries.setdefault(m["node_num"], m)
    snr = dict(LiaisonMeshtastic.objects.filter(
        recepteur=moi, source=SourceLiaisonMeshtastic.RF, emetteur__in=nums).values_list("emetteur", "snr"))
    noms = {c.node_num: (c.long_name or c.short_name or f"!{c.node_num:08x}") for c in contacts}
    noeuds = []
    for c in contacts:
        vu = c.dernier_entendu or c.dernier_advert
        b = batteries.get(c.node_num)
        noeuds.append({
            "node_num": c.node_num, "id": f"!{c.node_num:08x}", "nom": noms[c.node_num],
            "nom_court": c.short_name or "", "materiel": c.hardware_model or "",
            "batterie": b["batterie"] if b else None, "tension": b["tension"] if b else None,
            "sauts": c.sauts, "snr": snr.get(c.node_num),
            "dernier_entendu": vu.isoformat() if vu else None,
            "position": bool(getattr(c, "location", None)),
        })
    noeuds.sort(key=lambda n: n["dernier_entendu"] or "", reverse=True)

    # ── Derniers traceroutes ────────────────────────────────────────────────
    traceroutes = []
    for t in TacheAdminMeshtastic.objects.filter(
            compagnon=compagnon, type_tache=TypeTacheAdminMeshtastic.TRACEROUTE,
            statut=StatutTacheAdminMeshtastic.TERMINEE).order_by("-date_reponse")[:20]:
        try:
            reponse = json.loads(t.reponse or "{}")
        except ValueError:
            continue
        nommer = lambda n: noms.get(n) or (f"!{n:08x}" if isinstance(n, int) else "?")  # noqa: E731
        traceroutes.append({
            "cible": t.node_num_cible, "cible_nom": nommer(t.node_num_cible),
            "date": t.date_reponse.isoformat() if t.date_reponse else None,
            "aller": [{"node_num": n, "nom": nommer(n)} for n in reponse.get("aller") or []],
            "snr_aller": reponse.get("snr_aller") or [],
            "retour": [{"node_num": n, "nom": nommer(n)} for n in reponse.get("retour") or []],
            "snr_retour": reponse.get("snr_retour") or [],
        })

    return {
        "fenetre": fenetre, "pas_s": int(pas.total_seconds()), "debut": debut.isoformat(),
        "passerelle": {"id": str(compagnon.id), "nom": compagnon.nom, "node_num": moi},
        "series": series, "types_paquets": types_paquets, "noeuds": noeuds, "traceroutes": traceroutes,
    }
