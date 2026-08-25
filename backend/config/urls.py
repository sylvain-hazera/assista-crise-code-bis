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

# Route média montée inconditionnellement : nginx proxifie /media/ vers le backend
# plutôt que de servir les fichiers lui-même, donc cette route doit fonctionner même
# hors DEBUG. Le helper `django.conf.urls.static.static()` ne convient pas ici : il a
# sa propre garde interne sur `settings.DEBUG` et ne génère aucune route quand DEBUG
# est faux, quoi qu'on fasse autour de son appel — on enregistre donc directement la
# vue `django.views.static.serve` sous-jacente.
urlpatterns += [
    re_path(
        r'^%s(?P<path>.*)$' % re.escape(settings.MEDIA_URL.lstrip('/')),
        serve_static,
        {'document_root': settings.MEDIA_ROOT},
    ),
]
