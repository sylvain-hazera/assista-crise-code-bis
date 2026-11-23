"""Tableau radio MeshCore (23/11/2026) : ce que les observateurs MQTT, le flux CoreScope, la
cartographie publique et nos companions ont recueilli, enfin affiché.

Rien n'est inventé ici : chaque bloc lit une table déjà remplie.
- **Trafic** : `CompteurPaquetsMeshCore` (trames décodées par type, par récepteur, par heure ;
  écrit par le service des observateurs et par nos companions, purgé à 30 jours).
- **Liaisons** : `LiaisonMeshCore` (réception directe avec SNR, relais consécutifs d'un chemin).
- **Relais publics** : `NoeudPublicMeshCore` (cartographie importée d'une instance CoreScope).
- **Observateurs** : `EtatObservateurMeshCore` (leurs messages d'état) et les sources
  configurées (`SourceObservateurMeshCore`, sans jamais leurs identifiants de connexion).
"""
import datetime
from collections import defaultdict

from django.db.models import Count, Max, Sum
from django.utils import timezone

FENETRES = {"6h": datetime.timedelta(hours=6), "24h": datetime.timedelta(hours=24), "7j": datetime.timedelta(days=7)}
#: Les valeurs d'état que l'écran sait nommer, si l'observateur les publie (voir EtatObservateurMeshCore).
MESURES_CONNUES = ("battery_mv", "noise_floor", "uptime_secs", "last_rssi", "last_snr", "recv", "sent")
SILENCE = datetime.timedelta(hours=1)


def _noms(cles, environment):
    """Le nom de chaque clé publique (ou préfixe) : cartographie publique, companions, contacts,
    observateurs qui se nomment eux-mêmes."""
    from .models import CompagnonMeshCore, ContactMeshCore, EtatObservateurMeshCore, NoeudPublicMeshCore

    cles = {c.lower() for c in cles if c}
    noms = {}
    for modele, champ in ((EtatObservateurMeshCore, "origine"), (ContactMeshCore, "nom"), (NoeudPublicMeshCore, "nom")):
        filtre = {"environment": environment} if hasattr(modele, "environment") else {}
        for cle, nom in modele.objects.filter(pubkey_hex__in=cles, **filtre).values_list("pubkey_hex", champ):
            if nom:
                noms.setdefault(cle.lower(), nom)
    for cle, nom in CompagnonMeshCore.objects.filter(pubkey_hex__in=cles).values_list("pubkey_hex", "nom"):
        if nom:
            noms[cle.lower()] = f"{nom} (companion)"
    return noms


