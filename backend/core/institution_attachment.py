"""Rattachement automatique d'un utilisateur à une institution (contact + rôle opérationnel).

Ces fonctions ne doivent JAMAIS être appelées avant que la possession de la boîte mail de
l'utilisateur ait été prouvée (clic sur le lien d'activation) : rattacher un compte à une
institution réelle sur la seule foi d'un email non vérifié permettrait à quiconque de se faire
passer pour un employé d'une institution (ex: une mairie, un SDIS) sans jamais recevoir ni
cliquer sur aucun email.
"""
from .audit import audit_log, send_mail_logged
from .branding import branding_for_institution, send_branded_mail
from .auth_validation import InstitutionEmailValidator
from .crypto_fields import blind_index
from .matrix import MATRIX_SERVER_NAME
from .models import (
    AffectationRoleOperationnel,
    ContactInstitution,
    Environment,
    Institution,
    InstitutionDomaine,
    InstitutionType,
    RoleOperationnel,
    Team,
    User,
    UserRole,
)
from .permissions import get_active_environment


def get_or_create_institution_team(institution, request=None):
    """Équipe "de tête" de l'institution, nommée d'après elle (Team.name = institution.nom) --
    un seul tenant par institution : recherchée par institution+nom avant toute création,
    jamais dupliquée même si plusieurs membres se rattachent en parallèle. Demande
    utilisateur du 2026-10-08 : tout membre d'une institution doit se retrouver dans une
    équipe à son nom, pas seulement les personnes explicitement ajoutées via l'écran Équipes
    -- voir grant_institution_and_demo_access, qui appelle cette fonction pour CHAQUE
    rattachement."""
    team = Team.objects.filter(institution=institution, name=institution.nom).first()
    if team is not None:
        return team, False
    environment = get_active_environment(request) if request is not None else Environment.PROD
    team = Team.objects.create(name=institution.nom, institution=institution, environment=environment)
    if request is not None:
        audit_log(
            request=request, action_code="CREATION", objet_type="Team", objet_id=team.id,
            commentaire=f"Équipe « {institution.nom} » créée automatiquement pour l'institution",
        )
    return team, True


