"""Ce qu'un administrateur de la plateforme REGARDE : son institution, une autre, ou tout.

LE PROBLÈME (signalé par Sylvain le 15/11/2026)
Un administrateur échappait à tous les filtres de périmètre : partout, il voyait toutes les
institutions, toutes les équipes, toutes les missions de la plateforme. C'est son DROIT, mais
ce n'est pas ce dont il a besoin pour travailler : un administrateur qui est aussi cadre d'une
mairie veut d'abord voir sa mairie, comme ses collègues, et ne pas chercher ses trois équipes
parmi celles de cinquante institutions.

LA RÈGLE
Le sélecteur de la barre du haut dit ce que l'administrateur regarde, et le navigateur le
transmet à chaque requête dans l'en-tête `X-Perimetre` :

- `MIENNE` : son institution active, comme un cadre de cette institution (le choix par défaut
  de l'écran). Sans institution, il n'y a rien à quoi se restreindre : il voit tout.
- l'identifiant d'une institution : celle-là, comme s'il en était cadre.
- `TOUT` : toute la plateforme, comme avant.

CE QUE LE SÉLECTEUR CHANGE, ET CE QU'IL NE CHANGE PAS
Il réduit ce qui est AFFICHÉ dans les listes. Il ne retire aucun DROIT : un administrateur peut
toujours ouvrir un objet par son adresse, le modifier, valider un compte -- les contrôles de
permission ne lisent pas ce module. Ce n'est donc pas une barrière de sécurité, et il ne faut
jamais s'en servir comme telle.

Sans l'en-tête (ponts, application mobile, scripts, tests écrits avant ce module), rien ne
change : l'administrateur voit tout, comme avant. Pour tout autre rôle, l'en-tête est ignoré :
il ne peut jamais ÉLARGIR ce que quelqu'un voit.
"""
import uuid

from rest_framework.exceptions import ValidationError

from .models import UserRole
from .permissions import effective_role_or_none

EN_TETE = "HTTP_X_PERIMETRE"
TOUT, MIENNE = "TOUT", "MIENNE"


def _memo(request, cle, calcul):
    cache = getattr(request, "_perimetre_admin_memo", None)
    if cache is None:
        cache = {}
        try:
            request._perimetre_admin_memo = cache
        except AttributeError:
            return calcul()
    if cle not in cache:
        cache[cle] = calcul()
    return cache[cle]


def est_administrateur(request) -> bool:
    user = getattr(request, "user", None) if request is not None else None
    if not (user and getattr(user, "is_authenticated", False)):
        return False
    return effective_role_or_none(request) == UserRole.ADMINISTRATOR


def _choix(request):
    """(mode, institution) pour un administrateur : (TOUT, None) ou ("INSTITUTION", institution).
    Lève ValidationError sur un en-tête qui ne désigne rien : un périmètre mal compris ne doit
    pas se transformer en silence en « tout » ni en « rien »."""
    from .models import Institution

    meta = getattr(request, "META", None) or {}
    valeur = (meta.get(EN_TETE) or "").strip()
    if not valeur or valeur.upper() == TOUT:
        return TOUT, None
    if valeur.upper() == MIENNE:
        institution = getattr(request.user, "institution", None)
        return ("INSTITUTION", institution) if institution is not None else (TOUT, None)
    try:
        identifiant = uuid.UUID(valeur)
    except ValueError:
        raise ValidationError({"perimetre": "Périmètre invalide (TOUT, MIENNE ou l'identifiant d'une institution)."})
    institution = Institution.objects.filter(pk=identifiant).first()
    if institution is None:
        raise ValidationError({"perimetre": "Cette institution n'existe pas (ou plus)."})
    return "INSTITUTION", institution


def admin_voit_tout(request) -> bool:
    """Vrai pour un administrateur qui regarde toute la plateforme. C'est LA question à poser
    là où le code disait « si administrateur : pas de filtre »."""
    if not est_administrateur(request):
        return False
    return _memo(request, "choix", lambda: _choix(request))[0] == TOUT


def admin_sans_filtre(request, vue=None) -> bool:
    """Vrai si l'appelant est un administrateur que CETTE requête ne doit pas filtrer :

    - il regarde toute la plateforme, ou
    - il ouvre un objet précis (route de détail : lecture, modification, action sur un objet).

    Le second cas est ce qui garantit que le sélecteur ne retire aucun droit : seules les
    LISTES sont réduites. Sans lui, un administrateur regardant sa mairie recevrait « 404 » en
    ouvrant l'équipe d'une autre institution dont on lui a envoyé l'adresse.

    `vue` : la vue DRF en cours ; à défaut elle est retrouvée sur la requête."""
    if not est_administrateur(request):
        return False
    if vue is None:
        vue = (getattr(request, "parser_context", None) or {}).get("view")
    if vue is not None and getattr(vue, "detail", None):
        return True
    return admin_voit_tout(request)


