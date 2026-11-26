"""Une association existante rejoint le réseau, et jusqu'où elle intervient (26/11/2026).

Décisions de Sylvain :
- « Elles sont déjà existantes et veulent rejoindre notre réseau » : une demande simple (nom,
  activité, commune du siège, étendue), validée par l'administrateur, qui vérifie surtout qu'il ne
  s'agit pas d'un doublon. Le même parcours sert à une AASC et à une association non agréée
  (FCBA 33, signaleurs radio sur les courses cyclistes).
- « Par défaut, le périmètre de l'association, c'est elle. » L'étendue n'est pas une liste de
  territoires : c'est un échelon compté depuis la commune du siège — commune, intercommunalité,
  département, région, zone de défense, national (outre-mer compris).
- L'étendue dit jusqu'où l'association peut **être sollicitée** (demande de mobilisation) ou
  **solliciter** une commune pour proposer son intervention (proposer son aide sur une crise).
- N'importe quel échelon est ouvert à une association non agréée ; le bureau le change librement.
"""
from django.db import transaction
from django.utils import timezone

from .models import (
    ContactInstitution, DemandeAdhesionAssociation, EchelonIntervention, Institution, InstitutionType,
    StatutAdhesionAssociation,
)

ORDRE = [EchelonIntervention.COMMUNE, EchelonIntervention.EPCI, EchelonIntervention.DEPARTEMENT,
         EchelonIntervention.REGION, EchelonIntervention.ZONE, EchelonIntervention.NATIONAL]


class ErreurAdhesion(ValueError):
    """Geste refusé ; le message est fait pour être lu."""


def zone_de_departement(departement_code: str):
    """(code, nom) de la zone de défense d'un département, ou None."""
    from .zones_defense import ZONES_DEFENSE
    for code, nom, _chef_lieu, regions in ZONES_DEFENSE:
        for _region, _nom_region, departements in regions:
            if any(d == departement_code for d, _ in departements):
                return code, nom
    return None


def _commune(code):
    from .models import Commune
    return Commune.objects.filter(code=code).first() if code else None


def libelles(commune_code: str) -> dict:
    """Ce que chaque échelon veut dire depuis cette commune : « Floirac », « Bordeaux Métropole »,
    « Gironde », « Nouvelle-Aquitaine », « zone Sud-Ouest », « toute la France »."""
    from .geo_lookup import commune_from_code, epci_nom_from_code
    from .geo_reference import DEPARTEMENTS, REGIONS
    c = _commune(commune_code)
    if c is None:
        return {}
    zone = zone_de_departement(c.departement_code or "")
    return {
        EchelonIntervention.COMMUNE: c.nom or commune_from_code(c.code) or c.code,
        EchelonIntervention.EPCI: (epci_nom_from_code(c.epci_code) if c.epci_code else "") or "intercommunalité",
        EchelonIntervention.DEPARTEMENT: DEPARTEMENTS.get(c.departement_code) or c.departement_code or "",
        EchelonIntervention.REGION: REGIONS.get(c.region_code) or c.region_code or "",
        EchelonIntervention.ZONE: f"zone {zone[1]}" if zone else "zone de défense",
        EchelonIntervention.NATIONAL: "toute la France, outre-mer compris",
    }


def commune_dans_etendue(institution, commune_code: str) -> bool:
    """La commune est-elle dans l'étendue d'intervention de l'institution ? Faux sans commune du
    siège connue (sauf échelon national)."""
    echelon = getattr(institution, "echelon_intervention", EchelonIntervention.COMMUNE) or EchelonIntervention.COMMUNE
    if echelon == EchelonIntervention.NATIONAL:
        return True
    siege, cible = _commune(institution.commune_code), _commune(commune_code)
    if siege is None or cible is None:
        return False
    if echelon == EchelonIntervention.COMMUNE:
        return siege.code == cible.code
    if echelon == EchelonIntervention.EPCI:
        return bool(siege.epci_code) and siege.epci_code == cible.epci_code
    if echelon == EchelonIntervention.DEPARTEMENT:
        return bool(siege.departement_code) and siege.departement_code == cible.departement_code
    if echelon == EchelonIntervention.REGION:
        return bool(siege.region_code) and siege.region_code == cible.region_code
    if echelon == EchelonIntervention.ZONE:
        za, zb = zone_de_departement(siege.departement_code or ""), zone_de_departement(cible.departement_code or "")
        return za is not None and za == zb
    return False


