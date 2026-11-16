"""Le salon où l'on parle à une équipe : celui de la crise en cours, sinon celui de tous les jours.

Deux règles posées par Sylvain le 16/11/2026, qui semblaient se contredire :

- « un salon par crise, et les messages hors crise ne suivent pas » ;
- « on doit pouvoir réutiliser des équipes permanentes, prêtes pour la crise future ».

Elles tiennent ensemble dès que c'est le SALON, et non l'équipe, qui est propre à la crise : une
équipe permanente garde son salon de tous les jours (`SalonMatrixEquipe.crise` vide) et en
reçoit un autre pour chaque crise où elle est engagée.

**Qui choisit le salon.** Toujours le serveur, jamais l'écran : l'application mobile et la page
de l'équipe demandent « la messagerie de l'équipe » sans savoir qu'il y a des crises, et elles
doivent pourtant tomber dans le bon salon -- sinon la cellule de crise écrirait à une équipe qui
lit ailleurs. D'où `crise_du_contexte` :

1. la crise nommée par l'appelant (`?crise=`, envoyé par la cellule de crise), si l'équipe y est
   bien engagée et qu'elle est ouverte ;
2. à défaut, la crise ouverte la plus récente à laquelle l'équipe est affectée ;
3. à défaut, aucune : le salon de tous les jours.

À la clôture de la crise, l'équipe retrouve donc d'elle-même son salon habituel ; celui de la
crise reste, comme archive.

**Ce qui n'a pas de variante par crise** : la cellule de crise, qui est déjà une équipe créée
pour la crise (son seul salon EST celui de la crise) ; et le salon d'encadrement, qui suit la
hiérarchie des équipes, pas les crises.
"""
from .models import PointOperationnel, SalonMatrixEquipe, TypeSalonEquipe


def est_equipe_de_crise(equipe) -> bool:
    """Une équipe créée pour porter la cellule d'une crise : elle n'existe que pour cette crise."""
    return PointOperationnel.objects.filter(equipe=equipe, type__code="CELLULE_CRISE").exists()


def crises_ouvertes_de(equipe):
    """Les crises ouvertes où l'équipe est engagée : affectée à la crise, ou à l'un de ses points."""
    from .models import Crisis

    return (Crisis.objects.filter(end_date__isnull=True)
            .filter(pk__in=list(equipe.assigned_crises.values_list("id", flat=True))
                    + list(PointOperationnel.objects.filter(equipe=equipe, crise__isnull=False)
                           .values_list("crise_id", flat=True))))


def crise_du_contexte(equipe, crise_id=None):
    """La crise dans laquelle on parle à cette équipe en ce moment, ou None (voir le module)."""
    if est_equipe_de_crise(equipe):
        return None
    ouvertes = crises_ouvertes_de(equipe)
    if crise_id:
        try:
            nommee = ouvertes.filter(pk=crise_id).first()
        except (ValueError, TypeError, Exception):  # identifiant mal formé : on l'ignore
            nommee = None
        if nommee is not None:
            return nommee
    return ouvertes.order_by("-start_date").first()


def salon_intervenants(equipe, crise, environment, creer=True):
    """Le salon INTERVENANTS de l'équipe pour `crise` (None = celui de tous les jours).

    Créé à la demande : un salon de crise naît à la première discussion, pas à l'affectation --
    même règle que le reste (« un salon ne naît que s'il y a quelqu'un à y mettre »). `room_id`
    reste vide jusqu'au passage du pont Matrix."""
    filtre = {"equipe": equipe, "type": TypeSalonEquipe.INTERVENANTS, "crise": crise}
    if not creer:
        return SalonMatrixEquipe.objects.filter(**filtre).first()
    salon, _cree = SalonMatrixEquipe.objects.get_or_create(**filtre, defaults={"environment": environment})
    return salon


def salon_du_contexte(request, equipe, creer=True):
    """Le salon où cette requête parle à l'équipe. `?crise=` (ou `crise` dans le corps) nomme la
    crise ; sinon c'est la crise ouverte de l'équipe, sinon le salon de tous les jours."""
    from .permissions import get_active_environment

    crise_id = request.query_params.get("crise") or (request.data.get("crise") if hasattr(request.data, "get") else None)
    return salon_intervenants(equipe, crise_du_contexte(equipe, crise_id), get_active_environment(request), creer=creer)