def _envoyer_email_acces_messagerie_equipe(user, team, request):
    """Email envoyé la première fois qu'un membre rejoint l'équipe de son institution :
    comment accéder à la messagerie de groupe (Element X + connexion SSO Assista-Crise, voir
    core/oidc.py -- aucun mot de passe Matrix séparé à retenir). Element X exige malgré tout de
    connaître l'adresse du serveur AVANT de pouvoir rediriger vers la connexion SSO : sans
    cette indication, un utilisateur qui ouvre l'app pour la première fois ne sait pas quoi
    saisir (constaté le 2026-10-08, demande explicite de l'ajouter). Jamais appelée avec
    request=None (voir grant_institution_and_demo_access) -- send_mail_logged/audit_log en
    ont besoin pour la main courante et la bascule démo.

    Branding (voir core/branding.py) : team.institution est TOUJOURS connue ici (voir
    get_or_create_institution_team, un FK non-nullable) -- seul le nom affiché dans le corps est
    personnalisé, pas l'infrastructure Matrix elle-même (un seul serveur partagé, pas un
    déploiement Matrix par partenaire, voir la mémoire de conception marque blanche)."""
    branding = branding_for_institution(team.institution)
    message = (
        f"Bonjour {user.first_name},\n\n"
        f"Vous avez été rattaché à l'équipe « {team.name} » sur {branding.nom_affichage}, qui dispose "
        "d'une messagerie de groupe intégrée.\n\n"
        "Pour y accéder depuis votre téléphone :\n\n"
        "1. Installez l'application Element X :\n"
        "   - Android : https://play.google.com/store/apps/details?id=io.element.android.x\n"
        "   - iPhone : https://apps.apple.com/us/app/element-x-secure-chat-call/id1631335820\n\n"
        "2. Au démarrage, choisissez \"Se connecter\", puis \"Je possède déjà un compte\", et "
        f"indiquez l'adresse de serveur suivante quand elle est demandée :\n{MATRIX_SERVER_NAME}\n\n"
        f"3. Vous serez redirigé vers la page de connexion {branding.nom_affichage} : connectez-vous avec "
        "votre compte habituel (les mêmes identifiants que sur la plateforme).\n\n"
        "{signature}"
    )
    try:
        send_branded_mail(
            request, team.institution,
            subject=f"Accès à la messagerie de l'équipe {team.name}",
            message=message,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception:
        pass


def find_institution_by_known_domain(user):
    """Trouve (sans rattacher personne) l'institution propriétaire du domaine email de
    l'utilisateur, si déjà connu (InstitutionDomaine, alimenté par une précédente confirmation
    de l'annuaire)."""
    domain = (user.email or '').rsplit('@', 1)[-1].strip().lower()
    if not domain:
        return None

    institution_domaine = InstitutionDomaine.objects.filter(
        domaine__iexact=domain, valide=True
    ).select_related('institution').first()
    if not institution_domaine:
        return None

    institution = institution_domaine.institution
    # Backfill : cette institution existait déjà (domaine mis en cache par un premier membre)
    # mais n'avait pas encore de commune renseignée — ce nouveau membre peut la compléter.
    if not institution.commune_code and user.pending_commune_code:
        institution.commune_code = user.pending_commune_code
        institution.commune_nom = user.pending_commune_name or ''
        institution.save(update_fields=['commune_code', 'commune_nom'])

    return institution


def find_or_create_institution_from_annuaire(user, annuaire_match, request=None):
    """Trouve/crée l'institution confirmée par l'annuaire officiel et met en cache son domaine
    (InstitutionDomaine), sans rattacher personne — l'institution elle-même est réelle et
    indépendante de qui s'y rattache ensuite, contrairement au ContactInstitution/rôle de CET
    utilisateur (voir attach_user_with_role, décidé explicitement après confirmation)."""
    domain = annuaire_match.get('domain')
    nom = annuaire_match.get('nom') or domain
    type_code = (annuaire_match.get('type_service_local') or 'autre').strip().lower() or 'autre'

    # Un type trouvé dans l'annuaire officiel des collectivités désigne un service public réel —
    # marqué public par défaut, sauf le repli 'autre' (annuaire muet sur le type, on ne sait pas).
    institution_type, _ = InstitutionType.objects.get_or_create(
        code=type_code,
        defaults={'libelle': type_code.title(), 'est_public': type_code != 'autre'},
    )

    institution, institution_created = Institution.objects.get_or_create(
        nom=nom,
        defaults={
            'type': institution_type, 'email': user.email, 'actif': True,
            'commune_code': user.pending_commune_code or '',
            'commune_nom': user.pending_commune_name or '',
        },
    )
    if institution_created and request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="Institution",
            objet_id=institution.id,
            commentaire=f"Création institution via annuaire officiel : {institution.nom}",
        )
    # Backfill pour une institution préexistante (créée avant l'ajout de ces champs, ou par un
    # premier membre sans commune déclarée) : get_or_create ne pose les defaults qu'à la création.
    if not institution_created and not institution.commune_code and user.pending_commune_code:
        institution.commune_code = user.pending_commune_code
        institution.commune_nom = user.pending_commune_name or ''
        institution.save(update_fields=['commune_code', 'commune_nom'])

    if domain:
        institution_domaine, domaine_created = InstitutionDomaine.objects.get_or_create(
            institution=institution,
            domaine=domain,
            defaults={'valide': True},
        )
        if domaine_created and request is not None:
            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="InstitutionDomaine",
                objet_id=institution_domaine.id,
                commentaire=f"Domaine '{domain}' confirmé via l'annuaire pour {institution.nom}",
            )

    return institution


