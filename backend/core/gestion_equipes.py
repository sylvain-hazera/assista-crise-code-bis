"""Qui peut GÉRER une équipe : la règle de l'arbre (21/11/2026).

Demande de Sylvain : « Respecte l'arbre, un membre du bureau départemental ne peut pas modifier
un membre du bureau régional (sauf s'il a des droits supérieurs). » Puis, aux deux questions
posées : un cadre peut nommer un autre cadre de sa propre coordination (oui), et on affiche
« Bureau de la coordination » pour les échelons de coordination (oui).

Avant, la seule condition était « être de la même institution » (`_appartient_a_equipe`) : le
coordinateur de la Loire pouvait changer les cadres de la coordination régionale, ou du national.

**La règle**, pour une institution qui a un bureau (une association) :

- l'administrateur de la plateforme : toutes les équipes ;
- le bureau de l'institution (ou de l'institution délégataire) : toutes ses équipes — ce sont
  les « droits supérieurs » ;
- un cadre (encadrement, ou chef d'équipe) d'une équipe : cette équipe et toutes celles en
  dessous. Jamais au-dessus, jamais une branche voisine.

**Une institution sans bureau garde la règle d'avant.** Une mairie n'a ni bureau ni arbre de
coordination : ses agents gèrent ses équipes, comme jusqu'ici. Imposer l'arbre là où il n'existe
pas retirerait à une commune la main sur ses propres équipes.

Ce qui relève de la règle : la structure de l'équipe (modifier, désactiver, supprimer,
réactiver, déplacer dans l'arbre), sa composition (inviter, ajouter, encadrement) et sa
mission. Le travail opérationnel au quotidien (ressources, dossiers, points, canaux) reste
ouvert à l'institution, comme avant.

Le calcul est fait UNE fois par requête (`_contexte`) : la liste des équipes en sert 127 d'un
coup, et une requête par équipe la rendrait inutilisable.
"""
def _contexte(request):
    cache = getattr(request, "_gestion_equipes", None)
    if cache is not None:
        return cache
    from .models import ContactInstitution, Team, UserRole
    from .permissions import get_effective_role

    user = request.user
    admin = get_effective_role(request) == UserRole.ADMINISTRATOR
    contacts = list(ContactInstitution.objects.filter(utilisateur=user, actif=True)
                    .values_list("institution_id", "membre_bureau"))
    parents = dict(Team.objects.values_list("id", "equipe_parente_id"))
    cadre_de = set(Team.membres_encadrement.through.objects.filter(user_id=user.id)
                   .values_list("team_id", flat=True))
    cadre_de |= set(Team.objects.filter(leader_id=user.id).values_list("id", flat=True))
    avec_bureau = set(ContactInstitution.objects.filter(actif=True, membre_bureau=True)
                      .values_list("institution_id", flat=True).distinct())
    from .delegation_gestion import collectivites_deleguees
    cache = {
        "admin": admin,
        # Une collectivité pour laquelle il agit par délégation de gestion vaut appartenance.
        "membre_de": {i for i, _ in contacts} | {c.id for c in collectivites_deleguees(user)},
        "bureau_de": {i for i, b in contacts if b},
        "avec_bureau": avec_bureau,
        "parents": parents,
        "cadre_de": cadre_de,
    }
    try:
        request._gestion_equipes = cache
    except AttributeError:
        pass
    return cache


def _chaine(team_id, parents):
    """L'équipe et toutes ses ancêtres. Ensemble des vus : `equipe_parente` n'empêche pas un
    cycle saisi à la main."""
    vus, courant = [], team_id
    while courant is not None and courant not in vus:
        vus.append(courant)
        courant = parents.get(courant)
    return vus


def peut_gerer_equipe(request, team) -> bool:
    """Vrai si l'appelant peut modifier la structure, la composition ou la mission de `team`."""
    ctx = _contexte(request)
    if ctx["admin"]:
        return True
    institutions = {i for i in (team.institution_id, team.institution_delegataire_id) if i}
    if not institutions:
        # Équipe hors de toute institution : rien à hiérarchiser, règle d'avant (personne
        # d'autre que l'administrateur n'était bloqué par `_appartient_a_equipe`).
        return True
    if not institutions & ctx["membre_de"]:
        return False
    if not institutions & ctx["avec_bureau"]:
        return True     # institution sans bureau (une mairie) : la règle d'avant
    if institutions & ctx["bureau_de"]:
        return True
    return any(t in ctx["cadre_de"] for t in _chaine(team.id, ctx["parents"]))


MESSAGE_REFUS = ("Cette équipe est gérée par le niveau au-dessus du vôtre : seuls ses cadres, "
                 "ceux des équipes au-dessus d'elle et le bureau peuvent la modifier.")


def est_hierarchique(request, team) -> bool:
    """Vrai si l'équipe appartient à une institution qui a un bureau, donc organisée en arbre.
    Rattacher sous soi l'équipe d'une entreprise ou d'une autre mairie reste permis (voir
    TeamViewSet.rattacher_equipe) ; déplacer une équipe d'association qu'on ne gère pas, non."""
    ctx = _contexte(request)
    institutions = {i for i in (team.institution_id, team.institution_delegataire_id) if i}
    return bool(institutions & ctx["avec_bureau"])
