"""Image de partage du site, par marque (16/11/2026).

Un lien vers le site, partagé par WhatsApp ou par SMS, s'affichait « Assista Crise » sans
image, quel que soit le domaine. L'en-tête de la page annonce maintenant une image
(`og:image`) à une adresse fixe, /api/branding/logo/, qui renvoie vers le logo de la marque
du domaine visité : les services de partage n'exécutent pas le JavaScript et ne peuvent pas
lire /api/branding/.
"""
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from core.models import Institution, InstitutionType, InstitutionWebDomaine

URL = "/api/branding/logo/"
DOMAINE = "reserve-logo.exemple.fr"

# Le plus petit PNG valide : un pixel.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6300010000000500010d0a2db40000000049454e44ae426082")


@pytest.fixture
def marque(db, settings, tmp_path):
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + [DOMAINE]
    settings.MEDIA_ROOT = str(tmp_path)
    itype = InstitutionType.objects.create(code="AASC_LOGO", libelle="Association agréée")
    institution = Institution.objects.create(nom="Réserve du logo", type=itype)
    InstitutionWebDomaine.objects.create(institution=institution, hostname=DOMAINE)
    return institution


@pytest.mark.django_db
class TestLogoDeLaMarque:
    def test_le_site_generaliste_renvoie_vers_le_logo_assista_crise(self):
        reponse = APIClient().get(URL)

        assert reponse.status_code == 302
        assert reponse["Location"] == "/logo.png"

    def test_une_marque_sans_logo_garde_celui_par_defaut(self, marque):
        reponse = APIClient().get(URL, HTTP_HOST=DOMAINE)

        assert reponse.status_code == 302
        assert reponse["Location"] == "/logo.png"

    def test_une_marque_renvoie_vers_son_propre_logo(self, marque):
        marque.logo = SimpleUploadedFile("logo.png", PNG, content_type="image/png")
        marque.save()

        reponse = APIClient().get(URL, HTTP_HOST=DOMAINE)

        assert reponse.status_code == 302
        assert reponse["Location"] == marque.logo.url
        # Le logo d'une marque ne sort jamais sous le nom d'une autre.
        assert APIClient().get(URL)["Location"] == "/logo.png"

    def test_la_reponse_est_lisible_sans_compte(self, marque):
        """Les services de partage n'ont pas de session."""
        assert APIClient().get(URL, HTTP_HOST=DOMAINE).status_code == 302          # et non 401
