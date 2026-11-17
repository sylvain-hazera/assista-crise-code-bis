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
    AffectationLogementIntervenant, Crisis, EngagementPersonnel, ImplicationInstitution,
    LieuDeDepart, Team,
)

#: Au-delà, ce n'est plus une journée mais un oubli : la personne coupe en plusieurs lignes.
DUREE_MAX_H = 24


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


def hebergement_de(utilisateur, crise) -> str:
    """Le logement de la personne sur cette crise, si elle y est « en déplacement sur site » :
    le plus récent fait foi. Vide si elle n'est pas hébergée."""
    affectation = (
        AffectationLogementIntervenant.objects.filter(intervenant=utilisateur, crise=crise)
        .select_related("point", "offre").order_by("-date_creation").first()
    )
    if affectation is None:
        return ""
    if affectation.point_id:
        return affectation.point.nom or "Centre d'hébergement"
    return (affectation.offre.title if affectation.offre_id else "") or "Logement mis à disposition"


def _lieu(valeur, defaut):
    return valeur if valeur in LieuDeDepart.values else defaut


def partir(utilisateur, environment, crise, equipe=None, depart_de=None) -> EngagementPersonnel:
    """« Je pars ». Rejouable : déjà parti sur cette crise, on rend l'engagement en cours.

    `depart_de` : domicile ou hébergement. Sans précision, quelqu'un qui a un logement sur
    cette crise part de son logement."""
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
    logement = hebergement_de(utilisateur, crise)
    depart_de = _lieu(depart_de, LieuDeDepart.HEBERGEMENT if logement else LieuDeDepart.DOMICILE)
    return EngagementPersonnel.objects.create(
        utilisateur=utilisateur, environment=environment, crise=crise, equipe=equipe,
        institution=institution, parti_le=timezone.now(), depart_de=depart_de,
        hebergement=logement if depart_de == LieuDeDepart.HEBERGEMENT else "",
    )


def rentrer(utilisateur, environment, retour_a=None):
    """« Je rentre ». Sans départ en cours, il n'y a rien à clore. On rentre par défaut là
    d'où l'on est parti."""
    ouvert = en_cours(utilisateur, environment)
    if ouvert is None:
        raise ErreurEngagement("Vous n'êtes pas déclaré parti.")
    ouvert.rentre_le = timezone.now()
    ouvert.retour_a = _lieu(retour_a, ouvert.depart_de)
    if ouvert.retour_a == LieuDeDepart.HEBERGEMENT and not ouvert.hebergement:
        ouvert.hebergement = hebergement_de(utilisateur, ouvert.crise)
    ouvert.save(update_fields=["rentre_le", "retour_a", "hebergement"])
    return ouvert


# ── Compléter ses oublis à la main ─────────────────────────────────────────────────────────

def crises_declarables(utilisateur, environment):
    """Les crises sur lesquelles la personne peut compléter son relevé : celles où l'une de
    ses institutions a été engagée, closes comprises — on complète souvent après coup."""
    institutions = institutions_de(utilisateur)
    if not institutions:
        return Crisis.objects.none()
    crises = ImplicationInstitution.objects.filter(institution_id__in=institutions).values_list("crise_id", flat=True)
    return Crisis.objects.filter(id__in=crises, environment=environment).order_by("-start_date")


def _verifier(utilisateur, environment, parti_le, rentre_le, sauf=None):
    maintenant = timezone.now()
    if parti_le > maintenant or (rentre_le is not None and rentre_le > maintenant):
        raise ErreurEngagement("On ne déclare pas une heure à venir.")
    if rentre_le is not None:
        if rentre_le <= parti_le:
            raise ErreurEngagement("Le retour doit suivre le départ.")
        if (rentre_le - parti_le).total_seconds() > DUREE_MAX_H * 3600:
            raise ErreurEngagement(
                f"Plus de {DUREE_MAX_H} heures d'affilée : déclarez une ligne par sortie, du départ au retour.")
    autres = EngagementPersonnel.objects.filter(utilisateur=utilisateur, environment=environment)
    if sauf is not None:
        autres = autres.exclude(id=sauf.id)
    fin = rentre_le or maintenant
    for autre in autres:
        if autre.parti_le < fin and (autre.rentre_le or maintenant) > parti_le:
            raise ErreurEngagement(
                "Ces heures recouvrent une autre ligne de votre relevé "
                f"(départ du {timezone.localtime(autre.parti_le).strftime('%d/%m à %H:%M')}).")


