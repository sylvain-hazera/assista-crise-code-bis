"""Ce que l'eau atteint, et à partir de quel niveau : les enjeux du plan croisés avec la
simulation d'inondation.

C'est la question qu'une commune pose à un logiciel de cartographie quand elle prépare son plan :
« si le cours d'eau monte de deux mètres, qu'est-ce qui est dans l'eau ? ». La simulation
(`core/inondation.py`) garde déjà, pour chaque niveau d'eau, la zone inondée de la commune, et
pour chaque adresse le niveau qui l'atteint. Il restait à y poser les enjeux :

- les **sites sensibles** retenus au plan et les **lieux d'accueil** des dispositifs, qui ont des
  coordonnées : leur seuil est le plus petit niveau dont la zone inondée les contient ;
- les **personnes vulnérables**, qui n'ont qu'une adresse : elle est rapprochée du relevé des
  adresses de la simulation (aucune adresse ne sort du serveur, voir
  `core/secteurs_vulnerables.py`). Ce croisement-là n'est rendu qu'aux personnes habilitées.

**Ce sont des hypothèses**, et l'écran comme le document le disent : la simulation étend un
niveau d'eau sur le relief, elle ne modélise ni les digues, ni les réseaux, ni la vitesse du
courant. Elle dit par où regarder, pas ce qui arrivera. Un lieu d'accueil « atteint à 1,5 m »
est une raison d'aller voir sur place, pas une interdiction de s'en servir.
"""
from .models import (
    AdresseSimuleeInondation,
    PalierInondationSimule,
    Plan,
    StatutSiteSensible,
    SuiviSiteSensible,
)


def paliers_de(commune_code, environment):
    """Les niveaux d'eau simulés pour la commune, du plus bas au plus haut, avec leur zone."""
    return list(PalierInondationSimule.objects.filter(commune_code=commune_code, environment=environment)
                .exclude(polygone__isnull=True).order_by("niveau_metres"))


def seuil_d_un_point(point, paliers):
    """Le plus petit niveau d'eau dont la zone inondée contient ce point, ou None s'il reste au
    sec jusqu'au plus haut niveau simulé."""
    if point is None:
        return None
    for palier in paliers:
        if palier.polygone is not None and palier.polygone.contains(point):
            return palier.niveau_metres
    return None


def exposes(institution, environment) -> dict:
    """Les sites sensibles retenus et les lieux d'accueil du plan, avec le niveau d'eau qui les
    atteint. Triés du plus exposé au moins exposé ; ce qui n'a pas de coordonnées est dit."""
    from . import zonages_officiels

    commune_code = institution.commune_code or ""
    paliers = paliers_de(commune_code, environment) if commune_code else []
    zonages = zonages_officiels.en_base(commune_code, environment) if commune_code else {}
    enjeux = []

    suivis = (SuiviSiteSensible.objects
              .filter(institution=institution, environment=environment, statut=StatutSiteSensible.RETENU)
              .select_related("site"))
    for suivi in suivis:
        site = suivi.site
        enjeux.append({
            "nature": "Lieu ressource" if site.est_ressource and not site.est_enjeu else "Site sensible",
            "categorie": site.get_categorie_display(), "nom": site.nom,
            "situe": site.location is not None, "seuil_m": seuil_d_un_point(site.location, paliers),
            "zone_officielle": zonages_officiels.zone_d_un_point(site.location, zonages),
            "effectif": site.effectif_estime,
        })

    points = {}
    for plan in Plan.objects.filter(institution=institution, environment=environment, actif=True).prefetch_related("points__type"):
        for point in plan.points.all():
            points[point.id] = point
    for point in points.values():
        enjeux.append({
            "nature": "Lieu d'accueil ou point", "categorie": point.type.libelle if point.type_id else "",
            "nom": point.nom, "situe": point.location is not None,
            "seuil_m": seuil_d_un_point(point.location, paliers),
            "zone_officielle": zonages_officiels.zone_d_un_point(point.location, zonages),
            "effectif": point.capacite_accueil,
        })

    # Du plus exposé au moins exposé ; ce qui reste au sec ensuite ; ce qui n'est pas situé à la fin.
    enjeux.sort(key=lambda e: (not e["situe"], e["seuil_m"] is None, e["seuil_m"] or 0, e["nom"].casefold()))
    return {
        "commune_code": commune_code,
        "simulation_disponible": bool(paliers),
        "niveaux_m": [p.niveau_metres for p in paliers],
        "niveau_max_m": paliers[-1].niveau_metres if paliers else None,
        "enjeux": enjeux,
        # Les zones inondables officielles de l'État, relevées une fois (core/zonages_officiels.py).
        "zonages_officiels": zonages_officiels.etat(commune_code, environment),
        "en_zone_officielle": sum(1 for e in enjeux if e["zone_officielle"]),
        "atteints": sum(1 for e in enjeux if e["seuil_m"] is not None),
        "non_situes": sum(1 for e in enjeux if not e["situe"]),
    }


def seuils_du_registre(personnes, commune_code, environment) -> dict:
    """`{identifiant de fiche: niveau d'eau qui atteint son adresse}` pour les fiches dont
    l'adresse se retrouve dans le relevé de la simulation ; `None` si l'adresse reste au sec.
    Les fiches non retrouvées n'y figurent pas. À ne rendre qu'aux personnes habilitées."""
    from .rattachement_adresses import Releve

    releve = Releve(commune_code, environment)
    seuils = {}
    for personne in personnes:
        adresse = releve.adresse_de(personne)
        # Une adresse sans altitude ni niveau d'eau n'a pas été simulée (relevé simple, ou maison référencée pour
        # une autre crise) : on ne sait rien de l'eau chez elle, et on ne dit pas « au sec ».
        if adresse is not None and (adresse.altitude_metres is not None or adresse.seuil_inondation_metres is not None):
            seuils[personne.id] = adresse.seuil_inondation_metres
    return seuils