def find_institution_for_pending_user(user, request=None):
    """Cherche l'institution correspondant aux informations déclarées à l'inscription
    (user.pending_institution_*) — cache de domaines connus, puis annuaire officiel si besoin.
    Ne rattache PAS l'utilisateur (aucun ContactInstitution/rôle créé ici) : c'est la personne,
    via un choix explicite après activation, qui confirme (voir attach_user_with_role) ou crée
    sa propre institution si rien n'est trouvé ici (voir UserViewSet.creer_mon_institution).
    Peut renvoyer None sans qu'aucune erreur ne se soit produite : signifie simplement "aucune
    correspondance", pas un échec de la recherche elle-même."""
    institution = find_institution_by_known_domain(user)

    if institution is None and user.pending_institution_name:
        valid, _message, details = InstitutionEmailValidator.validate_institution_account(
            email=user.email,
            institution_name=user.pending_institution_name or '',
            institution_type=user.pending_institution_type or '',
            commune_name=user.pending_commune_name or '',
            commune_code=user.pending_commune_code or '',
        )
        annuaire_match = (details or {}).get('annuaire') if valid else None
        if annuaire_match and annuaire_match.get('matched'):
            institution = find_or_create_institution_from_annuaire(user, annuaire_match, request)

    return institution


def grant_institution_and_demo_access(user, institution, request=None):
    """Pose User.institution (si pas déjà défini — ne bascule jamais le contexte "Vue Ma
    Collectivité" d'un compte déjà rattaché ailleurs, ex: un profil multi-institutions membre
    de plusieurs mairies) et accorde automatiquement le même rôle en zone DEMO (si aucun accès
    démo n'a déjà été réglé — manuellement ou par un rattachement précédent). Un compte
    institutionnel réel doit pouvoir essayer la démo sans dépendre d'un octroi manuel séparé par
    un administrateur (voir AuthService.canAccessDemo côté frontend).

    Ajoute aussi `user` à l'équipe "de tête" de l'institution (voir
    get_or_create_institution_team) et lui envoie, la toute première fois seulement, l'email
    d'accès à la messagerie d'équipe -- appelée par TOUS les chemins de rattachement
    (attach_user_with_role, attach_secours_user_to_institution, resolve_or_invite_responsable,
    import CSV personnel communal), donc point unique pour garantir qu'aucun membre
    d'institution n'y échappe. `request` volontairement optionnel (certains appelants
    historiques n'en avaient pas besoin) mais SANS request l'email n'est pas envoyé
    (send_mail_logged/audit_log en ont besoin) -- en pratique tous les appelants réels en
    disposent (actions de vue authentifiées ou import, jamais un script sans contexte)."""
    update_fields = []
    if user.institution_id is None:
        user.institution = institution
        update_fields.append('institution')
    if not user.demo_role:
        user.demo_role = user.type
        update_fields.append('demo_role')
    if update_fields:
        user.save(update_fields=update_fields)

    team, _ = get_or_create_institution_team(institution, request)
    if not team.members.filter(pk=user.pk).exists():
        team.members.add(user)
        if request is not None:
            audit_log(
                request=request, action_code="MODIFICATION", objet_type="Team", objet_id=team.id,
                commentaire=f"{user.email} ajouté à l'équipe « {team.name} » (rattachement institution)",
            )
            _envoyer_email_acces_messagerie_equipe(user, team, request)


def attach_user_with_role(user, institution, role_code, request=None, fonction='Membre', contact_principal=False):
    """Rattache explicitement l'utilisateur à `institution` avec le rôle qu'il a choisi — appelé
    une fois qu'il a confirmé lui-même la correspondance proposée par
    find_institution_for_pending_user (UserViewSet.confirmer_institution), ou juste après avoir
    créé sa propre institution (UserViewSet.creer_mon_institution — `fonction`/`contact_principal`
    ajustés dans ce cas pour refléter qu'il en est le créateur). Nettoie les pending_* dans tous
    les cas. Lève ValueError si `role_code` ne correspond à aucun RoleOperationnel connu (à
    l'appelant de traduire ça en 400)."""
    role = RoleOperationnel.objects.filter(code=role_code).first()
    if not role:
        raise ValueError(f"Rôle inconnu : {role_code}")

    contact, contact_created = _get_or_create_contact_institution(institution, user, fonction, contact_principal)
    if contact_created and request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="ContactInstitution",
            objet_id=contact.id,
            commentaire=f"Rattachement de {user.email} à l'institution {institution.nom} (confirmé par l'utilisateur)",
        )
    grant_institution_and_demo_access(user, institution, request)

    affectation, affectation_created = AffectationRoleOperationnel.objects.get_or_create(
        utilisateur=user, institution=institution, competence=None, role=role,
        defaults={'actif': True},
    )
    if affectation_created and request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="AffectationRoleOperationnel",
            objet_id=affectation.id,
            commentaire=f"Rôle {role.libelle} attribué à {user.email} pour {institution.nom} (choisi par l'utilisateur)",
        )

    _clear_pending_institution_fields(user)
    return contact