def completer(utilisateur, environment, *, crise, parti_le, rentre_le, equipe=None,
              depart_de=None, retour_a=None) -> EngagementPersonnel:
    """Ajoute à la main une sortie oubliée. Elle doit être complète (un départ ET un retour) :
    un départ en cours se déclare par le bouton, pas après coup."""
    if rentre_le is None:
        raise ErreurEngagement("Une ligne ajoutée à la main porte un départ et un retour.")
    if not crises_declarables(utilisateur, environment).filter(id=crise.id).exists():
        raise ErreurEngagement("Ni votre institution ni vos équipes n'ont été engagées sur cette crise.")
    if equipe is not None and not equipes_de(utilisateur).filter(id=equipe.id).exists():
        raise ErreurEngagement("Vous n'êtes pas membre de cette équipe.")
    _verifier(utilisateur, environment, parti_le, rentre_le)
    depart_de = _lieu(depart_de, LieuDeDepart.DOMICILE)
    retour_a = _lieu(retour_a, depart_de)
    institution = equipe.institution if equipe is not None and equipe.institution_id else getattr(utilisateur, "institution", None)
    return EngagementPersonnel.objects.create(
        utilisateur=utilisateur, environment=environment, crise=crise, equipe=equipe, institution=institution,
        parti_le=parti_le, rentre_le=rentre_le, depart_de=depart_de, retour_a=retour_a,
        hebergement=hebergement_de(utilisateur, crise) if LieuDeDepart.HEBERGEMENT in (depart_de, retour_a) else "",
        saisie_manuelle=True, modifie_le=timezone.now(),
    )


def corriger(engagement, *, parti_le=None, rentre_le=None, depart_de=None, retour_a=None) -> EngagementPersonnel:
    """Corrige une de SES lignes — typiquement le retour oublié. La ligne est marquée
    « complétée à la main » : le relevé ne fait pas passer une correction pour une déclaration
    faite sur le moment. Une ligne validée par l'encadrement ne se corrige plus."""
    if engagement.valide_le is not None:
        raise ErreurEngagement(
            "Cette ligne a été validée par votre encadrement : demandez-lui de lever sa validation.")
    parti = parti_le or engagement.parti_le
    rentre = rentre_le if rentre_le is not None else engagement.rentre_le
    _verifier(engagement.utilisateur, engagement.environment, parti, rentre, sauf=engagement)
    engagement.parti_le, engagement.rentre_le = parti, rentre
    engagement.depart_de = _lieu(depart_de, engagement.depart_de)
    engagement.retour_a = _lieu(retour_a, engagement.retour_a or engagement.depart_de) if rentre is not None else ""
    engagement.saisie_manuelle = True
    engagement.modifie_le = timezone.now()
    # La remarque a été entendue : la ligne retourne à la relecture.
    engagement.remarque_chef = ""
    engagement.save()
    return engagement


# ── La relecture par l'encadrement ─────────────────────────────────────────────────────────
# Décision du 17/11/2026 : seule la personne complète son relevé ; le chef d'équipe en a la
# vision et valide. Il ne corrige donc rien : il valide, ou renvoie la ligne avec une remarque.

def equipes_encadrees(utilisateur):
    """Les équipes dont la personne relit les relevés : elle en est chef, régulatrice, ou
    membre de l'encadrement."""
    return Team.objects.filter(
        Q(leader=utilisateur) | Q(regulateur=utilisateur) | Q(membres_encadrement=utilisateur)).distinct()


def a_relire_par(utilisateur, environment):
    """Les lignes que cette personne peut relire : celles de ses équipes — pas les siennes."""
    return (
        EngagementPersonnel.objects.filter(environment=environment, equipe__in=equipes_encadrees(utilisateur))
        .exclude(utilisateur=utilisateur)
        .select_related("utilisateur", "crise", "equipe", "valide_par")
    )


def _relisible(engagement, relecteur, environment):
    if engagement.utilisateur_id == relecteur.id:
        raise ErreurEngagement("On ne valide pas son propre relevé : c'est à un autre encadrant de le faire.")
    if not a_relire_par(relecteur, environment).filter(id=engagement.id).exists():
        raise ErreurEngagement("Cette ligne n'est pas celle d'une équipe que vous encadrez.")


def valider(engagement, relecteur, environment) -> EngagementPersonnel:
    _relisible(engagement, relecteur, environment)
    if engagement.rentre_le is None:
        raise ErreurEngagement("Cette sortie n'est pas terminée : il n'y a pas encore de durée à valider.")
    engagement.valide_par, engagement.valide_le, engagement.remarque_chef = relecteur, timezone.now(), ""
    engagement.save(update_fields=["valide_par", "valide_le", "remarque_chef"])
    return engagement


