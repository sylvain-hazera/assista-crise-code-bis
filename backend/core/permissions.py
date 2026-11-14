"""Permissions DRF réutilisables liées au type de compte (User.type)."""
import hashlib

from django.db.models import Q
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import BasePermission

from .models import Environment, UserRole

INSTITUTIONAL_TYPES = {
    UserRole.LOCAL_AUTHORITY,
    UserRole.ORGANIZED_RESCUE,
    UserRole.ADMINISTRATOR,
    UserRole.REGULATEUR,
}


class DenyInDemo(BasePermission):
    """Refuse toute action en zone DEMO — pour les écritures sur des ressources dont la
    configuration/affectation ne doit jamais être modifiable depuis la démo (ex: companion/
    nœud personnel MeshCore, voir CompagnonMeshCoreViewSet/NoeudMeshUtilisateurViewSet,
    demande explicite du 14/09). La LECTURE (list/retrieve) de ces mêmes ressources reste
    volontairement possible mais masquée au niveau du serializer (même principe que
    UserSerializer.to_representation pour email/téléphone) : jamais cette permission sur
    list/retrieve, qui doivent continuer à alimenter la carte et la messagerie en démo."""
    message = "Indisponible depuis la zone de démonstration."

    def has_permission(self, request, view):
        return get_active_environment(request) != Environment.DEMO


def get_active_environment(request):
    """Zone active de la requête (PROD par défaut), choisie par le frontend via l'en-tête
    X-Environment (bascule "kill switch"). Cette valeur ne fait que sélectionner laquelle de
    deux configurations déjà décidées par un admin (type/demo_role) s'applique — elle ne peut
    jamais accorder plus de droits que ce que l'admin a explicitement réglé pour cet
    utilisateur, et sert aussi de filtre sur les données (voir EnvironmentScopedViewSetMixin
    dans views.py), donc pas de scénario où on "prétend" un environnement pour lire les
    données d'un autre."""
    value = request.META.get("HTTP_X_ENVIRONMENT", Environment.PROD)
    if value not in (Environment.PROD, Environment.DEMO):
        raise ValidationError({"environment": "Environnement invalide (PROD ou DEMO attendu)."})
    return value


def send_mail_env_aware(request, subject, message, from_email, recipient_list, **kwargs):
    """Enveloppe django.core.mail.send_mail pour les notifications opérationnelles
    (affectation, confirmation de création...) : en zone DEMO, redirige systématiquement vers
    l'utilisateur connecté à l'origine de l'action plutôt que vers le destinataire enregistré
    (souvent fictif/de repli en démo, ex: contact anonyme du formulaire "Autre information") —
    pour que les comptes de démonstration voient concrètement ce que l'appli aurait envoyé,
    sans jamais spammer une adresse tierce. Sans effet en PROD. Ne concerne pas les emails de
    cycle de vie de compte (inscription, activation, validation) : structurellement propres à
    PROD, la démo ne crée jamais de compte."""
    from .audit import send_mail_logged

    if get_active_environment(request) == Environment.DEMO and getattr(request.user, "is_authenticated", False):
        recipient_list = [request.user.email]
        subject = f"[DEMO] {subject}"
    return send_mail_logged(request, subject, message, from_email, recipient_list, **kwargs)


def get_effective_role(request):
    """Rôle appliqué pour CETTE requête : `user.type` en PROD, `user.demo_role` en DEMO.
    À utiliser à la place de tout accès direct à `request.user.type` dans les contrôles de
    permission, pour que la bascule démo/prod soit respectée uniformément partout."""
    if get_active_environment(request) == Environment.DEMO:
        if not request.user.demo_role:
            raise PermissionDenied("Vous n'avez pas accès à la zone de démonstration.")
        return request.user.demo_role
    return request.user.type


def effective_role_or_none(request):
    """Variante non-bloquante de get_effective_role, pour les vérifications de visibilité
    "douces" (ex: masquer un champ de localisation) qui ne doivent jamais faire échouer toute
    une réponse à cause d'un client qui prétend être en DEMO sans y avoir droit — contrairement
    à un vrai contrôle de permission, où l'échec explicite (403) est voulu."""
    try:
        return get_effective_role(request)
    except PermissionDenied:
        return None


