from django.contrib import admin

from django.contrib.gis.admin import GISModelAdmin
from .models import (
    User, Crisis, Request, Offer, Information,
    RequestType, OfferType, InformationType
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