def renvoyer(engagement, relecteur, environment, remarque) -> EngagementPersonnel:
    """« À revoir » : la ligne retourne à la personne, avec ce qu'on lui demande de corriger.
    Lève aussi une validation déjà donnée."""
    _relisible(engagement, relecteur, environment)
    remarque = (remarque or "").strip()
    if not remarque:
        raise ErreurEngagement("Dites ce qui est à revoir : la personne ne peut pas le deviner.")
    engagement.valide_par, engagement.valide_le, engagement.remarque_chef = None, None, remarque[:500]
    engagement.save(update_fields=["valide_par", "valide_le", "remarque_chef"])
    return engagement


def activite(utilisateur, environment, du, au) -> list:
    """Ce que la personne et ses équipes ont fait entre deux dates, pour l'aider à retrouver
    ses heures : ses créneaux de planning, ce qu'elle a consigné, et la vie des dossiers et des
    missions de ses équipes.

    Volontairement sans le détail des commentaires : ils parlent de personnes aidées, et la
    question ici est seulement « à quelle heure se passait quoi »."""
    from .models import CreneauEquipe, Dossier, DossierHistorique, JournalCollectivite, Mission

    equipes = list(equipes_de(utilisateur))
    noms = {e.id: e.name for e in equipes}
    lignes = []

    for creneau in CreneauEquipe.objects.filter(
            equipe__in=equipes, date__gte=du.date(), date__lte=au.date()).select_related("utilisateur"):
        a_moi = creneau.utilisateur_id == utilisateur.id
        lignes.append({
            "quand": creneau.date.isoformat(), "heure": False, "source": "moi" if a_moi else "equipe",
            "equipe": noms.get(creneau.equipe_id, ""),
            "quoi": f"Planning : créneau {creneau.get_creneau_display().lower()} ({creneau.get_statut_display().lower()})"
                    + ("" if a_moi else " d'un coéquipier"),
        })

    for evenement in DossierHistorique.objects.filter(
            Q(auteur=utilisateur) | Q(dossier__equipe__in=equipes),
            date_creation__gte=du, date_creation__lte=au, environment=environment).select_related("dossier").distinct():
        lignes.append({
            "quand": evenement.date_creation, "heure": True,
            "source": "moi" if evenement.auteur_id == utilisateur.id else "equipe",
            "equipe": noms.get(evenement.dossier.equipe_id, ""),
            "quoi": f"Dossier {evenement.dossier.numero} : {evenement.evenement.lower()}",
        })

    for entree in JournalCollectivite.objects.filter(
            auteur=utilisateur, date_creation__gte=du, date_creation__lte=au, environment=environment):
        lignes.append({"quand": entree.date_creation, "heure": True, "source": "moi", "equipe": "",
                       "quoi": "Main courante : une entrée consignée"})

    # Les connexions à l'application : un repère simple, « j'ai ouvert l'application à 6 h 50 ».
    from .models import AuditLog
    for connexion in AuditLog.objects.filter(
            utilisateur=utilisateur, action__code="CONNEXION", succes=True,
            date_action__gte=du, date_action__lte=au).only("date_action"):
        lignes.append({"quand": connexion.date_action, "heure": True, "source": "moi", "equipe": "",
                       "quoi": "Connexion à l'application"})

    for mission in Mission.objects.filter(equipes__in=equipes, environment=environment).filter(
            Q(date_creation__gte=du, date_creation__lte=au) | Q(date_cloture__gte=du, date_cloture__lte=au)).distinct():
        for quand, verbe in ((mission.date_creation, "ouverte"), (mission.date_cloture, "close")):
            if quand is not None and du <= quand <= au:
                lignes.append({"quand": quand, "heure": True, "source": "equipe", "equipe": "",
                               "quoi": f"Mission « {mission.titre} » {verbe}"})

    lignes.sort(key=lambda l: str(l["quand"]), reverse=True)
    return lignes[:500]


def de_l_institution(crise, institution, environment):
    """Les engagements que cette institution relit : ceux partis en son nom ou avec l'une de
    ses équipes."""
    return (
        EngagementPersonnel.objects.filter(crise=crise, environment=environment)
        .filter(Q(institution=institution) | Q(equipe__institution=institution))
        .select_related("utilisateur", "equipe").order_by("parti_le").distinct()
    )