def construire(environment, fenetre="24h", maintenant=None):
    from .models import (
        CompteurPaquetsMeshCore, EtatObservateurMeshCore, LiaisonMeshCore, NoeudPublicMeshCore,
        SourceObservateurMeshCore,
    )

    maintenant = maintenant or timezone.now()
    duree = FENETRES.get(fenetre, FENETRES["24h"])
    debut = maintenant - duree
    pas = datetime.timedelta(hours=6) if duree > datetime.timedelta(days=1) else datetime.timedelta(hours=1)

    # ── Trafic ──
    compteurs = CompteurPaquetsMeshCore.objects.filter(environment=environment, heure__gte=debut)
    par_type = {t: n for t, n in compteurs.values_list("type_paquet").annotate(n=Sum("nombre")).values_list("type_paquet", "n")}
    series = defaultdict(int)
    for heure, n in compteurs.values_list("heure").annotate(n=Sum("nombre")).values_list("heure", "n"):
        seau = debut + ((heure - debut) // pas) * pas if heure >= debut else debut
        series[seau] += n
    courbe = []
    t = debut
    while t < maintenant:
        courbe.append({"debut": t.isoformat(), "trames": series.get(t, 0)})
        t += pas
    recepteurs = list(compteurs.values("recepteur_pubkey_hex").annotate(n=Sum("nombre"), derniere=Max("heure"))
                      .order_by("-n")[:15])

    # ── Liaisons ──
    liaisons = LiaisonMeshCore.objects.filter(environment=environment, dernier_vu__gte=debut)
    par_source = dict(liaisons.values_list("source").annotate(n=Count("id")).values_list("source", "n"))
    entendus = liaisons.values("emetteur_prefixe_hex").distinct().count()
    ecoutants = liaisons.values("recepteur_pubkey_hex").distinct().count()

    # ── Relais publics (CoreScope) ──
    publics = NoeudPublicMeshCore.objects.filter(environment=environment)
    repeteurs = publics.filter(role__iexact="repeater")
    meilleurs = list(repeteurs.exclude(score_utilite=None).order_by("-score_utilite")
                     .values("pubkey_hex", "nom", "score_utilite", "note_utilite", "dernier_vu", "relais_actif")[:10])
    instances = sorted({i for i in publics.values_list("instance", flat=True).distinct() if i})
    derniere_import = publics.aggregate(m=Max("date_import"))["m"]

    # ── Observateurs ──
    etats = list(EtatObservateurMeshCore.objects.filter(environment=environment).order_by("-recu_le")[:100])
    trames_par = dict(compteurs.values_list("recepteur_pubkey_hex").annotate(n=Sum("nombre")).values_list("recepteur_pubkey_hex", "n"))

    noms = _noms([r["recepteur_pubkey_hex"] for r in recepteurs] + [e.pubkey_hex for e in etats], environment)

    return {
        "fenetre": fenetre if fenetre in FENETRES else "24h",
        "calcule_le": maintenant.isoformat(),
        "trafic": {
            "total": sum(par_type.values()),
            "par_type": sorted(({"type": t or "INCONNU", "trames": n} for t, n in par_type.items()), key=lambda x: -x["trames"]),
            "courbe": courbe,
            "pas_heures": int(pas.total_seconds() // 3600),
            "recepteurs": [{
                "pubkey": r["recepteur_pubkey_hex"], "nom": noms.get(r["recepteur_pubkey_hex"].lower(), r["recepteur_pubkey_hex"][:12]),
                "trames": r["n"], "derniere_heure": r["derniere"].isoformat() if r["derniere"] else None,
            } for r in recepteurs],
        },
        "liaisons": {
            "reception_directe": par_source.get("RF", 0), "chemins": par_source.get("CHEMIN", 0),
            "voisinage": par_source.get("VOISINAGE", 0), "emetteurs_entendus": entendus, "recepteurs": ecoutants,
        },
        "relais_publics": {
            "repeteurs": repeteurs.count(),
            "repeteurs_vus": repeteurs.filter(dernier_vu__gte=debut).count(),
            "rooms": publics.filter(role__iexact="room").count(),
            "instances": instances,
            "derniere_import": derniere_import.isoformat() if derniere_import else None,
            "plus_utiles": [{
                "pubkey": m["pubkey_hex"], "nom": m["nom"] or m["pubkey_hex"][:12], "score": round(m["score_utilite"], 2),
                "note": m["note_utilite"], "actif": m["relais_actif"],
                "dernier_vu": m["dernier_vu"].isoformat() if m["dernier_vu"] else None,
            } for m in meilleurs],
        },
        "observateurs": [{
            "pubkey": e.pubkey_hex, "nom": e.origine or noms.get(e.pubkey_hex, e.pubkey_hex[:12]), "iata": e.iata,
            "recu_le": e.recu_le.isoformat(), "silencieux": maintenant - e.recu_le > SILENCE,
            "mesures": {k: e.mesures[k] for k in MESURES_CONNUES if k in e.mesures},
            "autres_mesures": len([k for k in e.mesures if k not in MESURES_CONNUES]),
            "trames": trames_par.get(e.pubkey_hex, 0),
        } for e in etats],
        "sources": [{
            "nom": s.nom, "type": s.type_source, "actif": s.actif, "etat": s.dernier_etat,
            "derniere_connexion": s.derniere_connexion.isoformat() if s.derniere_connexion else None,
        } for s in SourceObservateurMeshCore.objects.filter(environment=environment).order_by("nom")],
    }
