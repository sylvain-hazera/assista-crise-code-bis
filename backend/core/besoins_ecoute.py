"""Thèmes "à l'écoute" pour les formulaires publics (Request/Offer/Information) -- une
institution déclarée ACTEUR opérationnel sur une crise (voir ImplicationInstitution) doit
désormais déclarer au moins un Besoin qu'elle écoute (voir ImplicationInstitutionViewSet
.perform_create/perform_update). Ce module calcule, pour une crise et une commune données,
l'union des Besoins effectivement à l'écoute -- consommé par TypesALecouteView (AllowAny) pour
filtrer le sélecteur de type des formulaires publics avant tout dépôt."""
from .models import Besoin, Commune, ImplicationInstitution, StatutImplication, TypeImplication


def _commune_dans_zone_crise(crise, commune_code: str) -> bool:
    """Détermine si `commune_code` fait partie de la zone de LA CRISE -- une institution
    déclarée ACTEUR sur une crise écoute sur toute la zone de CETTE crise (celle définie via
    "Institutions impliquées" -- communes/départements ajoutés, zone dessinée, ou simplement le
    rayon par défaut autour de son point de départ), pas seulement sur son propre secteur
    institutionnel. Correctif : une mairie ACTEUR sur une crise intercommunale (ex: "Incendie de
    Saumos" couvrant Le Porge ET Saumos) ne doit pas être ignorée pour les communes voisines de
    la même crise sous prétexte que ce n'est pas sa commune de rattachement -- repéré en direct
    par l'utilisateur (25/09), une mairie ACTEUR avait bien déclaré des thèmes mais aucun
    n'apparaissait à l'écoute pour la commune homonyme de la crise elle-même."""
    if commune_code in (crise.zone_communes or []):
        return True

    commune = Commune.objects.filter(code=commune_code).first()
    if commune and commune.departement_code and commune.departement_code in (crise.zone_departements or []):
        return True

    if commune and commune.centre_latitude is not None and commune.centre_longitude is not None:
        from django.contrib.gis.geos import Point
        point = Point(commune.centre_longitude, commune.centre_latitude, srid=4326)
        if crise.zone_secteurs is not None and not crise.zone_secteurs.empty and crise.zone_secteurs.contains(point):
            return True
        if crise.zone is not None and not crise.zone.empty and crise.zone.contains(point):
            return True

    # Repli : aucune zone composée (communes/départements/dessin) -- crise déclarée seulement
    # avec un point + un rayon (voir Crisis.location/radius), cas le plus simple. Se contente de
    # comparer la commune résolue du point de la crise, sans tenir compte du rayon lui-même
    # (pas de commune référentiel "à N km" prêt à l'emploi) -- suffisant pour le cas courant
    # d'une crise à l'échelle d'une seule commune.
    from .geo_lookup import commune_code_from_point
    return commune_code_from_point(crise.location) == commune_code


def besoins_a_lecoute(crise, commune_code: str | None = None):
    """Besoins qu'au moins une institution ACTEUR (validée, active) écoute pour `crise` --
    IMPLIQUE n'y figure jamais (une institution seulement concernée par la crise ne fournit pas
    d'aide, voir ImplicationInstitution.__doc__). `commune_code=None` : AUCUNE restriction
    géographique -- décision explicite de l'utilisateur (25/09) pour les propositions d'aide
    (axe "offer") : un offreur peut se trouver n'importe où (un logement à 50km, un trajet
    depuis Bordeaux...), contrairement à un demandeur ou un signalement qui, eux, sont
    naturellement dans/près de la zone concernée. Fourni : filtre en plus sur la zone de la
    crise (voir _commune_dans_zone_crise)."""
    if commune_code is not None and not _commune_dans_zone_crise(crise, commune_code):
        return Besoin.objects.none()

    implications = ImplicationInstitution.objects.filter(
        crise=crise, actif=True, statut=StatutImplication.VALIDEE,
        type_implication=TypeImplication.ACTEUR,
    ).prefetch_related("themes")

    besoin_ids = set()
    for implication in implications:
        besoin_ids.update(implication.themes.values_list("id", flat=True))

    # Écouter une FAMILLE, c'est écouter ce qu'elle contient (26/10/2026). Les thèmes proposés à
    # une institution sont les besoins racine (« Accueil & alimentation », « Secours & soins »,
    # « Pompage & citernes »...), mais les correspondances thème -> type de formulaire ont été
    # posées sur les SOUS-besoins (« Hébergement », « Nourriture et eau », « Pompage »...). Une
    # mairie qui cochait les familles les plus évidentes n'avait donc AUCUN type à l'écoute, et
    # le public ne pouvait plus rien déposer du tout : ni demande, ni offre, ni signalement.
    # Un seul niveau, comme la hiérarchie elle-même (Besoin.parent, cf. Competence.parent).
    # Sens unique : écouter un sous-besoin n'implique pas d'écouter toute sa famille, un choix
    # précis restant un choix précis.
    besoin_ids.update(
        Besoin.objects.filter(parent_id__in=besoin_ids).values_list("id", flat=True)
    )

    return Besoin.objects.filter(id__in=besoin_ids)
