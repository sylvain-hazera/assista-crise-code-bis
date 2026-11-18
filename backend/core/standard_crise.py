"""Le standard de crise d'une collectivité : une fiche par appel reçu (17/11/2026).

Quand la mairie ouvre un numéro pour ses habitants, chaque appel doit laisser une trace : qui a
appelé, pour quoi, quelle suite a été donnée. Jusqu'ici l'agent n'avait que la main courante,
où un appel se noie entre deux décisions.

**Corrigé le 18/11/2026.** La première version notait ici, à part, les demandes d'aide, les
offres et les signalements reçus par téléphone : c'était un doublon des fiches de
l'application. Désormais l'agent remplit **le formulaire public à la place de l'appelant**
(« saisie pour autrui ») : la vraie demande, la vraie offre, le vrai signalement, la vraie
recherche de personne sont créés, et suivent leur chemin habituel. La fiche d'appel n'en est
que la trace — qui a décroché, quand — et y renvoie (`rattacher_saisie`). L'adresse
électronique, que quelqu'un qui téléphone n'a pas toujours, devient facultative dans ce seul
cas (`SaisieStandardMixin`), et aucun courriel ne part quand elle manque.

Seuls « renseignement » et « autre » se notent directement ici : ils n'ont pas d'équivalent
ailleurs. Un tel appel peut encore ouvrir un **dossier** s'il demande une intervention.

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


def institution_du_standard(request):
    """L'institution au nom de laquelle l'appelant tient le standard, ou None."""
    from .permissions import IsInstitutionalActor
    from .views_stocks import institution_regardee

    if not getattr(request.user, "is_authenticated", False):
        return None
    if not IsInstitutionalActor().has_permission(request, None):
        return None
    return institution_regardee(request)


def est_saisie_standard(request) -> bool:
    """Ce dépôt est-il fait par le standard, pour un appelant ? Il faut le demander
    (`via_standard`) ET en avoir le droit : un particulier qui ajouterait ce champ n'obtient
    rien, son adresse électronique reste exigée."""
    if request is None or str(request.data.get("via_standard") or "").lower() not in ("1", "true", "oui"):
        return False
    return institution_du_standard(request) is not None


def _decrire(objet):
    """(nature, objet de l'appel, nom, téléphone, lieu, crise, relation) pour une fiche créée."""
    nom_du_modele = type(objet).__name__
    if nom_du_modele == "Request":
        return (NatureAppelStandard.DEMANDE_AIDE, objet.title,
                f"{objet.first_name_request or ''} {objet.last_name_request or ''}".strip(),
                objet.phone_request or "", "", objet.crisis, "demandes")
    if nom_du_modele == "Offer":
        return (NatureAppelStandard.OFFRE_AIDE, objet.title,
                f"{objet.first_name_offer or ''} {objet.last_name_offer or ''}".strip(),
                getattr(objet, "phone_offer", "") or "", "", objet.crisis, "offres")
    if nom_du_modele == "Information":
        return (NatureAppelStandard.SIGNALEMENT, objet.title,
                f"{objet.first_name_information or ''} {objet.last_name_information or ''}".strip(),
                objet.phone_information or "", "", objet.crisis, "informations")
    if nom_du_modele == "RecherchePersonne":
        return (NatureAppelStandard.PERSONNE_DISPARUE, "Recherche d'une personne disparue",
                objet.contact_nom or "", objet.contact_telephone or "", objet.ville or "",
                getattr(objet, "crise", None), "recherches")
    raise ValueError(f"Rien à rattacher au standard pour {nom_du_modele}.")


def rattacher_saisie(request, objet):
    """Après la création d'une fiche par le standard : la trace de l'appel, qui y renvoie.

    Un même formulaire peut créer plusieurs fiches (deux besoins dans une demande) : elles
    portent le même `standard_appel`, tiré par le navigateur, et ne laissent qu'UNE fiche
    d'appel. Ne fait jamais échouer le dépôt : la vraie fiche compte plus que sa trace."""
    if not est_saisie_standard(request):
        return None
    import logging

    from django.db import IntegrityError

    institution = institution_du_standard(request)
    environnement = objet.environment
    nature, titre, nom, telephone, lieu, crise, relation = _decrire(objet)
    try:
        identifiant = uuid.UUID(str(request.data.get("standard_appel")))
    except (ValueError, TypeError):
        identifiant = uuid.uuid4()
    try:
        cle = dict(institution=institution, environment=environnement, identifiant_saisie=identifiant)
        appel = AppelStandard.objects.filter(**cle).first()
        if appel is None:
            try:
                with transaction.atomic():
                    appel = enregistrer(institution, environnement, request.user, nature=nature, objet=titre or "—",
                                        crise=crise, appelant_nom=nom, appelant_telephone=telephone, lieu=lieu)
                    appel.identifiant_saisie = identifiant
                    # La vraie fiche existe et suit son chemin : rien à traiter au standard.
                    appel.suite = SuiteAppelStandard.TRANSMIS
                    appel.save(update_fields=["identifiant_saisie", "suite"])
            except IntegrityError:
                # Deux fiches du même formulaire arrivées en même temps : l'autre a gagné.
                appel = AppelStandard.objects.get(**cle)
        getattr(appel, relation).add(objet)
        # La fiche elle-même dit qu'elle a été saisie pour autrui, et par qui.
        type(objet).objects.filter(pk=objet.pk).update(enregistre_pour_autrui_par=institution)
        objet.enregistre_pour_autrui_par = institution
        return appel
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("Fiche d'appel du standard non créée pour %s", type(objet).__name__)
        return None


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
