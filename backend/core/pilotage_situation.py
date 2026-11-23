"""Tableaux de situation du pilotage (23/11/2026) : ce qui existait ailleurs et n'était pas
visible dans le poste de pilotage, en cartes, pour une crise.

- **Veille de la zone** : vigilance météo des départements, tronçons de crue en vigilance,
  stations de hauteur d'eau, foyers d'incendie et foudre récents dans la zone de la crise.
- **Accueil et hébergement** : centres (capacité, présents), personnes mises en sécurité,
  familles à reloger.
- **Dégâts** : biens évalués par gravité, part évaluée, par commune.
- **Moyens** : demandes non couvertes face aux offres disponibles, renforts demandés.
- **Radio** : équipes engagées, canal radio configuré, dernier message reçu par radio.

Rien n'est saisi ici : chaque bloc lit des tables déjà remplies. Un bloc en échec n'empêche
pas les autres de s'afficher (il rend `erreur`). Aucune donnée nominative.
"""
import datetime
import logging

from django.contrib.gis.geos import Polygon
from django.db.models import Count, Max, Q, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


def emprise(crise):
    """La zone de la crise, ou un carré autour de son point (son rayon, en km)."""
    if crise.zone is not None:
        return crise.zone
    p = crise.location
    d = max(1, crise.radius or 10) / 111.0
    return Polygon.from_bbox((p.x - d * 1.4, p.y - d, p.x + d * 1.4, p.y + d))


def departements(crise):
    codes = [str(c) for c in (crise.zone_departements or []) if c]
    if not codes:
        from .geo_lookup import commune_code_from_point
        commune = commune_code_from_point(crise.location)
        if commune:
            codes = [commune[:3] if commune.startswith("97") else commune[:2]]
    return codes


def veille(crise, maintenant):
    from .models import FoyerActif, ImpactFoudre, StationHydrometrique, TronconVigilanceCrues, VigilanceMeteo

    zone = emprise(crise)
    couleurs = {1: "vert", 2: "jaune", 3: "orange", 4: "rouge"}
    vigilance = [{"departement": v.departement_code, "aujourdhui": couleurs.get(v.couleur_j, "?"),
                  "demain": couleurs.get(v.couleur_j1, "?")}
                 for v in VigilanceMeteo.objects.filter(departement_code__in=departements(crise))]
    crues = [{"nom": t.nom or t.code, "niveau": couleurs.get(t.niveau, str(t.niveau))}
             for t in TronconVigilanceCrues.objects.filter(niveau__gte=2, geometrie__intersects=zone).order_by("-niveau")[:10]]
    stations = []
    for s in StationHydrometrique.objects.filter(location__within=zone).exclude(hauteur_m=None)[:200]:
        historique = [h for h in (s.historique or []) if isinstance(h, (list, tuple)) and len(h) >= 2]
        evolution = None
        if len(historique) >= 2:
            try:
                evolution = round(float(historique[-1][1]) - float(historique[0][1]), 2)
            except (TypeError, ValueError):
                evolution = None
        stations.append({"nom": s.nom, "cours_eau": s.cours_eau, "hauteur_m": s.hauteur_m,
                         "le": s.hauteur_le.isoformat() if s.hauteur_le else None, "evolution_m": evolution})
    stations.sort(key=lambda s: -(s["evolution_m"] or 0))
    return {
        "vigilance_meteo": vigilance,
        "crues": crues,
        "stations": stations[:6],
        "foyers_24h": FoyerActif.objects.filter(location__within=zone, source_fixe=False,
                                                date__gte=maintenant - datetime.timedelta(hours=24)).count(),
        "foudre_1h": ImpactFoudre.objects.filter(location__within=zone, instant__gte=maintenant - datetime.timedelta(hours=1)).count(),
    }


def accueil(crise, environment):
    from .models import DeclarationSecurite, DossierRelogement, PointOperationnel, RegistrePresence

    centres = []
    for p in PointOperationnel.objects.filter(crise=crise, environment=environment, type__code="HEBERGEMENT", actif=True,
                                              date_fermeture__isnull=True):
        presents = RegistrePresence.objects.filter(point=p, date_depart__isnull=True).aggregate(n=Sum("nombre"))["n"] or 0
        centres.append({"nom": p.nom, "capacite": p.capacite_accueil, "presents": presents})
    declarations = DeclarationSecurite.objects.filter(crise=crise, environment=environment)
    personnes = declarations.aggregate(a=Sum("nombre_adultes"), e=Sum("nombre_enfants"))
    relogement = dict(DossierRelogement.objects.filter(crise=crise, environment=environment)
                      .values_list("statut").annotate(n=Count("id")).values_list("statut", "n"))
    return {
        "centres": centres,
        "places": sum(c["capacite"] or 0 for c in centres),
        "presents": sum(c["presents"] for c in centres),
        "mises_en_securite": {"declarations": declarations.count(),
                              "personnes": (personnes["a"] or 0) + (personnes["e"] or 0),
                              "cherchent_un_centre": declarations.filter(situation="BESOIN_CENTRE").count()},
        "relogement": {"en_recherche": relogement.get("EN_RECHERCHE", 0), "heberges": relogement.get("HEBERGE", 0),
                       "reloges": relogement.get("RELOGEE", 0) + relogement.get("RETOUR_DOMICILE", 0)},
    }


