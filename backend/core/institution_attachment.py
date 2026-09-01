"""Rattachement automatique d'un utilisateur à une institution (contact + rôle opérationnel).

Ces fonctions ne doivent JAMAIS être appelées avant que la possession de la boîte mail de
l'utilisateur ait été prouvée (clic sur le lien d'activation) : rattacher un compte à une
institution réelle sur la seule foi d'un email non vérifié permettrait à quiconque de se faire
passer pour un employé d'une institution (ex: une mairie, un SDIS) sans jamais recevoir ni
cliquer sur aucun email.
"""
from .audit import audit_log
from .auth_validation import InstitutionEmailValidator
from .models import (
    AffectationRoleOperationnel,
    ContactInstitution,
    Institution,
    InstitutionDomaine,
    InstitutionType,
    RoleOperationnel,
    User,
    UserRole,
)


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

    institution_type, _ = InstitutionType.objects.get_or_create(
        code=type_code,
        defaults={'libelle': type_code.title()},
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

    contact, contact_created = ContactInstitution.objects.get_or_create(
        institution=institution,
        utilisateur=user,
        defaults={'fonction': fonction, 'contact_principal': contact_principal, 'actif': True},
    )
    if contact_created and request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="ContactInstitution",
            objet_id=contact.id,
            commentaire=f"Rattachement de {user.email} à l'institution {institution.nom} (confirmé par l'utilisateur)",
        )

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
    - tout autre type (ou aucun) : ne fait rien, comportement inchangé.

    Retourne l'institution rattachée, ou None (soit parce que le type n'est ni aasc ni rcsc,
    soit parce qu'aucune mairie n'a pu être trouvée pour une RCSC — à l'appelant de décider
    quoi faire dans ce dernier cas, ex: notifier pour un rattachement manuel)."""
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
        contact, contact_created = ContactInstitution.objects.get_or_create(
            institution=matched_institution, utilisateur=user,
            defaults={'fonction': 'Créateur', 'contact_principal': institution_created, 'actif': True},
        )
        if contact_created and request is not None:
            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="ContactInstitution",
                objet_id=contact.id,
                commentaire=f"Rattachement AASC de {user.email} à {matched_institution.nom}",
            )
        assign_default_institution_role(user, matched_institution)

    elif pending_type == 'rcsc':
        if user.pending_commune_code:
            matched_institution = Institution.objects.filter(
                type__code='mairie', commune_code=user.pending_commune_code, actif=True,
            ).first()
        if matched_institution:
            contact, contact_created = ContactInstitution.objects.get_or_create(
                institution=matched_institution, utilisateur=user,
                defaults={'fonction': 'Réserviste RCSC', 'actif': True},
            )
            if contact_created and request is not None:
                audit_log(
                    request=request,
                    action_code="CREATION",
                    objet_type="ContactInstitution",
                    objet_id=contact.id,
                    commentaire=f"Rattachement RCSC de {user.email} à {matched_institution.nom}",
                )

    _clear_pending_institution_fields(user)
    return matched_institution


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
        contact, contact_created = ContactInstitution.objects.get_or_create(
            institution=institution, utilisateur=user,
            defaults={'fonction': 'Régulateur de crise', 'actif': True},
        )
        if contact_created and request is not None:
            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="ContactInstitution",
                objet_id=contact.id,
                commentaire=f"Rattachement de {user.email} comme régulateur pour {institution.nom}",
            )
        return user, False

    email = (responsable_email or '').strip().lower()
    if not email:
        return None, False

    existing = User.objects.filter(email__iexact=email).first()
    if existing:
        if existing.type == UserRole.SIMPLE_USER:
            existing.type = UserRole.REGULATEUR
            existing.save(update_fields=['type'])
        contact, contact_created = ContactInstitution.objects.get_or_create(
            institution=institution, utilisateur=existing,
            defaults={'fonction': 'Régulateur de crise', 'actif': True},
        )
        if contact_created and request is not None:
            audit_log(
                request=request,
                action_code="CREATION",
                objet_type="ContactInstitution",
                objet_id=contact.id,
                commentaire=f"Rattachement de {existing.email} comme régulateur pour {institution.nom}",
            )
        return existing, False

    user = User.objects.create_user(
        username=email,
        email=email,
        password=None,
        type=UserRole.REGULATEUR,
        institution=institution,
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
    return user, True