def is_regulateur_aut_locale_de_la_crise(request, crise) -> bool:
    """L'utilisateur courant est-il un compte AUT_LOCALE (rôle effectif, prod/démo) rattaché à
    une institution elle-même impliquée (validée, active) sur `crise` ? — condition
    d'autorisation pour valider/refuser une déclaration ACTEUR en attente d'une institution
    tierce (ImplicationInstitutionViewSet.valider/refuser), et pour piloter l'affichage des
    boutons correspondants côté ImplicationInstitutionSerializer.peut_valider. Défini ici (et
    pas dans serializers.py/views.py) pour être appelable depuis les deux sans import
    circulaire — même raison que _peut_gerer_stock_point."""
    if not request.user or not request.user.is_authenticated:
        return False
    role = effective_role_or_none(request)
    # L'administrateur aussi (oubli constaté le 22/10/2026 en démo sur la cellule de crise :
    # bouton Valider refusé en 403 pour un compte ADMIN), comme partout ailleurs dans l'appli.
    if role == UserRole.ADMINISTRATOR:
        return True
    if role != UserRole.LOCAL_AUTHORITY:
        return False

    # ContactInstitution (rattachement institutionnel), pas User.institution (FK direct
    # distinct, réservé à la "Vue Ma collectivité" — voir UserSerializer.get_ma_zone) : c'est
    # ContactInstitution que ImplicationInstitutionViewSet utilise déjà partout ailleurs
    # (perform_create/_can_manage) pour déterminer "l'institution de l'appelant".
    from .models import ContactInstitution, ImplicationInstitution, StatutImplication

    institution_ids = ContactInstitution.objects.filter(
        utilisateur=request.user, actif=True,
    ).values_list('institution_id', flat=True)
    return ImplicationInstitution.objects.filter(
        crise=crise, institution_id__in=institution_ids, statut=StatutImplication.VALIDEE, actif=True,
    ).exists()


class IsInstitutionalActor(BasePermission):
    """Autorise les comptes institutionnels (autorité locale, secours organisés, admin) —
    au sens du rôle EFFECTIF de la requête (prod ou démo selon la bascule active)."""

    message = "Cette action est réservée aux acteurs institutionnels."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and get_effective_role(request) in INSTITUTIONAL_TYPES
        )


class IsOwnerOrInstitutional(BasePermission):
    """Autorise l'auteur (compte lié, `obj.author`) d'un contenu public à le modifier ou le
    supprimer lui-même, en plus des acteurs institutionnels. Offer/Request/Information sont en
    `permission_classes = [AllowAny]` pour permettre la création publique (y compris anonyme) —
    sans `get_permissions()` dédié pour update/partial_update/destroy, cette même permission
    s'appliquait à CES actions aussi : n'importe qui, même anonyme, pouvait modifier ou
    supprimer le contenu de n'importe qui d'autre (vérifié en le reproduisant). La suppression
    anonyme reste possible par ailleurs via le lien à jeton envoyé par email
    (delete-offer/delete-request/delete-information), qui ne passe pas par ce ViewSet."""

    message = "Vous ne pouvez modifier ou supprimer que votre propre contenu."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if IsInstitutionalActor().has_permission(request, view):
            return True
        return obj.author_id == request.user.id


class IsOfferOwnerOrInstitutional(BasePermission):
    """Même principe que IsOwnerOrInstitutional, pour les objets qui n'ont pas d'auteur direct
    mais dépendent d'une Offer (ex: DisponibiliteOffre) — l'auteur de l'offre parente fait
    autorité. DisponibiliteOffreViewSet était en `permission_classes = [AllowAny]` sur toute la
    classe, sans aucune restriction : n'importe qui, même anonyme, pouvait créer/modifier/
    supprimer les créneaux de disponibilité de n'importe quel bénévole sur n'importe quelle
    offre (vérifié en le reproduisant)."""

    message = "Vous ne pouvez modifier ou supprimer que les disponibilités de votre propre offre."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if IsInstitutionalActor().has_permission(request, view):
            return True
        return obj.offer.author_id == request.user.id


