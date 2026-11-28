"""Ce qu'on partage sans connexion, « pour les copains » (28/11/2026).

Demande de Sylvain : une adresse unique, sans authentification, avec tout ce qui ne relève ni
d'une crise ni d'une manifestation — météo, réseau radio, propagation, veille du territoire.

RÈGLE DE LA PARTIE RADIO : l'infrastructure et le relief, jamais un appareil personnel, une clé
ou un accès.
- Répéteurs et rooms MeshCore seulement : la cartographie publique (CoreScope), nos relais, les
  répéteurs entendus. Jamais de companion ni de capteur (l'appareil de quelqu'un, souvent chez
  lui).
- Aucun nœud Meshtastic : sans rôle connu, rien ne distingue un relais du téléphone de quelqu'un.
- Ni institution, ni commentaire, ni liaison mesurée (elles situeraient des passerelles
  personnelles), ni traceroute, ni liste des nœuds entendus.
- Une couverture calculée ne sort que si quelqu'un qui a l'accès radio l'a publiée.
- La santé du réseau est agrégée : ni nom, ni position, ni nombre exact de passerelles.
"""
import datetime
import statistics

from django.utils import timezone

from .cartographie_meshcore import PREFIXES_MASQUES

ROLES_PUBLICS = {"repeater": "répéteur", "room": "room"}
TYPES_CONTACT = {"REPEATER": "repeater", "ROOM": "room"}
#: Au-delà, un nœud qu'on n'a plus entendu n'est plus montré.
OUBLI = datetime.timedelta(days=30)


def _masque(nom):
    return any((nom or "").startswith(p) for p in PREFIXES_MASQUES)


def radio_publique(environment, maintenant=None):
    """GeoJSON des répéteurs et rooms MeshCore, dédoublonnés par clé publique. La cartographie
    publique d'abord ; nos relais et les répéteurs entendus complètent ce qu'elle n'a pas."""
    from .models import ContactMeshCore, NoeudPublicMeshCore, RelaisMeshCore

    maintenant = maintenant or timezone.now()
    limite = maintenant - OUBLI
    vus = {}

    def ajouter(cle, lon, lat, nom, role, source, dernier_vu, actif):
        cle = (cle or "").lower()
        if not cle or cle in vus or _masque(nom):
            return
        vus[cle] = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
                    "properties": {"nom": nom or cle[:8], "role": role, "role_libelle": ROLES_PUBLICS[role],
                                   "source": source, "dernier_vu": dernier_vu.isoformat() if dernier_vu else None,
                                   "actif": bool(actif)}}

    for n in (NoeudPublicMeshCore.objects.filter(environment=environment, role__in=list(ROLES_PUBLICS))
              .exclude(location__isnull=True).only("pubkey_hex", "location", "nom", "role", "dernier_vu", "relais_actif")):
        if n.dernier_vu and n.dernier_vu < limite:
            continue
        ajouter(n.pubkey_hex, n.location.x, n.location.y, n.nom, n.role, "cartographie publique", n.dernier_vu, n.relais_actif)
    for r in (RelaisMeshCore.objects.filter(environment=environment, actif=True).exclude(location__isnull=True)
              .only("pubkey_hex", "location", "nom")):
        ajouter(r.pubkey_hex or f"relais-{r.id}", r.location.x, r.location.y, r.nom, "repeater", "relais de l'association", None, True)
    for c in (ContactMeshCore.objects.filter(environment=environment, type_contact__in=list(TYPES_CONTACT))
              .exclude(location__isnull=True).only("pubkey_hex", "location", "nom", "type_contact", "dernier_advert")):
        if c.dernier_advert and c.dernier_advert < limite:
            continue
        ajouter(c.pubkey_hex, c.location.x, c.location.y, c.nom, TYPES_CONTACT[c.type_contact], "entendu par nos passerelles",
                c.dernier_advert, True)
    return {"type": "FeatureCollection", "features": list(vus.values()),
            "attribution": "Cartographie CoreScope (meshstats) et passerelles Assista-Crise"}


def couvertures_publiques(environment):
    from .models import CouvertureRadioSite, StatutCouvertureRadio

    return CouvertureRadioSite.objects.filter(environment=environment, publique=True,
                                              statut=StatutCouvertureRadio.TERMINEE).order_by("nom")