def institution_regardee(request):
    """L'institution dont l'appelant adopte le point de vue.

    Pour un administrateur qui a choisi une institution : celle-là. Pour tout autre (et pour un
    administrateur qui regarde tout) : la sienne, `User.institution`, exactement comme avant --
    les pages « ma collectivité » continuent ainsi de désigner la sienne."""
    user = getattr(request, "user", None) if request is not None else None
    if not (user and getattr(user, "is_authenticated", False)):
        return None
    if est_administrateur(request):
        mode, institution = _memo(request, "choix", lambda: _choix(request))
        if mode != TOUT:
            return institution
    # Collectivité en mode export seul (convention rompue avec l'AASC qui lui fournissait
    # l'accès) : plus aucun périmètre, seul l'export de ses données reste ouvert (21/11/2026).
    from .delegation_gestion import utilisateur_en_export_seul
    if utilisateur_en_export_seul(user):
        return None
    return getattr(user, "institution", None)


def institutions_visibles(request):
    """Identifiants des institutions dont l'appelant voit les objets, ou None pour « pas de
    restriction » (administrateur regardant toute la plateforme).

    - administrateur regardant une institution : celle-là et ses filles, à toute profondeur
      (décision du 19/11/2026 : « les listes incluent les filles ») ;
    - tout autre : les institutions où il est membre actif (`ContactInstitution`), la relation
      qui fait autorité -- ce que les vues écrivaient chacune de leur côté."""
    from .models import ContactInstitution

    if admin_voit_tout(request):
        return None
    if est_administrateur(request):
        institution = institution_regardee(request)
        if institution is None:
            return []
        return _memo(request, "regardee_et_filles",
                     lambda: list(institutions_descendantes({institution.id})))
    return _memo(request, "membre_de", lambda: _membre_ou_delegue(request.user))


def _membre_ou_delegue(user):
    """Ses rattachements actifs, plus les collectivités pour lesquelles il agit par délégation
    de gestion ; moins une collectivité en mode export seul (ses objets ne se consultent plus
    que par l'export)."""
    from .delegation_gestion import collectivites_deleguees, en_mode_export_seul
    from .models import ContactInstitution, Institution

    ids = set(ContactInstitution.objects.filter(utilisateur=user, actif=True)
              .values_list("institution_id", flat=True))
    ids.update(c.id for c in collectivites_deleguees(user))
    exclues = {i.id for i in Institution.objects.filter(id__in=ids, acces_fourni_par__isnull=False)
               if en_mode_export_seul(i)}
    return list(ids - exclues)


def etat(request):
    """Ce que l'écran affiche dans le sélecteur : le mode en vigueur et l'institution regardée."""
    if not est_administrateur(request):
        return {"administrateur": False, "mode": None, "institution": None}
    mode, institution = _memo(request, "choix", lambda: _choix(request))
    return {
        "administrateur": True,
        "mode": TOUT if mode == TOUT else "INSTITUTION",
        "institution": ({"id": str(institution.id), "nom": institution.nom_affichage or institution.nom}
                        if institution is not None else None),
    }


def institutions_descendantes(ids_racines):
    """Les institutions données et toutes leurs filles (`institution_parente`), à toute
    profondeur : CCAS et médiathèque sous une mairie, comités sous une association nationale.

    Même méthode que `visibilite_membres._equipes_descendantes` : une requête pour tout l'arbre,
    parcours en mémoire, ensemble des vus contre un cycle posé à la main."""
    from .models import Institution

    racines = {r for r in (ids_racines or ()) if r is not None}
    if not racines:
        return set()
    filles = {}
    for fille_id, mere_id in Institution.objects.exclude(institution_parente_id=None).values_list(
        "id", "institution_parente_id"
    ):
        filles.setdefault(mere_id, []).append(fille_id)
    vus, a_voir = set(racines), list(racines)
    while a_voir:
        for fille in filles.get(a_voir.pop(), ()):
            if fille not in vus:
                vus.add(fille)
                a_voir.append(fille)
    return vus


def institution_regardee_et_filles(request):
    """Pour un administrateur qui se place dans une institution : elle et ses filles — ce qu'il
    peut choisir pour AGIR au nom de cette institution (19/11/2026 : en se plaçant dans le
    Conseil départemental de la Loire, la page des campagnes proposait toutes les institutions
    de la plateforme). None quand il regarde toute la plateforme (pas de restriction)."""
    if admin_voit_tout(request):
        return None
    regardee = institution_regardee(request)
    return institutions_descendantes({regardee.id}) if regardee is not None else set()