def _clear_pending_institution_fields(user):
    if user.pending_institution_name or user.pending_institution_type or user.pending_commune_name or user.pending_commune_code:
        user.pending_institution_name = None
        user.pending_institution_type = None
        user.pending_commune_name = None
        user.pending_commune_code = None
        user.save(update_fields=[
            'pending_institution_name', 'pending_institution_type',
            'pending_commune_name', 'pending_commune_code',
        ])


def assign_default_institution_role(user, institution=None):
    """Affecte l'utilisateur à un rôle opérationnel par défaut au sein de l'institution
    (RESPONSABLE si elle n'a encore aucune affectation, REGULATEUR sinon), sans thème/compétence
    assigné — le choix d'une compétence arbitraire (le premier objet de la table) induisait en
    erreur silencieusement. Les thèmes réels sont précisés ensuite via l'écran dédié
    (AffectationRoleOperationnelViewSet), qui peut compléter ou dupliquer cette affectation avec
    une vraie compétence. À défaut d'institution déjà résolue, retombe sur l'ancienne heuristique
    par nom (moins fiable, conservée pour ne pas régresser les cas non couverts par l'annuaire)."""
    if institution is None:
        institution_name = (user.last_name or '').strip() or user.email

        institution_type = InstitutionType.objects.filter(code__iexact='autre').first()
        if not institution_type:
            institution_type = InstitutionType.objects.create(code='autre', libelle='Autre')

        institution, institution_created = Institution.objects.get_or_create(
            nom=institution_name,
            defaults={
                'type': institution_type, 'email': user.email, 'actif': True,
                'commune_code': user.pending_commune_code or '',
                'commune_nom': user.pending_commune_name or '',
            }
        )
        if not institution_created and not institution.commune_code and user.pending_commune_code:
            institution.commune_code = user.pending_commune_code
            institution.commune_nom = user.pending_commune_name or ''
            institution.save(update_fields=['commune_code', 'commune_nom'])

    role_code = 'RESPONSABLE' if not institution.affectations_roles.exists() else 'REGULATEUR'
    role = RoleOperationnel.objects.filter(code=role_code).first()
    if not role:
        role = RoleOperationnel.objects.create(code=role_code, libelle=role_code.title())

    AffectationRoleOperationnel.objects.get_or_create(
        utilisateur=user,
        institution=institution,
        competence=None,
        role=role,
        defaults={'actif': True}
    )


