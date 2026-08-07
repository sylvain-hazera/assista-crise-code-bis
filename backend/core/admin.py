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