class IsInstitutionMemberOrAdministrator(BasePermission):
    """Seul un membre actif de CETTE institution précise (ContactInstitution), ou un
    administrateur plateforme, peut la modifier — contrairement à IsInstitutionalActor
    (n'importe quel acteur institutionnel, de n'importe quelle institution), qui laissait
    n'importe quel compte authentifié institutionnel éditer l'institution de quelqu'un d'autre
    (InstitutionViewSet n'avait aucune restriction de permission sur update/partial_update)."""

    message = "Seul un membre de cette institution peut la modifier."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if get_effective_role(request) == UserRole.ADMINISTRATOR:
            return True
        from .models import ContactInstitution
        return ContactInstitution.objects.filter(
            institution=obj, utilisateur=request.user, actif=True,
            environment=get_active_environment(request),
        ).exists()


class IsSelfOrInstitutional(BasePermission):
    """Pour UserViewSet : un compte ne peut modifier/supprimer que lui-même, en plus des
    acteurs institutionnels — sans permission dédiée, UserViewSet (permission par défaut
    IsAuthenticated, aucun get_permissions()) laissait n'importe quel compte authentifié
    modifier ou supprimer le compte de n'importe qui d'autre par son UUID (vérifié en le
    reproduisant)."""

    message = "Vous ne pouvez modifier ou supprimer que votre propre compte."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if IsInstitutionalActor().has_permission(request, view):
            return True
        return obj.pk == request.user.pk


class IsOwnDeclarationOrInstitutional(BasePermission):
    """Autorise l'auteur d'une déclaration de sécurité ("je suis en sécurité") à modifier sa
    propre situation (arrivée/départ d'un centre d'accueil, relogement...), en plus des
    acteurs institutionnels qui peuvent modifier n'importe quelle déclaration."""

    message = "Vous ne pouvez modifier que vos propres déclarations."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if IsInstitutionalActor().has_permission(request, view):
            return True
        return obj.declare_par_id == request.user.id


class IsAdministrator(BasePermission):
    """Autorise uniquement les comptes administrateur, au sens du rôle effectif de la requête."""

    message = "Cette action est réservée aux administrateurs."

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and get_effective_role(request) == UserRole.ADMINISTRATOR
        )


class PeutAgirPourCompagnon(BasePermission):
    """Écrire dans la file d'un companion radio, ou la lire.

    **Ferme un trou préexistant**, constaté le 13/11/2026 : `MessageMeshLogViewSet` accordait
    `create`, `partial_update` et `a-envoyer` à `IsAuthenticated` seul, en supposant dans un
    commentaire que l'appelant était « un compte de service, pas un acteur institutionnel
    humain » — sans jamais le vérifier. Conséquences concrètes :

    - `/messages-meshcore/a-envoyer/` **sans paramètre `compagnon`** rendait la file sortante
      de TOUS les companions de la plateforme, à tout compte inscrit — contenu des messages
      compris ;
    - n'importe qui pouvait déposer un **faux message entrant** attribué à une radio.

    Trois familles d'appelants légitimes :

    1. le **compte de service d'un pont** ou d'un satellite approuvé, comme aujourd'hui — c'est
       lui qui tient la radio dans le cas nominal ;
    2. un **relais navigateur** avec une session vivante sur CE companion (voir
       `core/relais_navigateur.py`) : le poste verrouillé où l'on ne peut rien installer ;
    3. un **administrateur au sens du rôle RÉEL**, pour le diagnostic. Jamais le rôle effectif :
       un `demo_role=ADMIN` prêté pour une démonstration ne donne pas la main sur une radio
       réelle — même raisonnement que `EstComptePont`.

    **Le companion doit être nommé.** Une requête qui n'en désigne aucun est refusée aux
    appelants de la famille 2 : c'est précisément la forme qui faisait fuiter toutes les files.
    Les comptes de service, eux, interrogent parfois sans filtre et gardent ce droit.

    **Ne s'applique PAS à la création d'un message sortant**, et la nuance a coûté 15 tests le
    13/11/2026 : un message SORTANT est écrit par un HUMAIN — le régulateur qui compose dans le
    chat radio — et déposé en file pour que le pont l'émette plus tard. Seuls sont des gestes
    de passerelle : déposer un message ENTRANT (ce que la radio a entendu), lire la file
    sortante, et marquer un envoi abouti ou échoué. Voir `PeutEcrireMessageMesh`.
    """

    message = ("Vous ne pouvez agir que pour une radio dont vous relayez activement la "
               "liaison, ou avec un compte de service de passerelle.")

    def has_permission(self, request, view):
        from .models import CompagnonMeshCore
        from .relais_navigateur import session_active

        utilisateur = request.user
        if not getattr(utilisateur, "is_authenticated", False):
            return False

        # 1. Compte de service d'un pont / satellite, et 3. administrateur réel : inchangé.
        if getattr(utilisateur, "compte_service_pont", False):
            return True
        if getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR:
            return True
        # Import tardif : models importe permissions indirectement par ailleurs. Même
        # vérification que EstComptePont — un satellite approuvé tient une radio.
        from .models import Satellite, StatutEnrolementSatellite
        if Satellite.objects.filter(
                compte_service=utilisateur,
                statut_enrolement=StatutEnrolementSatellite.APPROUVE).exists():
            return True

        # 2. Relais navigateur : le companion doit être nommé, et la session vivante.
        compagnon_id = (request.data.get("compagnon") if hasattr(request, "data") else None) \
            or request.query_params.get("compagnon")
        if not compagnon_id:
            return False
        if not CompagnonMeshCore.objects.filter(pk=compagnon_id).exists():
            return False
        return session_active(utilisateur, compagnon_id) is not None


