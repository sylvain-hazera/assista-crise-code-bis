"""Délégation de gestion : une AASC exploite la plateforme pour une collectivité (21/11/2026).

Ce module répond à trois questions, et à elles seules :

1. **Qui agit pour l'AASC sur une commune déléguée ?** Son bureau
   (`ContactInstitution.membre_bureau`) et l'encadrement (`leader`, `membres_encadrement`) de ses
   équipes actives dont le territoire couvre la commune — coordination nationale, zone de
   défense, région, département, équipe locale. Décision de Sylvain : « tous les cadres
   concernés ». Jamais recopié : quand l'encadrement change, les droits suivent.

2. **Cette personne peut-elle agir pour cette collectivité ?** Une délégation ACTIVE, non échue,
   dont elle est une des personnes qui agissent. C'est ce que lisent les contrôles
   d'appartenance (`institution_courante.est_membre`, `views._appartient_a_institution`,
   `perimetre_admin.institutions_visibles`…) : agir pour la mairie, c'est basculer son
   institution courante sur elle, et tout le reste de l'application suit.

3. **Cette collectivité n'a-t-elle plus que l'export ?** Quand l'AASC lui fournissait l'accès
   (`Institution.acces_fourni_par`) et qu'aucune délégation n'est plus active avec elle :
   « si la mairie rompt la convention, elle ne peut plus qu'exporter ses données ».

Le registre des personnes vulnérables n'est JAMAIS ouvert par ce module (voir
`vulnerabilites.py` : habilitation nominative ou DelegationCompetence dédiée).
"""
from django.db.models import Q
from django.utils import timezone

from .models import ContactInstitution, DelegationGestion, Team, User


def _departement(commune_code: str) -> str:
    if not commune_code:
        return ""
    return commune_code[:3] if commune_code[:2] in ("97", "98") else commune_code[:2]


def _region(commune_code: str):
    from .geo_lookup import commune_secteur_codes
    return (commune_secteur_codes(commune_code) or {}).get("region_code")


def equipe_couvre_commune(team, commune_code: str) -> bool:
    """Le territoire d'une équipe couvre-t-il la commune ? Échelon d'abord (une coordination
    départementale couvre tout son département), puis la zone d'intervention déclarée."""
    if not commune_code:
        return False
    echelon = (team.echelon or "").upper()
    code = team.territoire_code or ""
    dep = _departement(commune_code)
    if echelon == "NATIONAL":
        return True
    if echelon == "DEPARTEMENTAL" and code == dep:
        return True
    if echelon == "REGIONAL" and code and code == _region(commune_code):
        return True
    if echelon == "ZONE_DEFENSE" and code:
        from .zones_defense import departements_de_zone
        deps = {d[0] if isinstance(d, (list, tuple)) else d for d in departements_de_zone(code)}
        if dep in deps:
            return True
    if commune_code in (team.communes or []):
        return True
    return dep in (team.departements or [])


def communes_de(delegation) -> list:
    """Communes NOMMÉES par la délégation : sa liste, sinon la commune de la collectivité.
    Pour une délégation départementale ou intercommunale, voir `zones_de`."""
    if delegation.communes:
        return list(delegation.communes)
    code = delegation.collectivite.commune_code
    return [code] if code else []


def zones_de(delegation) -> list:
    """Zones couvertes, sous forme (niveau, code) : les communes listées, sinon le secteur de la
    collectivité — sa commune, son intercommunalité, ou son département (« la Réserve signe par
    défaut avec le département », 21/11/2026)."""
    if delegation.communes:
        return [("commune", c) for c in delegation.communes if c]
    c = delegation.collectivite
    niveau = c.secteur_niveau_effectif or "commune"
    if niveau == "departement" and c.departement_code:
        return [("departement", c.departement_code)]
    if niveau == "epci" and c.epci_code:
        return [("epci", c.epci_code)]
    return [("commune", c.commune_code)] if c.commune_code else []


def _departements_d_epci(epci_code) -> set:
    from .models import Commune
    return set(Commune.objects.filter(epci_code=epci_code).values_list("departement_code", flat=True))


def equipe_couvre_departement(team, dep: str) -> bool:
    echelon = (team.echelon or "").upper()
    code = team.territoire_code or ""
    if echelon == "NATIONAL":
        return True
    if echelon == "DEPARTEMENTAL":
        return code == dep
    if echelon == "REGIONAL" and code:
        from .models import Commune
        return Commune.objects.filter(departement_code=dep, region_code=code).exists()
    if echelon == "ZONE_DEFENSE" and code:
        from .zones_defense import departements_de_zone
        return dep in {d[0] if isinstance(d, (list, tuple)) else d for d in departements_de_zone(code)}
    return dep in (team.departements or [])