def attach_secours_user_to_institution(user, request=None):
    """Rattache un compte SECOURS (Secours organisés) selon la sous-catégorie déclarée à
    l'inscription (`user.pending_institution_type`, posé par UserSerializer.create pour
    ORGANIZED_RESCUE) — à appeler uniquement à l'approbation du compte (approve_account),
    seule étape de confiance pour ce type (pas de lien magique d'activation, voir register()).

    - "aasc" : l'AASC est elle-même une institution — get-or-create par nom, comme
      assign_default_institution_role le fait déjà pour LOCAL_AUTHORITY quand aucune
      institution n'a pu être résolue, mais avec le VRAI nom déclaré (pending_institution_name)
      plutôt que le nom de famille de l'utilisateur.
    - "rcsc" : la réserve n'est pas sa propre institution, elle est rattachée à la Mairie déjà
      existante de la commune déclarée (recherche par commune_code) — jamais créée à la volée
      (une RCSC sans mairie enregistrée ne doit pas produire une fausse mairie).
    - tout autre type (ex: un agent de SDIS qui a choisi "Secours organisés" plutôt
      qu'"Institution" à l'inscription) : même résolution que le parcours Institution (domaine
      déjà connu, puis annuaire officiel, voir find_institution_for_pending_user) --
      l'approbation par un humain de confiance tient lieu ici de la confirmation explicite que
      l'utilisateur fait lui-même sur l'autre parcours. Avant ce correctif (préparation du POC
      SDIS 40, 20/10) : rien n'était rattaché ET les pending_* étaient effacés juste après --
      compte actif sans institution ni accès démo, sans plus aucune trace de ce qu'il avait
      déclaré. Sans correspondance, les pending_* sont désormais conservés pour un
      rattachement manuel.

    Retourne l'institution rattachée, ou None (aucune correspondance trouvée -- à l'appelant de
    décider quoi faire, ex: notifier pour un rattachement manuel)."""
    pending_type = (user.pending_institution_type or '').strip().lower()
    matched_institution = None

    if pending_type == 'aasc':
        aasc_type = InstitutionType.objects.filter(code='aasc').first()
        if not aasc_type:
            aasc_type = InstitutionType.objects.create(code='aasc', libelle='AASC')
        matched_institution, institution_created = Institution.objects.get_or_create(
            nom=user.pending_institution_name or user.email,
            defaults={
                'type': aasc_type, 'email': user.email, 'actif': True,
                'commune_code': user.pending_commune_code or '',
                'commune_nom': user.pending_commune_name or '',
            },
        )
        # assign_default_institution_role pose l'affectation opérationnelle (RESPONSABLE en
        # premier), mais ne crée jamais de ContactInstitution — à faire nous-même, comme
        # find_or_create_institution_from_annuaire le fait pour le rattachement mairie.
        contact, contact_created = _get_or_create_contact_institution(
            matched_institution, user, 'Créateur', institution_created,
        )
        if contact_created and request is not None:
            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="ContactInstitution",
                objet_id=contact.id,
                commentaire=f"Rattachement AASC de {user.email} à {matched_institution.nom}",
            )
        grant_institution_and_demo_access(user, matched_institution, request)
        assign_default_institution_role(user, matched_institution)

    elif pending_type == 'rcsc':
        if user.pending_commune_code:
            matched_institution = Institution.objects.filter(
                type__code__iexact='mairie', commune_code=user.pending_commune_code, actif=True,
            ).first()
        if matched_institution:
            contact, contact_created = _get_or_create_contact_institution(matched_institution, user, 'Réserviste RCSC')
            if contact_created and request is not None:
                audit_log(
                    request=request,
                    action_code="CREATION",
                    objet_type="ContactInstitution",
                    objet_id=contact.id,
                    commentaire=f"Rattachement RCSC de {user.email} à {matched_institution.nom}",
                )
            grant_institution_and_demo_access(user, matched_institution, request)

    else:
        matched_institution = find_institution_for_pending_user(user, request)
        if matched_institution is None:
            return None
        contact, contact_created = _get_or_create_contact_institution(matched_institution, user, 'Membre')
        if contact_created and request is not None:
            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="ContactInstitution",
                objet_id=contact.id,
                commentaire=f"Rattachement de {user.email} à {matched_institution.nom} (approbation compte Secours organisés)",
            )
        grant_institution_and_demo_access(user, matched_institution, request)
        assign_default_institution_role(user, matched_institution)

    _clear_pending_institution_fields(user)
    return matched_institution