def degats(crise, environment):
    from .models import AdresseBAN, Habitation

    biens = Habitation.objects.filter(crise=crise, environment=environment, fusionne_dans__isnull=True)
    par_statut = dict(biens.values_list("statut_evaluation").annotate(n=Count("id")).values_list("statut_evaluation", "n"))
    evalues = sum(n for s, n in par_statut.items() if s and s != "NON_EVALUEE")
    adresses = AdresseBAN.objects.filter(retiree_le__isnull=True, location__within=emprise(crise)).count()
    communes = list(biens.exclude(commune_code=None).values("commune_code")
                    .annotate(biens=Count("id"), touches=Count("id", filter=Q(statut_evaluation__in=["DEGATS_FAIBLES", "DEGATS_FORTS", "DETRUITE"])))
                    .order_by("-touches")[:8])
    return {
        "par_statut": {k: par_statut.get(k, 0) for k in ("PAS_DE_DEGATS", "DEGATS_FAIBLES", "DEGATS_FORTS", "DETRUITE", "NON_EVALUEE")},
        "evalues": evalues,
        "adresses_zone": adresses,
        "part_evaluee": round(100 * evalues / adresses, 1) if adresses else None,
        "communes": communes,
    }


def moyens(crise, environment, maintenant):
    from .models import MessageTerrain, Offer, Request

    demandes = dict(Request.objects.filter(crisis=crise, environment=environment, status__in=["NON_TRAITEE", "EN_COURS"])
                    .values_list("request_type__type").annotate(n=Count("id")).values_list("request_type__type", "n"))
    offres = dict(Offer.objects.filter(crisis=crise, environment=environment, status="DISPONIBLE")
                  .values_list("offer_type__type").annotate(n=Count("id")).values_list("offer_type__type", "n"))
    renforts = MessageTerrain.objects.filter(crise=crise, environment=environment, type="RENFORT",
                                             emis_le__gte=maintenant - datetime.timedelta(hours=24))
    return {
        "demandes_non_couvertes": sorted(({"type": t or "Autre", "nombre": n} for t, n in demandes.items()), key=lambda x: -x["nombre"]),
        "offres_disponibles": sorted(({"type": t or "Autre", "nombre": n} for t, n in offres.items()), key=lambda x: -x["nombre"]),
        "renforts_24h": {"demandes": renforts.count(), "personnes": renforts.aggregate(n=Sum("nombre"))["n"] or 0},
    }


def radio(crise, environment):
    from .models import CanalMeshCore, CanalMeshtastic, MessageTerrain, Team

    equipes = list(Team.objects.filter(assigned_crises=crise, actif=True, environment=environment).order_by("name"))
    ids = [t.id for t in equipes]
    meshtastic = set(CanalMeshtastic.objects.filter(equipe_id__in=ids).values_list("equipe_id", flat=True))
    meshcore = set(CanalMeshCore.objects.filter(equipe_id__in=ids).values_list("equipe_id", flat=True))
    derniers = dict(MessageTerrain.objects.filter(equipe_id__in=ids).exclude(canal="DONNEES")
                    .values_list("equipe_id").annotate(d=Max("emis_le")).values_list("equipe_id", "d"))
    return {"equipes": [{
        "nom": t.name, "meshtastic": t.id in meshtastic, "meshcore": t.id in meshcore,
        "dernier_message_radio": derniers[t.id].isoformat() if t.id in derniers else None,
    } for t in equipes]}


BLOCS = ("veille", "accueil", "degats", "moyens", "radio")


def situation(crise, environment, maintenant=None):
    maintenant = maintenant or timezone.now()
    appels = {
        "veille": lambda: veille(crise, maintenant),
        "accueil": lambda: accueil(crise, environment),
        "degats": lambda: degats(crise, environment),
        "moyens": lambda: moyens(crise, environment, maintenant),
        "radio": lambda: radio(crise, environment),
    }
    resultat = {"crise": str(crise.id), "debut": crise.start_date.isoformat() if crise.start_date else None,
                "calcule_le": maintenant.isoformat()}
    for nom in BLOCS:
        try:
            resultat[nom] = appels[nom]()
        except Exception:
            logger.exception("Bloc de situation « %s » en échec pour la crise %s.", nom, crise.id)
            resultat[nom] = {"erreur": "Indisponible pour le moment."}
    return resultat