def equipe_couvre_zone(team, niveau: str, code: str) -> bool:
    if niveau == "commune":
        return equipe_couvre_commune(team, code)
    if niveau == "departement":
        return equipe_couvre_departement(team, code)
    if niveau == "epci":
        return any(equipe_couvre_departement(team, d) for d in _departements_d_epci(code) if d)
    return False


def crise_touche(delegation, crise) -> bool:
    """La crise touche-t-elle le territoire délégué ?"""
    communes = set(crise.zone_communes or [])
    for niveau, code in zones_de(delegation):
        if niveau == "commune" and code in communes:
            return True
        if niveau == "departement" and (code in (crise.zone_departements or [])
                                        or any(_departement(c) == code for c in communes)):
            return True
        if niveau == "epci":
            from .models import Commune
            if Commune.objects.filter(epci_code=code, code__in=communes).exists():
                return True
    return False


def est_en_vigueur(delegation) -> bool:
    if delegation.statut != DelegationGestion.Statut.ACTIVE:
        return False
    return delegation.date_fin is None or delegation.date_fin >= timezone.localdate()


def _delegations_en_vigueur():
    aujourd_hui = timezone.localdate()
    return (DelegationGestion.objects
            .filter(statut=DelegationGestion.Statut.ACTIVE)
            .filter(Q(date_fin__isnull=True) | Q(date_fin__gte=aujourd_hui))
            .select_related("collectivite", "aasc"))


def agit_pour(user, delegation) -> bool:
    """`user` est-il une des personnes qui agissent pour l'AASC sur cette délégation ?"""
    if user is None or not getattr(user, "is_authenticated", False) or not est_en_vigueur(delegation):
        return False
    membre = ContactInstitution.objects.filter(utilisateur=user, institution=delegation.aasc, actif=True).first()
    if membre is None:
        return False
    if membre.membre_bureau:
        return True
    zones = zones_de(delegation)
    equipes = (Team.objects.filter(institution=delegation.aasc, actif=True)
               .filter(Q(leader=user) | Q(membres_encadrement=user)).distinct())
    return any(equipe_couvre_zone(e, n, c) for e in equipes for n, c in zones)


def delegations_de(user) -> list:
    """Délégations en vigueur pour lesquelles `user` agit, mémorisées sur l'objet utilisateur le
    temps de la requête (ces contrôles sont appelés depuis des sérialiseurs, donc par ligne)."""
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    memo = getattr(user, "_delegations_gestion_memo", None)
    if memo is not None:
        return memo
    aasc_ids = list(ContactInstitution.objects.filter(utilisateur=user, actif=True)
                    .values_list("institution_id", flat=True))
    resultat = [d for d in _delegations_en_vigueur().filter(aasc_id__in=aasc_ids) if agit_pour(user, d)]
    try:
        user._delegations_gestion_memo = resultat
    except AttributeError:
        pass
    return resultat


def collectivites_deleguees(user) -> list:
    return [d.collectivite for d in delegations_de(user)]


def est_delegue(user, institution) -> bool:
    if institution is None:
        return False
    inst_id = getattr(institution, "pk", institution)
    return any(str(d.collectivite_id) == str(inst_id) for d in delegations_de(user))


def delegation_pour(user, institution):
    inst_id = getattr(institution, "pk", institution)
    return next((d for d in delegations_de(user) if str(d.collectivite_id) == str(inst_id)), None)


def contexte_delegue(request):
    """La délégation au titre de laquelle l'appelant agit en ce moment : son institution
    courante est une collectivité déléguée dont il n'est pas membre lui-même. None sinon."""
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False) or not user.institution_id:
        return None
    if ContactInstitution.objects.filter(utilisateur=user, institution_id=user.institution_id, actif=True).exists():
        return None
    return delegation_pour(user, user.institution_id)


def personnes_qui_agissent(delegation) -> list:
    """Les personnes qui agissent, pour l'écran de la délégation (bureau, puis cadres)."""
    membres = (User.objects.filter(institutions__institution=delegation.aasc, institutions__actif=True)
               .distinct())
    return [u for u in membres if agit_pour(u, delegation)]


def en_mode_export_seul(institution) -> bool:
    """La collectivité recevait l'accès de son AASC, et n'a plus de délégation en vigueur avec
    elle : elle ne peut plus qu'exporter ses données."""
    if institution is None or not getattr(institution, "acces_fourni_par_id", None):
        return False
    return not _delegations_en_vigueur().filter(
        collectivite=institution, aasc_id=institution.acces_fourni_par_id).exists()


def utilisateur_en_export_seul(user) -> bool:
    """Le compte travaille pour une collectivité en mode export seul (et n'est pas administrateur)."""
    from .models import UserRole
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "type", None) == UserRole.ADMINISTRATOR:
        return False
    institution = getattr(user, "institution", None)
    return bool(institution) and en_mode_export_seul(institution)