def soumise_a_l_etendue(institution) -> bool:
    """Seules les associations ont une étendue : une mairie, une préfecture ou un SDIS agissent
    selon leurs propres compétences."""
    # La réserve communale n'en a pas : elle part en renfort avec l'accord de chaque commune
    # d'accueil (core/accords_communes.py), au nom de sa mairie.
    return (getattr(getattr(institution, "type", None), "code", "") or "").lower() in ("aasc", "association")


def crise_dans_etendue(institution, crise) -> bool:
    """Au moins une commune de la crise est dans l'étendue de l'association."""
    if not soumise_a_l_etendue(institution) or institution.echelon_intervention == EchelonIntervention.NATIONAL:
        return True
    if crise is None:
        return False
    communes = list(crise.zone_communes or [])
    if not communes and getattr(crise, "commune_code", None):
        communes = [crise.commune_code]
    return any(commune_dans_etendue(institution, c) for c in communes)


def message_hors_etendue(institution) -> str:
    libelle = libelles(institution.commune_code).get(institution.echelon_intervention, "")
    return (f"{institution.nom} intervient jusqu'à l'échelon « {institution.get_echelon_intervention_display().lower()} »"
            + (f" ({libelle})" if libelle else "") + " : cette commune est en dehors. Son bureau peut élargir cette étendue.")


# --- La demande ---------------------------------------------------------------------------------

def doublons_possibles(nom: str):
    """Les associations déjà inscrites dont le nom, sans accents ni casse, est le même ou contient
    l'autre. Comparaison en Python : le nom est chiffré en base."""
    from .institution_attachment import filtre_associatif, nom_comparable
    cible = nom_comparable(nom)
    if not cible:
        return []
    trouvees = []
    for institution in Institution.objects.filter(filtre_associatif("type__code"), actif=True):
        n = nom_comparable(institution.nom)
        if n and (n == cible or (len(cible) >= 6 and (cible in n or n in cible))):
            trouvees.append(institution)
    return trouvees


def deposer(demandeur, environment, *, nom, activite, commune_code, echelon, agrement="", fonction="", telephone=""):
    nom, activite = (nom or "").strip()[:200], (activite or "").strip()[:300]
    if not nom or not activite:
        raise ErreurAdhesion("Indiquez le nom de l'association et ce qu'elle fait.")
    if _commune(commune_code) is None:
        raise ErreurAdhesion("Choisissez la commune du siège dans la liste.")
    if echelon not in EchelonIntervention.values:
        echelon = EchelonIntervention.COMMUNE
    if DemandeAdhesionAssociation.objects.filter(demandeur=demandeur, statut=StatutAdhesionAssociation.EN_ATTENTE).exists():
        raise ErreurAdhesion("Vous avez déjà une demande en attente : l'administrateur y répond au plus vite.")
    from .institution_attachment import nom_comparable
    identiques = [i for i in doublons_possibles(nom) if nom_comparable(i.nom) == nom_comparable(nom)]
    if identiques:
        raise ErreurAdhesion(f"« {identiques[0].nom} » est déjà dans le réseau : demandez à la rejoindre comme membre, "
                             "son bureau acceptera votre candidature.")
    demande = DemandeAdhesionAssociation.objects.create(
        demandeur=demandeur, environment=environment, nom=nom, activite=activite, commune_code=commune_code,
        echelon=echelon, agrement=(agrement or "").strip()[:300], fonction=(fonction or "").strip()[:100],
        telephone=(telephone or "").strip()[:30],
    )
    from .notifications_admin import notifier_administrateurs
    try:
        notifier_administrateurs("Nouvelle demande d'adhésion d'association",
                                 f"{nom} ({libelles(commune_code).get(EchelonIntervention.COMMUNE, commune_code)}) demande à rejoindre le réseau.")
    except Exception:  # une notification qui échoue ne perd pas la demande
        pass
    return demande


