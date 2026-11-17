"""Le standard de crise d'une collectivité : une fiche par appel reçu (17/11/2026).

Quand la mairie ouvre un numéro pour ses habitants, chaque appel doit laisser une trace : qui a
appelé, pour quoi, quelle suite a été donnée. Jusqu'ici l'agent n'avait que la main courante,
où un appel se noie entre deux décisions.

La nature de l'appel reprend les catégories de l'application — demande d'aide, offre d'aide,
signalement — plus « renseignement » et « autre ». Ce n'est **pas** une demande ou une offre
déposée à la place de l'habitant : celles-ci exigent une adresse électronique et un jeton de
suivi que quelqu'un qui téléphone n'a pas. Un appel qui demande une intervention ouvre un
**dossier**, l'unité que les équipes traitent déjà.

Rien en clair : le nom, le téléphone, le lieu, l'objet et la suite donnée sont chiffrés. Le
dossier ouvert depuis une fiche ne recopie aucune de ces données (son titre et sa description
ne sont pas chiffrés) : il porte le numéro de la fiche, que les ayants droit vont relire.
"""
import uuid

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import AppelStandard, Dossier, DossierHistorique, NatureAppelStandard, SuiteAppelStandard


def numero_suivant(institution, environment) -> int:
    dernier = AppelStandard.objects.filter(institution=institution, environment=environment).aggregate(m=Max("numero"))["m"]
    return (dernier or 0) + 1


@transaction.atomic
def enregistrer(institution, environment, agent, *, nature, objet, crise=None, appelant_nom="",
                appelant_telephone="", lieu="") -> AppelStandard:
    """Crée la fiche. Le numéro est pris sous verrou : deux agents qui décrochent en même temps
    n'obtiennent pas le même."""
    type(institution).objects.select_for_update().get(pk=institution.pk)
    return AppelStandard.objects.create(
        institution=institution, environment=environment, crise=crise, recu_par=agent,
        numero=numero_suivant(institution, environment), nature=nature, objet=objet,
        appelant_nom=appelant_nom, appelant_telephone=appelant_telephone, lieu=lieu,
    )


def clore(appel, agent, suite, suite_donnee="") -> AppelStandard:
    appel.suite = suite
    appel.suite_donnee = suite_donnee
    appel.traite_par = agent
    appel.traite_le = timezone.now()
    appel.save(update_fields=["suite", "suite_donnee", "traite_par", "traite_le"])
    return appel


@transaction.atomic
def ouvrir_un_dossier(appel, agent, priorite=None) -> Dossier:
    """Ouvre le dossier que les équipes traiteront. Une fiche n'en ouvre qu'un."""
    if appel.dossier_id:
        return appel.dossier
    if appel.crise_id is None:
        raise ValueError("Rattachez d'abord cet appel à une crise : un dossier appartient à une crise.")
    nature = appel.get_nature_display().lower()
    dossier = Dossier.objects.create(
        numero=f"DOS-{uuid.uuid4().hex[:8].upper()}",
        crise=appel.crise, generique=True, institution_demandeuse=appel.institution,
        titre=f"Appel au standard n° {appel.numero} — {nature}",
        # Volontairement vide de tout détail : ce champ n'est pas chiffré.
        description=(f"Dossier ouvert depuis la fiche d'appel n° {appel.numero} du standard de "
                     f"{appel.institution.nom}. Le détail de l'appel se lit sur la fiche."),
        priorite=priorite or Dossier.Priorite.NORMALE,
        statut=Dossier.Statut.EN_ATTENTE_AFFECTATION, environment=appel.environment,
    )
    DossierHistorique.objects.create(
        dossier=dossier, auteur=agent, evenement="Création",
        commentaire=f"Ouvert depuis la fiche d'appel n° {appel.numero} du standard de crise.",
        environment=dossier.environment,
    )
    appel.dossier = dossier
    appel.suite = SuiteAppelStandard.TRANSMIS
    appel.traite_par = agent
    appel.traite_le = timezone.now()
    appel.save(update_fields=["dossier", "suite", "traite_par", "traite_le"])
    return dossier


def synthese(institution, environment, crise=None) -> dict:
    """Combien d'appels, de quelle nature, et combien attendent encore."""
    appels = AppelStandard.objects.filter(institution=institution, environment=environment)
    if crise is not None:
        appels = appels.filter(crise=crise)
    par_nature = {code: 0 for code in NatureAppelStandard.values}
    par_suite = {code: 0 for code in SuiteAppelStandard.values}
    for nature, suite in appels.values_list("nature", "suite"):
        par_nature[nature] = par_nature.get(nature, 0) + 1
        par_suite[suite] = par_suite.get(suite, 0) + 1
    return {
        "total": sum(par_nature.values()),
        "a_traiter": par_suite[SuiteAppelStandard.A_TRAITER],
        "par_nature": [{"code": c, "libelle": NatureAppelStandard(c).label, "nombre": par_nature[c]}
                       for c in NatureAppelStandard.values],
        "par_suite": [{"code": c, "libelle": SuiteAppelStandard(c).label, "nombre": par_suite[c]}
                      for c in SuiteAppelStandard.values],
    }
