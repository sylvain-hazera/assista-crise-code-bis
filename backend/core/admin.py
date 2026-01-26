from django.contrib import admin

from django.contrib.gis.admin import GISModelAdmin
from .models import (
    Utilisateur, Crise, Demande, Offre, Information,
    TypeDemande, TypeOffre, TypeInformation
)


@admin.register(Crise)
class CriseAdmin(GISModelAdmin):
    list_display = ('nom', 'date_debut', 'validateur')
    search_fields = ('nom',)

@admin.register(Demande)
class DemandeAdmin(GISModelAdmin):
    list_display = ('titre', 'statut', 'type_demande', 'auteur')
    list_filter = ('statut', 'type_demande')

@admin.register(Offre)
class OffreAdmin(GISModelAdmin):
    list_display = ('titre', 'statut', 'type_offre', 'auteur')
    list_filter = ('statut', 'type_offre')

@admin.register(Information)
class InformationAdmin(GISModelAdmin):
    list_display = ('titre', 'statut', 'type_information')


@admin.register(Utilisateur)
class UtilisateurAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'type', 'crise_touchee')
    list_filter = ('type',)


admin.site.register(TypeDemande)
admin.site.register(TypeOffre)
admin.site.register(TypeInformation)