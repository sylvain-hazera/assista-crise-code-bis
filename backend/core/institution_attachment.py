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
    Competence,
    ContactInstitution,
    Institution,
    InstitutionDomaine,
    InstitutionType,
    RoleOperationnel,
    User,
    UserRole,
)


def attach_by_known_domain(user, request=None):
    """Rattache l'utilisateur à l'institution propriétaire de son domaine email, si déjà connu
    (InstitutionDomaine, alimenté par une précédente confirmation de l'annuaire)."""
    domain = (user.email or '').rsplit('@', 1)[-1].strip().lower()
    if not domain:
        return None

    institution_domaine = InstitutionDomaine.objects.filter(
        domaine__iexact=domain, valide=True
    ).select_related('institution').first()

    if not institution_domaine:
        return None

    institution = institution_domaine.institution

    contact, created = ContactInstitution.objects.get_or_create(
        institution=institution,
        utilisateur=user,
        defaults={'fonction': 'Membre (domaine email reconnu)', 'actif': True},
    )

    if created and request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="ContactInstitution",
            objet_id=contact.id,
            commentaire=(
                f"Rattachement automatique via domaine email '{domain}' "
                f"à l'institution {institution.nom}"
            ),
        )

    return institution


def resolve_or_create_institution_from_annuaire(user, annuaire_match, request=None):
    """Trouve/crée l'institution confirmée par l'annuaire officiel, met en cache son domaine
    (InstitutionDomaine) et y rattache l'utilisateur, pour que les inscriptions suivantes sur
    ce domaine profitent du rattachement automatique sans re-solliciter l'API."""
    domain = annuaire_match.get('domain')
    nom = annuaire_match.get('nom') or domain
    type_code = (annuaire_match.get('type_service_local') or 'autre').strip().lower() or 'autre'

    institution_type, _ = InstitutionType.objects.get_or_create(
        code=type_code,
        defaults={'libelle': type_code.title()},
    )

    institution, institution_created = Institution.objects.get_or_create(
        nom=nom,
        defaults={'type': institution_type, 'email': user.email, 'actif': True},
    )
    if institution_created and request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="Institution",
            objet_id=institution.id,
            commentaire=f"Création institution via annuaire officiel : {institution.nom}",
        )

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

    contact, contact_created = ContactInstitution.objects.get_or_create(
        institution=institution,
        utilisateur=user,
        defaults={'fonction': 'Membre (validation annuaire)', 'actif': True},
    )
    if contact_created and request is not None:
        audit_log(
            request=request,
            action_code="CREATION",
            objet_type="ContactInstitution",
            objet_id=contact.id,
            commentaire=f"Rattachement automatique via annuaire officiel à l'institution {institution.nom}",
        )

    return institution


def assign_default_institution_role(user, institution=None):
    """Affecte l'utilisateur à un rôle opérationnel par défaut au sein de l'institution
    (RESPONSABLE si elle n'a encore aucune affectation, REGULATEUR sinon). À défaut d'institution
    déjà résolue, retombe sur l'ancienne heuristique par nom (moins fiable, conservée pour ne pas
    régresser les cas non couverts par l'annuaire)."""
    if institution is None:
        institution_name = (user.last_name or '').strip() or user.email

        institution_type = InstitutionType.objects.filter(code__iexact='autre').first()
        if not institution_type:
            institution_type = InstitutionType.objects.create(code='autre', libelle='Autre')

        institution, _ = Institution.objects.get_or_create(
            nom=institution_name,
            defaults={'type': institution_type, 'email': user.email, 'actif': True}
        )

    role_code = 'RESPONSABLE' if not institution.affectations_roles.exists() else 'REGULATEUR'
    role = RoleOperationnel.objects.filter(code=role_code).first()
    if not role:
        role = RoleOperationnel.objects.create(code=role_code, libelle=role_code.title())

    competence = Competence.objects.first()
    if competence is None:
        competence = Competence.objects.create(nom='Général', description='Compétence par défaut')

    AffectationRoleOperationnel.objects.get_or_create(
        utilisateur=user,
        institution=institution,
        competence=competence,
        role=role,
        defaults={'actif': True}
    )


def attach_user_to_institution(user, request=None):
    """Point d'entrée unique : à appeler uniquement APRÈS confirmation de l'email (activation).

    Essaie d'abord le cache local (InstitutionDomaine), puis à défaut relance une vérification
    auprès de l'annuaire officiel à partir des informations déclarées à l'inscription
    (user.pending_institution_*). Nettoie ces champs une fois utilisés, qu'une correspondance
    ait été trouvée ou non."""
    matched_institution = attach_by_known_domain(user, request)

    if matched_institution is None and user.pending_institution_name:
        valid, _message, details = InstitutionEmailValidator.validate_institution_account(
            email=user.email,
            institution_name=user.pending_institution_name or '',
            institution_type=user.pending_institution_type or '',
            commune_name=user.pending_commune_name or '',
            commune_code=user.pending_commune_code or '',
        )
        annuaire_match = (details or {}).get('annuaire') if valid else None
        if annuaire_match and annuaire_match.get('matched'):
            matched_institution = resolve_or_create_institution_from_annuaire(user, annuaire_match, request)

    if user.type == UserRole.LOCAL_AUTHORITY:
        assign_default_institution_role(user, matched_institution)

    if user.pending_institution_name or user.pending_institution_type or user.pending_commune_name or user.pending_commune_code:
        user.pending_institution_name = None
        user.pending_institution_type = None
        user.pending_commune_name = None
        user.pending_commune_code = None
        user.save(update_fields=[
            'pending_institution_name', 'pending_institution_type',
            'pending_commune_name', 'pending_commune_code',
        ])

    return matched_institution


def resolve_or_invite_responsable(responsable_id, responsable_email, institution, request=None):
    """Résout le responsable/régulateur déclaré pour l'implication d'une institution sur une
    crise : soit un contact déjà rattaché à l'institution (par id), soit une invitation par email
    (un compte inactif est créé s'il n'existe pas encore).

    Retourne (user, invited) où `invited` indique qu'un nouveau compte vient d'être créé et
    qu'un email d'activation doit être envoyé par l'appelant — ce module ignore volontairement
    `request`/`build_magic_link` (définis dans views.py) pour éviter un import circulaire ; il ne
    s'en sert que pour l'audit, comme le reste du fichier."""
    if responsable_id:
        try:
            user = User.objects.get(pk=responsable_id)
        except User.DoesNotExist:
            return None, False
        if not ContactInstitution.objects.filter(
            institution=institution, utilisateur=user, actif=True
        ).exists():
            return None, False
        if user.type == UserRole.SIMPLE_USER:
            user.type = UserRole.REGULATEUR
            user.save(update_fields=['type'])
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
