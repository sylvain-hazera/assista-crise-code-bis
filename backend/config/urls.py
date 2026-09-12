"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
import re

from django.conf import settings
from django.contrib import admin
from django.http import HttpResponseForbidden
from django.urls import path, re_path, include
from django.views.static import serve as serve_static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    # Sous /django-admin/ (et non /admin/) pour matcher ce que proxy/nginx.conf
    # proxifie déjà vers le backend, et ne pas entrer en conflit avec le préfixe
    # /admin utilisé par le SPA Angular côté frontend.
    path('django-admin/', admin.site.urls),
    path('api/', include('core.urls')),

    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

# Préfixes sous MEDIA_ROOT qui ne doivent JAMAIS être servis en direct — chacun n'est
# accessible qu'via une action /api/.../preview|download/ qui vérifie les droits à chaque
# appel (user_can_view_photo / check_document_access). Miroir exact des `location
# /media/photos|documents|recherches/ { return 403; }` de proxy/nginx.conf : nginx est déjà
# censé bloquer ces chemins en prod, cette route Django fait la même chose en défense en
# profondeur (dev sans nginx devant, ou nginx un jour mal reconfiguré — déjà arrivé sur ce
# projet). Aujourd'hui, TOUT champ à fichier du site tombe sous l'un de ces trois préfixes
# (voir secure_*_path dans core/models.py) : rien n'est plus jamais requis en accès direct.
PREFIXES_MEDIA_PROTEGES = ('photos/', 'documents/', 'recherches/')


def serve_media(request, path, document_root=None):
    if path.startswith(PREFIXES_MEDIA_PROTEGES):
        return HttpResponseForbidden()
    return serve_static(request, path, document_root=document_root)


# Route média montée inconditionnellement : nginx proxifie /media/ vers le backend
# plutôt que de servir les fichiers lui-même, donc cette route doit fonctionner même
# hors DEBUG. Le helper `django.conf.urls.static.static()` ne convient pas ici : il a
# sa propre garde interne sur `settings.DEBUG` et ne génère aucune route quand DEBUG
# est faux, quoi qu'on fasse autour de son appel — on enregistre donc directement la
# vue `serve_media` ci-dessus (elle-même basée sur `django.views.static.serve`).
urlpatterns += [
    re_path(
        r'^%s(?P<path>.*)$' % re.escape(settings.MEDIA_URL.lstrip('/')),
        serve_media,
        {'document_root': settings.MEDIA_ROOT},
    ),
]