class PeutEcrireMessageMesh(BasePermission):
    """Créer un message mesh : la règle dépend de la DIRECTION, pas de l'action.

    Distinction apprise de force le 13/11/2026, après avoir bloqué le chat radio en serrant la
    vis sur l'ensemble de `create` :

    - **SORTANT** : un humain compose. C'est le régulateur qui écrit « rentrez à la base » dans
      le chat ; le message part en file et le pont l'émettra. Droit d'acteur institutionnel,
      comme avant.
    - **ENTRANT** : c'est un geste de passerelle — on dépose ce que la radio a entendu. Droit
      réservé à qui tient la radio (voir `PeutAgirPourCompagnon`), sans quoi n'importe qui
      fabrique un faux message attribué à un intervenant de terrain.

    Serrer les deux de la même façon casse le chat ; les laisser ouverts tous les deux laisse
    fabriquer de faux messages. Il fallait les séparer.
    """

    message = PeutAgirPourCompagnon.message

    def has_permission(self, request, view):
        from .models import DirectionMessageMesh

        direction = (request.data.get("direction") if hasattr(request, "data") else None) or ""
        if direction == DirectionMessageMesh.ENTRANT:
            return PeutAgirPourCompagnon().has_permission(request, view)
        return IsInstitutionalActor().has_permission(request, view)


class EstComptePont(BasePermission):
    """Lecture des endpoints qui exposent un SECRET mesh en clair.

    Ces endpoints existent parce qu'un pont radio ne peut pas faire autrement : il lui faut le
    mot de passe MQTT du broker, la clé privée X25519 du companion et les PSK de canal pour
    parler le protocole (voir meshtastic-bridge/crypto.py). Mais jusqu'au 07/11/2026 ils se
    contentaient de `IsAuthenticated` : **n'importe quel compte citoyen inscrit pouvait lire ces
    secrets**, donc se faire passer pour une passerelle de l'institution et déchiffrer son
    trafic radio.

    Trois familles d'appelants légitimes, et pas une de plus :

    1. le compte de service d'un pont, marqué explicitement (`User.compte_service_pont`, posé
       par `manage.py marquer_compte_pont`) ;
    2. le compte de service d'un satellite APPROUVÉ — son pont local lit les mêmes endpoints ;
    3. un administrateur au sens du rôle **RÉEL**, pour le diagnostic. Pas le rôle effectif : un
       `demo_role=ADMIN` prêté le temps d'une démonstration ne doit pas donner les clés du
       réseau radio réel, même raisonnement que core/grafana.py:IsAdministrator.

    Le marquage est volontairement manuel et hors API : un compte qui peut lire tous les secrets
    radio ne doit pas pouvoir être fabriqué par une requête HTTP."""

    message = (
        "Cet endpoint expose des secrets radio : il est réservé aux comptes de service des "
        "ponts (manage.py marquer_compte_pont <email>), aux satellites approuvés et aux "
        "administrateurs."
    )

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        if getattr(user, 'compte_service_pont', False):
            return True
        # Rôle RÉEL, pas le rôle effectif : voir la docstring.
        if user.type == UserRole.ADMINISTRATOR:
            return True
        # Import tardif : models importe permissions indirectement par ailleurs.
        from .models import Satellite, StatutEnrolementSatellite
        return Satellite.objects.filter(
            compte_service=user, statut_enrolement=StatutEnrolementSatellite.APPROUVE,
        ).exists()