def couverture_en_dict(c):
    return {"id": str(c.id), "nom": c.nom, "calibre": c.calibre, "preset": c.preset,
            "surface_estimee_km2": c.surface_estimee_km2, "date_calcul": c.date_calcul}


def sante_reseau(environment, maintenant=None):
    """Les séries agrégées des dernières 24 heures, sans rien qui identifie une passerelle."""
    from . import tableau_meshcore
    from .models import CompagnonMeshtastic, CompteurPaquetsMeshtastic, MesureTelemetrieMeshtastic

    maintenant = maintenant or timezone.now()
    debut = maintenant - datetime.timedelta(hours=24)
    pas = datetime.timedelta(minutes=30)

    passerelles = {c.id: c.node_num for c in CompagnonMeshtastic.objects.filter(environment=environment).only("id", "node_num")}
    seaux = {"occupation_canal": {}, "temps_antenne_tx": {}}
    actives = set()
    for m in (MesureTelemetrieMeshtastic.objects.filter(compagnon_id__in=list(passerelles), horodatage__gte=debut)
              .values("compagnon_id", "node_num", "horodatage", "occupation_canal", "temps_antenne_tx")):
        if m["node_num"] != passerelles.get(m["compagnon_id"]):
            continue                                   # la passerelle elle-même, pas ses voisins
        actives.add(m["compagnon_id"])
        seau = debut + ((m["horodatage"] - debut) // pas) * pas
        for champ in seaux:
            if m[champ] is not None:
                seaux[champ].setdefault(seau, {}).setdefault(m["compagnon_id"], []).append(m[champ])

    def mediane(serie):
        # Moyenne par passerelle sur le pas, puis médiane entre passerelles.
        return [{"t": t.isoformat(), "v": round(statistics.median(sum(v) / len(v) for v in par.values()), 1)}
                for t, par in sorted(serie.items())]

    par_heure, par_type = {}, {}
    for c in (CompteurPaquetsMeshtastic.objects.filter(compagnon_id__in=list(passerelles), heure__gte=debut)
              .values("heure", "type_paquet", "nombre")):
        par_heure[c["heure"]] = par_heure.get(c["heure"], 0) + c["nombre"]
        par_type[c["type_paquet"]] = par_type.get(c["type_paquet"], 0) + c["nombre"]

    meshcore = tableau_meshcore.construire(environment, "24h", maintenant=maintenant)
    occupation = mediane(seaux["occupation_canal"])
    return {
        "calcule_le": maintenant.isoformat(),
        "meshtastic": {
            # Jamais le nombre exact : « aucune », « une » ou « plusieurs ».
            "passerelles": "aucune" if not actives else ("une" if len(actives) == 1 else "plusieurs"),
            "occupation_canal": occupation,
            "occupation_actuelle": occupation[-1]["v"] if occupation else None,
            "temps_antenne_tx": mediane(seaux["temps_antenne_tx"]),
            "paquets_par_heure": [{"t": h.isoformat(), "v": n} for h, n in sorted(par_heure.items())],
            "par_type": sorted(({"type": t, "nombre": n} for t, n in par_type.items()), key=lambda x: -x["nombre"]),
        },
        "meshcore": {
            "trames_24h": meshcore["trafic"]["total"],
            "par_type": meshcore["trafic"]["par_type"],
            "courbe": meshcore["trafic"]["courbe"],
            "repeteurs_publics": meshcore["relais_publics"]["repeteurs"],
            "repeteurs_vus_24h": meshcore["relais_publics"]["repeteurs_vus"],
        },
    }


def resume(environment):
    """Une ligne d'état par bouton de l'accueil `/ouvert` : rien que des comptes."""
    from . import propagation
    from .models import CelluleOrage

    maintenant = timezone.now()
    cellules = CelluleOrage.objects.filter(heure_image__gte=maintenant - datetime.timedelta(minutes=20)).count()
    hf = propagation.dernier()
    sante = None
    try:
        sante = sante_reseau(environment, maintenant)["meshtastic"]["occupation_actuelle"]
    except Exception:  # noqa: BLE001 — une ligne d'état ne casse pas l'accueil
        sante = None
    return {
        "cellules_orageuses": cellules,
        "repeteurs": len(radio_publique(environment, maintenant)["features"]),
        "kp": hf["kp"] if hf else None, "g": hf["g"] if hf else None, "g_libelle": hf["g_libelle"] if hf else None,
        "occupation_canal": sante,
        "couvertures": couvertures_publiques(environment).count(),
    }
