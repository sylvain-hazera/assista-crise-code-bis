"""Filtrage par zone de compétence (commune, EPCI, département, région, national).

Fonctionnement et règles : DOCUMENTATION.md, § 5.5.
"""
from django.db.models import Q
from rest_framework import status
from rest_framework.response import Response

from .models import UserRole
from .permissions import effective_role_or_none

# colonnes dénormalisées sur Offer et Request ; "national" n'a pas de filtre
SECTEUR_CHAMP_PAR_NIVEAU = {
    "commune": "commune_code",
    "epci": "epci_code",
    "departement": "departement_code",
    "region": "region_code",
}


def _parametre(request, nom):
    """Un paramètre de requête, que l'appelant soit une requête DRF ou une requête Django nue.

    `query_params` n'existe que sur les requêtes DRF. Ce module est aussi traversé depuis des
    sérialiseurs et des helpers qui reçoivent parfois une requête Django simple, où le même
    dictionnaire s'appelle `GET` — lire l'un sans l'autre lève un AttributeError au milieu d'un
    contrôle d'accès, c'est-à-dire au pire endroit."""
    params = getattr(request, 'query_params', None)
    if params is None:
        params = getattr(request, 'GET', None)
    return (params.get(nom) if params is not None else None) or ''


def _institution_commune_or_400(request):
    """Code commune de l'institution de l'appelant, ou une Response 400 explicite (plutôt
    qu'une liste vide qui masquerait la cause).

    Lit le raccourci `User.institution` et non `ContactInstitution`. L'invariant « un
    rattachement actif implique un raccourci renseigné » est tenu à l'écriture
    (`ContactInstitution.save`), ce qui est plus sûr que de le rattraper dans la quarantaine
    d'endroits qui lisent ce raccourci — dont des portes de contrôle d'accès au registre des
    personnes vulnérables, qu'on ne réécrit pas à l'aveugle.

    Les deux messages ci-dessous sont distincts et nommés, parce que le message unique
    précédent (« contactez un administrateur ») a coûté cher : un agent rattaché mais sans
    raccourci l'a reçu 75 fois sur quatre sessions avant de cesser de revenir, et
    l'administrateur, qui l'avait bel et bien rattaché, n'avait aucun moyen de comprendre que
    son geste n'y changeait rien."""
    institution = getattr(request.user, 'institution', None)
    if institution is None:
        return Response(
            {"error": "Votre compte n'est rattaché à aucune collectivité. Si vous venez "
                      "d'être ajouté comme contact d'une institution, déconnectez-vous et "
                      "reconnectez-vous ; si le message persiste, signalez-le : c'est une "
                      "anomalie de rattachement, pas un réglage de votre part."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # `?commune=` : une institution qui intervient SUR le territoire d'une autre doit dire
    # laquelle elle regarde — une association agréée acceptée sur six communes d'une crise n'a
    # pas « une » commune, elle en a six, et c'est à elle de choisir. Toujours vérifié contre
    # le périmètre accordé : le paramètre choisit parmi des droits, il n'en crée aucun.
    demandee = _parametre(request, 'commune').strip()
    if demandee:
        if demandee == institution.commune_code or demandee in _communes_autorisees_codes(request):
            return demandee
        return Response(
            {"error": f"Vous n'avez pas de droits sur la commune {demandee}. Une collectivité "
                      f"doit vous avoir accepté sur une crise de cette commune, ou vous avoir "
                      f"accordé une convention."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if institution.commune_code:
        return institution.commune_code

    # Pas de commune propre : si des communes sont accordées, le refus LES NOMME pour que
    # l'écran puisse proposer de choisir, au lieu d'annoncer une impasse. C'est le cas d'une
    # AASC, qui n'a pas de territoire à elle et n'en aura jamais.
    disponibles = _communes_autorisees_codes(request)
    if disponibles:
        return Response(
            {"error": f"« {institution.nom} » n'a pas de commune propre : choisissez la "
                      f"collectivité que vous souhaitez consulter.",
             "communes_disponibles": _nommer(disponibles),
             "choix_requis": "commune"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {"error": f"Aucune commune n'est renseignée sur « {institution.nom} », et aucune "
                  f"collectivité ne vous a accordé de droits. Cette vue est territoriale : "
                  f"elle ne peut rien afficher tant qu'une commune ne vous a pas accepté sur "
                  f"une crise, ou accordé une convention.",
         "communes_disponibles": [],
         "choix_requis": "commune"},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _nommer(codes) -> list:
    """Les communes d'un refus, avec leur nom, triées par nom.

    Un sélecteur qui n'affiche que des codes INSEE est illisible : personne ne sait que 29026
    est Châteauneuf-du-Faou. Une seule requête sur le référentiel, et seulement sur le chemin
    du refus — un code absent du référentiel reste proposé sous son code plutôt que d'être
    escamoté, sans quoi un droit réel deviendrait inaccessible."""
    from .models import Commune

    noms = dict(
        Commune.objects.filter(code__in=list(codes)).values_list("code", "nom")
    )
    return sorted(
        ({"code": c, "nom": noms.get(c) or c} for c in codes),
        key=lambda commune: (commune["nom"] or "").lower(),
    )


def _communes_autorisees_codes(request) -> set:
    """Les seuls codes COMMUNE du périmètre accordé.

    Un département accordé n'est volontairement pas déplié en communes : « Vue Ma
    Collectivité » demande de désigner UNE collectivité, et étendre une convention
    départementale en six cents choix dans un menu déroulant ne rendrait service à personne.
    Le filtrage des listes, lui, honore bien le département (voir apply_perimetre)."""
    return {code for niveau, code in communes_accordees(request) if niveau == "commune"}


def _sdis_en_demo(request):
    from .models import Environment
    from .permissions import get_active_environment

    institution = getattr(request.user, 'institution', None)
    if institution is None or not institution.type_id:
        return False
    if (institution.type.code or '').upper() != 'SDIS':
        return False
    return get_active_environment(request) == Environment.DEMO


def _institution_secteur_or_400(request):
    """(niveau, code) du secteur de l'institution de l'appelant, ou une Response 400.
    "national" renvoie un code None. En zone DEMO, un SDIS a une portée nationale (les jeux de
    démonstration couvrent plusieurs départements, POC SDIS 40 du 20/10/2026)."""
    if _sdis_en_demo(request):
        return "national", None

    commune_code = _institution_commune_or_400(request)
    if isinstance(commune_code, Response):
        return commune_code

    institution = request.user.institution
    # calculé par Institution.save()
    niveau = institution.secteur_niveau_effectif or "commune"

    if niveau == "national":
        return "national", None
    if niveau == "commune":
        return "commune", commune_code

    code = getattr(institution, f"{niveau}_code", None)
    if not code:
        return Response(
            {"error": f"Secteur ({niveau}) introuvable pour votre institution."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return niveau, code


def viewer_zone_code(request):
    """Comme _institution_secteur_or_400, mais None au lieu d'une 400 (pour les serializers).

    Rend la zone PROPRE de l'institution, c'est-à-dire son territoire permanent. Pour savoir ce
    que l'appelant a le droit de voir, utiliser `viewer_perimetre` : une institution peut avoir
    reçu des communes en plus (crise ou convention), et une AASC n'a que celles-là."""
    user = getattr(request, 'user', None) if request is not None else None
    if not (user and user.is_authenticated):
        return None
    result = _institution_secteur_or_400(request)
    if isinstance(result, Response):
        return None
    return result


def _memo(request, cle, calcul):
    """Mémorise un calcul sur la requête courante.

    `communes_accordees` coûte deux requêtes SQL, et les helpers de ce module sont appelés
    depuis des sérialiseurs, donc PAR LIGNE : sans cette mémoire, lister vingt-cinq demandes
    passait de 15 requêtes à 113 (mesuré par test_liste_demandes_est_affectee_sans_requete_par_ligne,
    qui a attrapé la régression). La durée de vie est celle de la requête HTTP, ce qui est
    exactement la fenêtre pendant laquelle le périmètre ne peut pas changer."""
    if request is None:
        return calcul()
    cache = getattr(request, '_zone_scoping_memo', None)
    if cache is None:
        cache = {}
        try:
            request._zone_scoping_memo = cache
        except AttributeError:
            # Objet requête exotique qui refuse les attributs : on calcule sans mémoriser
            # plutôt que d'échouer au milieu d'un contrôle d'accès.
            return calcul()
    if cle not in cache:
        cache[cle] = calcul()
    return cache[cle]


def communes_accordees(request) -> list:
    """Zones accordées à l'institution de l'appelant EN PLUS de la sienne, s'il y en a.

    Deux sources, et seulement deux, voulues ainsi (décision du 28/10/2026) :

    1. **La crise, commune par commune** — le cas par défaut. L'institution est acteur VALIDÉ
       sur une crise en cours : elle obtient les communes listées sur son implication, ou
       toutes celles de la crise si la liste est vide. C'est ce qui permet à chaque mairie
       d'accepter pour son seul territoire sur une crise multi-communes.
    2. **La convention, de longue durée** — l'exception. Une DelegationCompetence active
       accorde des communes, et parfois des départements entiers, sans lien avec une crise.

    Rendue sous la forme d'une liste de zones `(niveau, code)` et non de simples codes commune,
    pour qu'un département délégué reste un département : le convertir en liste de communes
    demanderait de requêter le référentiel à chaque appel, et perdrait les communes qui y
    seraient créées ensuite.

    Jamais d'exception propagée : cette fonction est appelée sur le chemin de lecture de
    presque toutes les listes. En cas de doute elle rend moins, pas plus."""
    return _memo(request, 'communes_accordees',
                 lambda: _calculer_communes_accordees(request))


def _calculer_communes_accordees(request) -> list:
    """Le calcul nu, sans mémoire — voir communes_accordees."""
    from django.utils import timezone

    from .models import (
        Crisis, DelegationCompetence, ImplicationInstitution, StatutImplication,
        TypeImplication,
    )

    user = getattr(request, 'user', None) if request is not None else None
    if not (user and getattr(user, 'is_authenticated', False)):
        return []
    institution = getattr(user, 'institution', None)
    if institution is None:
        return []

    zones = set()
    maintenant = timezone.now()

    # 1. Les crises en cours où l'institution est acteur VALIDÉ. `end_date__isnull=True` :
    #    une crise close ne doit plus rien ouvrir, l'acceptation ne valant que pour elle.
    implications = (
        ImplicationInstitution.objects
        .filter(
            institution=institution,
            type_implication=TypeImplication.ACTEUR,
            statut=StatutImplication.VALIDEE,
            actif=True,
            crise__end_date__isnull=True,
        )
        .values_list("communes", "crise__zone_communes", "crise__zone_departements")
    )
    for communes, zone_communes, zone_departements in implications:
        if communes:
            zones.update(("commune", c) for c in communes if c)
            continue
        # Liste vide = toute la crise. On prend sa zone telle qu'elle est déclarée, départements
        # compris : une crise déclarée au département ne nomme pas ses communes une par une.
        zones.update(("commune", c) for c in (zone_communes or []) if c)
        zones.update(("departement", d) for d in (zone_departements or []) if d)

    # 2. Les conventions actives, indépendantes de toute crise.
    delegations = (
        DelegationCompetence.objects
        .filter(institution_cible=institution, active=True)
        .filter(Q(date_fin__isnull=True) | Q(date_fin__gt=maintenant))
        .values_list("communes", "departements")
    )
    for communes, departements in delegations:
        zones.update(("commune", c) for c in (communes or []) if c)
        zones.update(("departement", d) for d in (departements or []) if d)

    return sorted(zones)


def viewer_perimetre(request):
    """Toutes les zones que l'appelant a le droit de voir, ou None s'il n'en a aucune.

    C'est la généralisation qui a motivé la refonte du 28/10/2026 : jusque-là un spectateur
    avait UNE zone `(niveau, code)`, ce qui convient à une mairie mais pas à une association
    agréée, dont le territoire est par nature un ENSEMBLE de communes variable selon les crises
    où elle est acceptée. Une institution sans commune propre obtenait donc `.none()` partout —
    aucun dossier, tableau de bord vide — quelle que soit la crise sur laquelle elle
    intervenait.

    Pour une mairie sans rien d'accordé, la liste contient sa seule zone et le filtrage est
    exactement celui d'avant. `None` (et non une liste vide) continue de signifier « aucune
    zone résolvable », pour que les appelants gardent leur repli actuel."""
    return _memo(request, 'perimetre', lambda: _calculer_perimetre(request))


def _calculer_perimetre(request):
    """Le calcul nu, sans mémoire — voir viewer_perimetre."""
    zones = []
    propre = viewer_zone_code(request)
    if propre is not None:
        if propre[0] == "national":
            # Inutile d'aller plus loin : rien n'élargit le national.
            return [propre]
        zones.append(propre)
    zones.extend(z for z in communes_accordees(request) if z not in zones)
    return zones or None


ECHELLE_ORDER = ["commune", "epci", "departement", "region", "national"]


def widen_zone_from_request(request):
    """Zone de l'appelant, élargie par ?echelle= (jamais rétrécie). None si non résolvable :
    l'appelant choisit le repli."""
    natural = viewer_zone_code(request)
    if natural is None:
        return None
    echelle = _parametre(request, 'echelle')
    if not echelle or echelle not in ECHELLE_ORDER:
        return natural
    if ECHELLE_ORDER.index(echelle) <= ECHELLE_ORDER.index(natural[0]):
        return natural
    if echelle == "national":
        return ("national", None)
    institution = request.user.institution
    code = getattr(institution, f"{echelle}_code", None)
    return (echelle, code) if code else natural


def object_in_viewer_zone(request, obj, champ_par_niveau=SECTEUR_CHAMP_PAR_NIVEAU):
    """True si obj est dans l'UNE des zones de l'appelant (toujours pour un administrateur ou
    le niveau national, jamais si aucune zone n'est résolvable).

    Doit suivre exactement la même règle que filter_queryset_to_viewer_zone : un objet visible
    dans une liste et refusé à l'unité, ou l'inverse, serait incompréhensible à l'usage et
    constituerait une faille dès que la seconde est plus permissive que la première."""
    if effective_role_or_none(request) == UserRole.ADMINISTRATOR:
        return True
    perimetre = viewer_perimetre(request)
    if perimetre is None:
        return False
    for niveau, code in perimetre:
        if niveau == "national":
            return True
        champ = champ_par_niveau.get(niveau)
        if champ and getattr(obj, champ, None) == code:
            return True
    return False


def object_in_viewer_zone_via_commune(request, obj, commune_field="commune_code"):
    """object_in_viewer_zone pour un modèle qui n'a que commune_code (Information) : les
    niveaux supérieurs sont résolus via le référentiel Commune."""
    if effective_role_or_none(request) == UserRole.ADMINISTRATOR:
        return True
    perimetre = viewer_perimetre(request)
    if perimetre is None:
        return False
    commune_code = getattr(obj, commune_field, None)
    niveaux_superieurs = []
    for niveau, code in perimetre:
        if niveau == "national":
            return True
        if not commune_code:
            continue
        if niveau == "commune":
            if commune_code == code:
                return True
            continue
        champ_commune = SECTEUR_CHAMP_PAR_NIVEAU.get(niveau)
        if champ_commune:
            niveaux_superieurs.append(Q(**{champ_commune: code}))
    if not commune_code or not niveaux_superieurs:
        return False
    # Une seule requête pour tous les niveaux supérieurs restants, au lieu d'une par zone : le
    # périmètre d'une association conventionnée peut en compter plusieurs dizaines.
    from .models import Commune
    combine = niveaux_superieurs[0]
    for q in niveaux_superieurs[1:]:
        combine |= q
    return Commune.objects.filter(combine, code=commune_code).exists()


def apply_zone(queryset, zone, resolver=None, champ_par_niveau=SECTEUR_CHAMP_PAR_NIVEAU):
    """Filtre queryset sur une zone (niveau, code) déjà résolue."""
    niveau, code = zone
    if niveau == "national":
        return queryset
    if resolver is not None:
        return queryset.filter(resolver(niveau, code))
    champ = champ_par_niveau.get(niveau)
    if not champ:
        return queryset.none()
    return queryset.filter(**{champ: code})


def _q_pour_zone(zone, resolver=None, champ_par_niveau=SECTEUR_CHAMP_PAR_NIVEAU):
    """Le Q d'UNE zone, ou None quand elle ne se traduit pas en filtre.

    `None` et « filtre vide » sont deux choses différentes et les confondre serait une faille :
    une zone nationale ne se filtre pas parce qu'elle contient tout, une zone dont le niveau
    n'a pas de colonne ne se filtre pas parce qu'on ne sait pas la restreindre. La première
    doit tout laisser passer, la seconde ne rien laisser passer. L'appelant tranche."""
    niveau, code = zone
    if niveau == "national":
        return "tout"
    if resolver is not None:
        return resolver(niveau, code)
    champ = champ_par_niveau.get(niveau)
    if not champ:
        return None
    return Q(**{champ: code})


def apply_perimetre(queryset, perimetre, resolver=None, champ_par_niveau=SECTEUR_CHAMP_PAR_NIVEAU):
    """Filtre queryset sur un ENSEMBLE de zones déjà résolues, en les réunissant.

    Une zone nationale dans le lot rend le filtre inutile : elle contient les autres. Une zone
    intraduisible est ignorée plutôt que de vider tout le périmètre — sinon une convention
    portant un niveau exotique fermerait aussi l'accès à la commune de l'institution, qui n'a
    rien à voir. Si AUCUNE zone n'est traduisible, on ne rend rien : c'est le cas « je ne sais
    pas restreindre », et il ne doit jamais devenir « je laisse tout passer »."""
    filtres = []
    for zone in perimetre:
        q = _q_pour_zone(zone, resolver=resolver, champ_par_niveau=champ_par_niveau)
        if q == "tout":
            return queryset
        if q is not None:
            filtres.append(q)
    if not filtres:
        return queryset.none()
    combine = filtres[0]
    for q in filtres[1:]:
        combine |= q
    # Pas de distinct() ici, et c'est délibéré. Réunir des Q dans UN seul .filter() produit une
    # seule requête avec un OR : sur une colonne, aucune ligne n'est dupliquée. Seul un
    # resolver qui traverse une relation multiple peut dupliquer, et les deux appelants
    # concernés (DossierViewSet, DeclarationSecuriteViewSet) posent déjà leur propre
    # distinct(). L'ajouter ici le rendrait surtout impossible à UNIR avec un autre queryset :
    # Django refuse « Cannot combine a unique query with a non-unique query » — ce qui cassait
    # la liste des déclarations de sécurité, où la zone est unie aux déclarations de l'auteur.
    return queryset.filter(combine)


def filter_queryset_to_viewer_zone(request, queryset, resolver=None, champ_par_niveau=SECTEUR_CHAMP_PAR_NIVEAU):
    """Réduit queryset à TOUT ce que l'appelant a le droit de voir ; vide si rien n'est
    résolvable. resolver(niveau, code) -> Q pour une ressource sans code géographique propre
    (ex : Team).

    Depuis le 28/10/2026, le périmètre peut contenir plusieurs zones (voir viewer_perimetre) :
    la zone propre de l'institution, plus les communes qu'une crise ou une convention lui a
    accordées. Pour une mairie sans rien d'accordé, c'est le comportement d'avant à
    l'identique."""
    if effective_role_or_none(request) == UserRole.ADMINISTRATOR:
        return queryset
    perimetre = viewer_perimetre(request)
    if perimetre is None:
        return queryset.none()
    return apply_perimetre(queryset, perimetre, resolver=resolver, champ_par_niveau=champ_par_niveau)


def communes_delegables(request, crise) -> list:
    """Communes de `crise` que l'appelant a le droit d'accorder à une autre institution.

    Règle posée par Sylvain le 28/10/2026 : **« je ne donne pas les droits sur une commune sur
    laquelle je n'ai pas les droits »**. Un conseil départemental, dont le périmètre couvre
    toute la crise, peut donc l'accorder en entier ; une commune ne peut accorder qu'elle-même.

    C'est l'intersection de la zone de la crise et du périmètre du donneur — le même résolveur
    gouverne ainsi la lecture ET la délégation, ce qui garantit qu'ils ne peuvent pas diverger.
    Un administrateur n'est pas exempté : il n'est pas responsable de traitement et n'a pas de
    territoire à accorder (voir BASE-LEGALE-REGISTRE-VULNERABLES.md § 5 pour le même principe
    appliqué au registre).

    Rend des dictionnaires {code, nom} triés par nom : la liste alimente des cases à cocher, et
    un code INSEE nu n'est pas lisible."""
    de_la_crise = [c for c in (crise.zone_communes or []) if c]
    if not de_la_crise:
        return []

    perimetre = viewer_perimetre(request)
    if perimetre is None:
        return []

    autorisees = set()
    departements = []
    for niveau, code in perimetre:
        if niveau == "national":
            autorisees.update(de_la_crise)
            break
        if niveau == "commune":
            autorisees.add(code)
        else:
            champ = SECTEUR_CHAMP_PAR_NIVEAU.get(niveau)
            if champ:
                departements.append((champ, code))

    if departements:
        # Une seule requête pour tous les niveaux supérieurs, restreinte aux communes de la
        # crise : on ne déplie jamais un département entier, seulement ce que la crise touche.
        from .models import Commune
        filtre = Q(**{departements[0][0]: departements[0][1]})
        for champ, code in departements[1:]:
            filtre |= Q(**{champ: code})
        autorisees.update(
            Commune.objects.filter(filtre, code__in=de_la_crise).values_list("code", flat=True)
        )

    return _nommer(autorisees & set(de_la_crise))
