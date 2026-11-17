"""La zone d'une crise, et les chemins par lesquels elle s'agrandit (17/11/2026).

Trois géométries composent la zone :

- `Crisis.zone` : le polygone dessiné à la déclaration (la zone initiale) ;
- `Crisis.zone_secteurs` : l'union des contours des communes et départements ajoutés ;
- `ZoneAjouteeCrise` : les zones dessinées EN PLUS par les institutions impliquées. Elles ne
  modifient pas la zone initiale, peuvent ne pas la toucher, et restent attachées à qui les a
  dessinées — la même règle de provenance que pour une commune ajoutée
  (`ContributionZoneCommune`).

Une commune entre donc dans une crise par deux chemins : **tout son territoire** (son contour
officiel rejoint `zone_secteurs`), ou **une zone qu'elle dessine**. Dans le second cas son code
figure quand même dans `zone_communes` — c'est lui qui porte les droits et l'accord du maire —
mais marqué `partielle`, et son contour entier ne fait pas partie de la zone.

Tout calcul « ce point est-il dans la zone ? » passe par ici, pour que les zones ajoutées
comptent partout où la zone compte.
"""
from django.contrib.gis.geos import MultiPolygon


def geometries(crise) -> list:
    """Toutes les géométries non vides qui composent la zone de la crise."""
    if crise is None:
        return []
    trouvees = [g for g in (crise.zone, crise.zone_secteurs) if g is not None and not g.empty]
    trouvees.extend(
        z.geometrie for z in crise.zones_ajoutees.all()
        if z.geometrie is not None and not z.geometrie.empty
    )
    return trouvees


def dessinee(crise):
    """L'emprise composée (secteurs + zones ajoutées) en un MultiPolygon, ou None.

    Sans la zone initiale : c'est le périmètre que les usages existants lisaient dans
    `zone_secteurs` seul, étendu aux zones ajoutées."""
    if crise is None:
        return None
    morceaux = []
    if crise.zone_secteurs is not None and not crise.zone_secteurs.empty:
        morceaux.append(crise.zone_secteurs)
    morceaux.extend(
        z.geometrie for z in crise.zones_ajoutees.all()
        if z.geometrie is not None and not z.geometrie.empty
    )
    if not morceaux:
        return None
    union = morceaux[0]
    for morceau in morceaux[1:]:
        union = union.union(morceau)
    if union.geom_type == "Polygon":
        union = MultiPolygon(union, srid=4326)
    return union


def contient(crise, point) -> bool:
    """Le point est-il dans l'une des géométries de la zone ?"""
    return any(g.contains(point) for g in geometries(crise))


def communes_partielles(crise) -> list:
    return sorted(
        crise.contributions_zone_communes.filter(partielle=True)
        .values_list("commune_code", flat=True)
    )


def peut_contribuer(request, crise) -> bool:
    """Qui peut dessiner une zone en plus : l'administrateur, l'auteur de la crise, et tout
    membre d'une institution impliquée sur elle. Pas « tout acteur institutionnel » : la zone
    d'une crise ouvre des droits, on n'y dessine pas depuis l'extérieur."""
    from .models import ContactInstitution, ImplicationInstitution, UserRole
    from .permissions import effective_role_or_none

    user = request.user
    if not (user and user.is_authenticated):
        return False
    if effective_role_or_none(request) == UserRole.ADMINISTRATOR or crise.author_id == user.id:
        return True
    return ImplicationInstitution.objects.filter(
        crise=crise, actif=True, institution_id__in=institutions_de(user),
    ).exists()


def institutions_de(user) -> set:
    from .models import ContactInstitution

    ids = set(
        ContactInstitution.objects.filter(utilisateur=user, actif=True)
        .values_list("institution_id", flat=True)
    )
    if getattr(user, "institution_id", None):
        ids.add(user.institution_id)
    return ids


def institution_contributrice(request, crise):
    """L'institution au nom de laquelle l'appelant dessine : la sienne si elle est impliquée
    sur la crise, sinon None (administrateur, auteur sans institution)."""
    from .models import ImplicationInstitution

    siennes = institutions_de(request.user)
    implication = (
        ImplicationInstitution.objects.filter(crise=crise, actif=True, institution_id__in=siennes)
        .select_related("institution").order_by("date_creation").first()
    )
    if implication is not None:
        return implication.institution
    return getattr(request.user, "institution", None)


def marquer_commune(crise, commune_code, institution, environment, partielle) -> None:
    """Inscrit une commune dans la zone de la crise si elle n'y est pas, avec sa provenance.

    Une commune déjà présente n'est pas touchée : le premier contributeur fait foi, et une
    commune entrée en entier ne redevient pas partielle parce qu'on y dessine une zone."""
    from .models import ContributionZoneCommune

    if not commune_code:
        return
    if commune_code in (crise.zone_communes or []):
        ContributionZoneCommune.objects.get_or_create(
            crise=crise, commune_code=commune_code,
            defaults={"institution": institution, "environment": environment},
        )
        return
    crise.zone_communes = [*(crise.zone_communes or []), commune_code]
    crise.save(update_fields=["zone_communes"])
    ContributionZoneCommune.objects.update_or_create(
        crise=crise, commune_code=commune_code,
        defaults={"institution": institution, "environment": environment, "partielle": partielle},
    )