@transaction.atomic
def accepter(demande, par, request=None):
    """Crée l'association et fait du demandeur son bureau, d'un seul geste."""
    from .institution_attachment import attach_user_with_role, get_or_create_institution_team
    if demande.statut != StatutAdhesionAssociation.EN_ATTENTE:
        raise ErreurAdhesion("Cette demande a déjà été traitée.")
    code_type = "aasc" if demande.agrement.strip() else "association"
    libelle = "AASC (Association agréée de sécurité civile)" if code_type == "aasc" else "Association"
    type_ = InstitutionType.objects.filter(code__iexact=code_type).first() \
        or InstitutionType.objects.create(code=code_type, libelle=libelle)
    c = _commune(demande.commune_code)
    institution = Institution.objects.create(
        nom=demande.nom, type=type_, description=demande.activite, commune_code=demande.commune_code,
        commune_nom=(c.nom if c else None), echelon_intervention=demande.echelon, environment=demande.environment,
    )
    attach_user_with_role(demande.demandeur, institution, "RESPONSABLE", request,
                          fonction=demande.fonction or "Bureau", contact_principal=True)
    ContactInstitution.objects.filter(institution=institution, utilisateur=demande.demandeur).update(membre_bureau=True)
    # Le bureau d'une association agit au nom d'une institution : son compte devient un compte de
    # secours organisés (pages de l'association, proposer son aide sur une crise), rattaché à elle.
    from .models import UserRole
    u = demande.demandeur
    champs = []
    if u.type not in (UserRole.ADMINISTRATOR, UserRole.LOCAL_AUTHORITY, UserRole.ORGANIZED_RESCUE, UserRole.REGULATEUR):
        u.type = UserRole.ORGANIZED_RESCUE
        champs.append("type")
    if not getattr(u, "institution_id", None):
        u.institution = institution
        champs.append("institution")
    if champs:
        u.save(update_fields=champs)
    get_or_create_institution_team(institution, request)
    demande.statut, demande.institution, demande.traite_par, demande.traite_le = (
        StatutAdhesionAssociation.ACCEPTEE, institution, par, timezone.now())
    demande.save(update_fields=["statut", "institution", "traite_par", "traite_le"])
    from .notifications_application import prevenir
    prevenir(demande.demandeur, f"{institution.nom} a rejoint le réseau",
             "Vous en êtes le bureau : invitez vos membres et publiez vos manifestations.",
             lien="/admin/membres-association", institution=institution, environment=demande.environment)
    return institution


def refuser(demande, par, motif):
    if demande.statut != StatutAdhesionAssociation.EN_ATTENTE:
        raise ErreurAdhesion("Cette demande a déjà été traitée.")
    if not (motif or "").strip():
        raise ErreurAdhesion("Dites pourquoi : la personne ne peut pas le deviner.")
    demande.statut, demande.motif_refus, demande.traite_par, demande.traite_le = (
        StatutAdhesionAssociation.REFUSEE, motif.strip()[:300], par, timezone.now())
    demande.save(update_fields=["statut", "motif_refus", "traite_par", "traite_le"])
    from .notifications_application import prevenir
    prevenir(demande.demandeur, "Demande d'adhésion de votre association", demande.motif_refus,
             lien="/rejoindre-association", environment=demande.environment)
    return demande


def changer_echelon(institution, par, echelon):
    """Le bureau change librement l'étendue d'intervention (décision du 26/11/2026)."""
    from .manifestations import organise
    if not organise(par, institution.id):
        raise ErreurAdhesion("Seul le bureau de l'association change son étendue d'intervention.")
    if echelon not in EchelonIntervention.values:
        raise ErreurAdhesion("Échelon inconnu.")
    institution.echelon_intervention = echelon
    institution.save(update_fields=["echelon_intervention"])
    return institution