def _peut_gerer_stock_point(request, point) -> bool:
    """Admin, responsable du point (champ `responsable` singulier — pas le M2M `responsables`,
    même limite que le contrôle d'origine), ou chef/membre de son équipe. Utilisé à la fois
    pour l'autorisation réelle (RegistrePresenceViewSet, ContributionMaterielViewSet,
    MaterielPointViewSet dans views.py) et pour le champ calculé `peut_gerer` exposé par
    PointOperationnelSerializer, afin que les boutons Secrétariat/Stock du frontend reflètent
    exactement les mêmes droits que ceux réellement appliqués par l'API."""
    user = request.user
    if get_effective_role(request) == UserRole.ADMINISTRATOR:
        return True
    if point.responsable_id == user.id:
        return True
    if point.equipe:
        if point.equipe.leader_id == user.id:
            return True
        if point.equipe.members.filter(id=user.id).exists():
            return True
    return False


def mask_email(value):
    """Email factice mais stable (la même vraie adresse donne toujours le même masque), pour
    ne jamais exposer une vraie adresse pendant une démonstration en zone DEMO."""
    if not value:
        return value
    digest = hashlib.sha256(value.encode()).hexdigest()[:10]
    return f"{digest}@zone.demo"


def mask_phone(value):
    """Numéro factice mais stable, au format +33 x xx xx xx xx — même principe que mask_email."""
    if not value:
        return value
    digest = "".join(c for c in hashlib.sha256(value.encode()).hexdigest() if c.isdigit())
    digits = (digest + "0123456789")[:9]
    return f"+33 {digits[0]} {digits[1:3]} {digits[3:5]} {digits[5:7]} {digits[7:9]}"


# Prénoms neutres et courants : un pseudonyme doit rester lisible dans un tableau et dans une
# conversation pendant une démonstration. Le patronyme, lui, est toujours « Démo-XXXX » : on ne
# fabrique PAS un faux nom de famille crédible, qui pourrait être pris pour une vraie personne
# (voire coïncider avec l'une).
PRENOMS_DEMO = (
    "Alex", "Camille", "Charlie", "Claude", "Dominique", "Eden", "Gabriel", "Jules",
    "Lou", "Louise", "Maé", "Marie", "Max", "Morgan", "Noa", "Pascal",
    "Robin", "Sacha", "Sam", "Solal", "Swann", "Thomas", "Yaël", "Zoé",
)


def pseudonyme(user):
    """(prénom, patronyme) factices mais STABLES pour un utilisateur donné.

    Stable, parce qu'une démonstration doit rester cohérente : la même personne doit porter le
    même pseudonyme d'une page à l'autre et d'une session à l'autre, sinon on ne peut pas suivre
    un scénario (« c'est bien le même chef d'équipe que sur l'écran précédent ? »).

    Dérivé de l'identifiant, pas du nom : deux homonymes restent distincts, et le pseudonyme ne
    permet pas de remonter au nom réel."""
    graine = str(getattr(user, 'id', None) or getattr(user, 'username', '') or '')
    digest = hashlib.sha256(graine.encode()).hexdigest()
    prenom = PRENOMS_DEMO[int(digest[:4], 16) % len(PRENOMS_DEMO)]
    return prenom, f"Démo-{digest[4:8].upper()}"


def est_son_propre_compte(request, user):
    """Vrai si `user` est l'appelant — seul cas où ses données personnelles restent en clair en
    zone DEMO (voir nom_affichable)."""
    appelant = getattr(request, 'user', None) if request is not None else None
    return bool(
        appelant is not None and getattr(appelant, 'id', None)
        and appelant.id == getattr(user, 'id', None)
    )


