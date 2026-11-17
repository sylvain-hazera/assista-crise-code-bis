"""« Je pars », « je rentre » pour le personnel municipal et les membres d'association.

Demande du 17/11/2026 : relever le temps engagé « en utilisant les déclarations de la
personne ». Ces déclarations existaient pour une ressource proposée par une offre d'aide
(`EngagementRessource`) ; un agent de la mairie ou un bénévole d'association, qui intervient
parce qu'il est membre d'une équipe, n'avait aucun bouton.

Deux gestes, et rien d'autre à saisir. La personne part sur une crise — avec son équipe si elle
en a une — puis rentre. Elle ne peut être partie qu'une fois à la fois. L'heure est celle du
serveur au moment du geste : on ne déclare pas après coup une heure qu'on choisit, c'est ce qui
donne sa valeur au relevé.
"""
from django.db.models import Q
from django.utils import timezone

from .models import (
    Crisis, EngagementPersonnel, ImplicationInstitution, Team,
)


class ErreurEngagement(ValueError):
    """Geste refusé ; le message est fait pour être lu."""


def equipes_de(utilisateur):
    return Team.objects.filter(Q(members=utilisateur) | Q(membres_encadrement=utilisateur)).distinct()


def institutions_de(utilisateur) -> set:
    """Les institutions au nom desquelles la personne peut partir : la sienne, et celles de
    ses équipes."""
    ids = set(equipes_de(utilisateur).exclude(institution__isnull=True).values_list("institution_id", flat=True))
    if getattr(utilisateur, "institution_id", None):
        ids.add(utilisateur.institution_id)
    return ids


def crises_ouvertes_pour(utilisateur, environment):
    """Les crises en cours où l'une de ses institutions est engagée : on ne part pas sur une
    crise qui ne concerne ni sa mairie ni son association."""
    institutions = institutions_de(utilisateur)
    if not institutions:
        return Crisis.objects.none()
    crises = ImplicationInstitution.objects.filter(
        institution_id__in=institutions, actif=True).values_list("crise_id", flat=True)
    return Crisis.objects.filter(id__in=crises, end_date__isnull=True, environment=environment).order_by("-start_date")


def en_cours(utilisateur, environment):
    return EngagementPersonnel.objects.filter(
        utilisateur=utilisateur, environment=environment, rentre_le__isnull=True,
    ).select_related("crise", "equipe").first()


def partir(utilisateur, environment, crise, equipe=None) -> EngagementPersonnel:
    """« Je pars ». Rejouable : déjà parti sur cette crise, on rend l'engagement en cours."""
    ouvert = en_cours(utilisateur, environment)
    if ouvert is not None:
        if ouvert.crise_id == crise.id:
            return ouvert
        raise ErreurEngagement(
            f"Vous êtes déjà parti sur « {ouvert.crise.name} » : déclarez d'abord votre retour.")
    if crise.end_date is not None:
        raise ErreurEngagement("Cette crise est close.")
    if not crises_ouvertes_pour(utilisateur, environment).filter(id=crise.id).exists():
        raise ErreurEngagement("Ni votre institution ni vos équipes ne sont engagées sur cette crise.")
    if equipe is not None and not equipes_de(utilisateur).filter(id=equipe.id).exists():
        raise ErreurEngagement("Vous n'êtes pas membre de cette équipe.")
    institution = equipe.institution if equipe is not None and equipe.institution_id else getattr(utilisateur, "institution", None)
    return EngagementPersonnel.objects.create(
        utilisateur=utilisateur, environment=environment, crise=crise, equipe=equipe,
        institution=institution, parti_le=timezone.now(),
    )


def rentrer(utilisateur, environment):
    """« Je rentre ». Sans départ en cours, il n'y a rien à clore."""
    ouvert = en_cours(utilisateur, environment)
    if ouvert is None:
        raise ErreurEngagement("Vous n'êtes pas déclaré parti.")
    ouvert.rentre_le = timezone.now()
    ouvert.save(update_fields=["rentre_le"])
    return ouvert


def de_l_institution(crise, institution, environment):
    """Les engagements que cette institution relit : ceux partis en son nom ou avec l'une de
    ses équipes."""
    return (
        EngagementPersonnel.objects.filter(crise=crise, environment=environment)
        .filter(Q(institution=institution) | Q(equipe__institution=institution))
        .select_related("utilisateur", "equipe").order_by("parti_le").distinct()
    )