def _get_or_create_contact_institution(institution, utilisateur, fonction, contact_principal=False):
    """Équivalent de `ContactInstitution.objects.get_or_create(institution=, utilisateur=,
    defaults={...})`, mais tolérant aux doublons déjà en base (constaté le 2026-10-02 sur
    l'institution "Mairie de Tests." : un même utilisateur peut déjà avoir plusieurs
    ContactInstitution actifs pour la même institution -- pas de contrainte d'unicité sur
    (institution, utilisateur) dans le modèle, voir ContactInstitution). `get_or_create` plante
    avec MultipleObjectsReturned dès qu'un doublon préexiste ; on prend le premier trouvé plutôt
    que de faire échouer toute la déclaration d'implication pour un problème de données
    sans rapport avec la demande de l'utilisateur. `fonction`/`contact_principal` ne s'appliquent
    qu'à la création -- un contact déjà existant n'est jamais modifié ici."""
    contact = ContactInstitution.objects.filter(institution=institution, utilisateur=utilisateur).first()
    if contact is not None:
        return contact, False
    return ContactInstitution.objects.create(
        institution=institution, utilisateur=utilisateur, fonction=fonction,
        contact_principal=contact_principal, actif=True,
    ), True


def resolve_or_invite_responsable(responsable_id, responsable_email, institution, request=None):
    """Résout le responsable/régulateur déclaré pour l'implication d'une institution sur une
    crise : soit un utilisateur déjà existant désigné par id, soit une invitation par email (un
    compte inactif est créé s'il n'existe pas encore). Dans les deux cas, le rattachement à
    `institution` (ContactInstitution) est créé s'il n'existe pas déjà — désigner quelqu'un comme
    responsable pour l'institution en fait de facto un contact de celle-ci, qu'il en était déjà
    membre ou non. L'appelant (perform_create de la vue) est déjà responsable de vérifier que le
    déclarant a le droit d'agir pour `institution` (membre ou administrateur) avant d'appeler
    cette fonction : elle ne revérifie pas cette appartenance.

    Retourne (user, invited) où `invited` indique qu'un nouveau compte vient d'être créé et
    qu'un email d'activation doit être envoyé par l'appelant — ce module ignore volontairement
    `request`/`build_magic_link` (définis dans views.py) pour éviter un import circulaire ; il ne
    s'en sert que pour l'audit, comme le reste du fichier."""
    if responsable_id:
        try:
            user = User.objects.get(pk=responsable_id)
        except User.DoesNotExist:
            return None, False
        if user.type == UserRole.SIMPLE_USER:
            user.type = UserRole.REGULATEUR
            user.save(update_fields=['type'])
        contact, contact_created = _get_or_create_contact_institution(institution, user, 'Régulateur de crise')
        if contact_created and request is not None:
            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="ContactInstitution",
                objet_id=contact.id,
                commentaire=f"Rattachement de {user.email} comme régulateur pour {institution.nom}",
            )
        grant_institution_and_demo_access(user, institution, request)
        return user, False

    email = (responsable_email or '').strip().lower()
    if not email:
        return None, False

    # email chiffré (voir core/crypto_fields.py) -- recherche exacte par index aveugle.
    existing = User.objects.filter(email_bidx=blind_index(email)).first()
    if existing:
        if existing.type == UserRole.SIMPLE_USER:
            existing.type = UserRole.REGULATEUR
            existing.save(update_fields=['type'])
        contact, contact_created = _get_or_create_contact_institution(institution, existing, 'Régulateur de crise')
        if contact_created and request is not None:
            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="ContactInstitution",
                objet_id=contact.id,
                commentaire=f"Rattachement de {existing.email} comme régulateur pour {institution.nom}",
            )
        grant_institution_and_demo_access(existing, institution, request)
        return existing, False

    user = User.objects.create_user(
        username=email,
        email=email,
        password=None,
        type=UserRole.REGULATEUR,
        institution=institution,
        demo_role=UserRole.REGULATEUR,
        enabled=False,
        is_active=False,
    )
    ContactInstitution.objects.create(
        institution=institution, utilisateur=user,
        fonction='Régulateur de crise', actif=True,
    )
    if request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="User",
            objet_id=user.id,
            commentaire=f"Invitation de {email} comme régulateur pour {institution.nom}",
        )
    # institution/demo_role déjà posés par create_user ci-dessus (no-op dans
    # grant_institution_and_demo_access) -- l'appel reste nécessaire pour l'ajout à l'équipe de
    # l'institution et l'email d'accès à la messagerie, comme pour tout autre rattachement.
    grant_institution_and_demo_access(user, institution, request)
    return user, True