def nom_affichable(user, request=None):
    """Nom lisible d'un utilisateur **pour l'affichage**, pseudonymisé en zone DEMO.

    Point de passage unique, ajouté le 07/11/2026. Il y avait jusque-là une soixantaine de
    `f"{u.first_name} {u.last_name}"` dispersés dans `serializers.py` et `views.py`, et **aucun**
    ne masquait quoi que ce soit : la zone de démonstration affichait donc les noms des vraies
    personnes de la production. `User` est en effet partagé entre les deux zones (un seul compte,
    un `demo_role`), contrairement à tout le contenu, qui est cloisonné par
    `EnvironmentScopedModel`. Les adresses et téléphones étaient déjà masqués (`mask_email`,
    `mask_phone`) — les noms, non.

    **Jamais pour le contenu d'un email.** Un message envoyé à une vraie personne doit porter son
    vrai nom : les `send_mail` de `views.py` lisent volontairement `first_name`/`last_name` en
    direct, et ne doivent pas passer par ici.

    **L'utilisateur voit toujours son propre nom en clair.** Se masquer à soi-même ne protège
    personne et rend la démonstration incompréhensible (« qui suis-je ? »).

    **Aucun repli sur l'email ou l'identifiant**, volontairement : la fonction remplace
    exactement `f"{u.first_name} {u.last_name}".strip()` et rend donc une chaîne VIDE pour un
    compte sans nom. Les appelants gardent ainsi leur propre repli (`or u.email`), inchangé en
    production — et en zone DEMO le pseudonyme est toujours non vide, donc ce repli ne s'applique
    jamais et aucune adresse ne fuit par ce chemin. Un repli interne aurait fait apparaître des
    emails là où le code renvoyait délibérément None."""
    if user is None:
        return None
    reel = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()
    if request is None or get_active_environment(request) != Environment.DEMO:
        return reel
    if est_son_propre_compte(request, user):
        return reel

    prenom, patronyme = pseudonyme(user)
    return f"{prenom} {patronyme}"


def strip_masked_fields_in_demo(request, validated_data, fields):
    """Retire `fields` de `validated_data` en zone DEMO — un formulaire d'édition affiche la
    version masquée (mask_email/mask_phone, voir to_representation des serializers concernés)
    et la renvoie telle quelle au save, même si un tout autre champ a changé : sans ce garde-
    fou, éditer une fiche en DEMO écrase silencieusement une vraie adresse email/téléphone par
    son masque affiché. Reproduit et corrigé en direct (comptes GRUISSAN/NICOLAS sur .114,
    voir UserSerializer.update) puis généralisé à Request/Offer/Information, qui suivent le
    même schéma de masquage."""
    if request is not None and get_active_environment(request) == Environment.DEMO:
        for field in fields:
            validated_data.pop(field, None)
    return validated_data


def user_can_view_photo(request, obj, *, author_field='author', teams_field=None, dossiers_field=None):
    """Détermine si l'utilisateur de `request` peut voir la photo d'un objet (Crisis/Offer/
    Request/Information/RecherchePersonne) : l'auteur, un acteur institutionnel (au sens du
    rôle effectif prod/démo), un membre d'une équipe affectée à l'objet, ou un participant
    d'un dossier lié à l'objet."""
    user = request.user
    if not user or not user.is_authenticated:
        return False

    if effective_role_or_none(request) in INSTITUTIONAL_TYPES:
        return True

    author = getattr(obj, author_field, None)
    if author and author == user:
        return True

    if teams_field and getattr(obj, teams_field).filter(
        Q(members=user) | Q(leader=user)
    ).exists():
        return True

    if dossiers_field and getattr(obj, dossiers_field).filter(
        participants__utilisateur=user
    ).exists():
        return True

    return False


class PeutAccederRadio(BasePermission):
    """Accès au domaine radio : un acteur institutionnel, ou un opérateur radio.

    Remplace `IsInstitutionalActor` sur les endpoints radio, et c'est un ÉLARGISSEMENT, pas un
    verrou : le propriétaire d'un nœud personnel n'a aucune raison d'être institutionnel pour
    lire l'état du réseau sur lequel son matériel émet, régler ce matériel et simuler une
    couverture. C'était jusqu'au 10/11/2026 la seule chose qui lui manquait.

    Le filtrage de ce que chacun VOIT reste celui des endpoints (zone, institution, secrets
    réservés aux ponts par EstComptePont). Cette permission ne dit que « cette personne a
    affaire au domaine radio »."""

    message = (
        "Le domaine radio est réservé aux acteurs institutionnels et aux opérateurs radio "
        "(voir /admin/radio pour demander le droit)."
    )

    def has_permission(self, request, view):
        from .acces_radio import a_acces_radio

        user = request.user
        if not (user and user.is_authenticated):
            return False
        if get_effective_role(request) in INSTITUTIONAL_TYPES:
            return True
        return a_acces_radio(user)
