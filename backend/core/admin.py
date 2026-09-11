from django.contrib import admin

from django.contrib.gis.admin import GISModelAdmin
from .models import (
    User, Crisis, Request, Offer, Information,
    RequestType, OfferType, InformationType,
    InstitutionType,
    Institution,
    RoleOperationnel,
    ContactInstitution,
    InstitutionDomaine,
    InstitutionCompetence,
    AffectationRoleOperationnel,
    DisponibiliteOperationnelle,
    DelegationCompetence,
    PointType,
    PointOperationnel,
    AuditAction,
    AuditLog,
    CompagnonMeshCore,
    NoeudMeshUtilisateur,
    MessageMeshLog,
    RelaisMeshCore,
    CanalMeshCore,
    MessageCanalMeshCore,
)


@admin.register(Crisis)
class CrisisAdmin(GISModelAdmin):
    """Admin pour les crises"""
    list_display = ('name', 'start_date', 'validator')
    search_fields = ('name',)

@admin.register(Request)
class RequestAdmin(GISModelAdmin):
    """Admin pour les demandes d'aide"""
    list_display = ('title', 'status', 'request_type', 'author')
    list_filter = ('status', 'request_type')

@admin.register(Offer)
class OfferAdmin(GISModelAdmin):
    """Admin pour les offres d'aide"""
    list_display = ('title', 'status', 'offer_type', 'author')
    list_filter = ('status', 'offer_type')

@admin.register(Information)
class InformationAdmin(GISModelAdmin):
    """Admin pour les informations"""
    list_display = ('title', 'status', 'information_type')


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Admin pour les utilisateurs"""
    list_display = ('username', 'email', 'type', 'affected_crisis')
    list_filter = ('type',)

admin.site.register(RequestType)
admin.site.register(OfferType)
admin.site.register(InformationType)
admin.site.register(InstitutionType)
admin.site.register(Institution)
admin.site.register(RoleOperationnel)
admin.site.register(InstitutionCompetence)
admin.site.register(AffectationRoleOperationnel)
admin.site.register(DisponibiliteOperationnelle)
admin.site.register(DelegationCompetence)
admin.site.register(PointType)
admin.site.register(PointOperationnel)
admin.site.register(AuditAction)
admin.site.register(AuditLog)
admin.site.register(ContactInstitution)
admin.site.register(InstitutionDomaine)



@admin.register(CompagnonMeshCore)
class CompagnonMeshCoreAdmin(admin.ModelAdmin):
    """Config rapide pour la phase de test MeshCore (voir meshcore-bridge/) — pas encore de
    page Angular dédiée tant que le matériel n'a pas confirmé l'usage."""
    list_display = ('nom', 'connexion_type', 'institution', 'actif', 'dernier_etat', 'derniere_connexion')
    list_filter = ('connexion_type', 'actif', 'dernier_etat')
    readonly_fields = ('pubkey_hex', 'derniere_connexion', 'dernier_etat', 'derniere_erreur', 'date_creation')


@admin.register(NoeudMeshUtilisateur)
class NoeudMeshUtilisateurAdmin(admin.ModelAdmin):
    list_display = ('pubkey_hex', 'utilisateur', 'nom_noeud', 'actif')
    search_fields = ('pubkey_hex', 'utilisateur__email', 'nom_noeud')


@admin.register(MessageMeshLog)
class MessageMeshLogAdmin(admin.ModelAdmin):
    list_display = ('compagnon', 'direction', 'statut', 'contact_pubkey_hex', 'expediteur', 'date_creation')
    list_filter = ('direction', 'statut', 'compagnon')
    readonly_fields = ('date_creation',)


@admin.register(RelaisMeshCore)
class RelaisMeshCoreAdmin(GISModelAdmin):
    list_display = ('nom', 'institution', 'actif', 'pubkey_hex')


@admin.register(CanalMeshCore)
class CanalMeshCoreAdmin(admin.ModelAdmin):
    list_display = ('nom', 'institution', 'crise', 'actif')


@admin.register(MessageCanalMeshCore)
class MessageCanalMeshCoreAdmin(admin.ModelAdmin):
    list_display = ('canal', 'direction', 'statut', 'expediteur', 'date_creation')
    list_filter = ('direction', 'statut', 'canal')
