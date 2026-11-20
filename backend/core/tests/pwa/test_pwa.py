"""Le site installable comme une application : manifestes et icônes par marque (20/11/2026)."""
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from core.models import Institution, InstitutionType, InstitutionWebDomaine


def _png(couleur=(200, 30, 30, 255), taille=(300, 120)):
    tampon = io.BytesIO()
    Image.new("RGBA", taille, couleur).save(tampon, format="PNG")
    return tampon.getvalue()


@pytest.mark.django_db
def test_manifeste_terrain_par_defaut(client):
    r = client.get("/api/pwa/manifeste/")
    assert r.status_code == 200
    assert r["Content-Type"].startswith("application/manifest+json")
    assert "max-age=300" in r["Cache-Control"]
    m = r.json()
    assert m["start_url"] == "/terrain" and m["id"] == "/terrain" and m["scope"] == "/"
    assert m["display"] == "standalone" and m["lang"] == "fr"
    assert m["name"].endswith("— Terrain")
    assert {i["purpose"] for i in m["icons"]} == {"any", "maskable"}
    assert all(i["src"].startswith("/api/pwa/icone/") for i in m["icons"])


@pytest.mark.django_db
def test_manifeste_pilotage_s_ouvre_sur_l_administration(client):
    m = client.get("/api/pwa/manifeste/", {"espace": "pilotage"}).json()
    assert m["start_url"] == "/admin" and m["id"] == "/admin" and m["short_name"] == "Pilotage"
    assert client.get("/api/pwa/manifeste/", {"espace": "ailleurs"}).status_code == 404


@pytest.mark.django_db
def test_icone_carree_sur_fond_blanc(client):
    for taille in (180, 192, 512):
        r = client.get("/api/pwa/icone/", {"taille": taille})
        assert r.status_code == 200 and r["Content-Type"] == "image/png"
        image = Image.open(io.BytesIO(r.content))
        assert image.size == (taille, taille) and image.mode == "RGB"
        assert image.getpixel((0, 0)) == (255, 255, 255)          # pas de transparence : iOS la noircit
    assert client.get("/api/pwa/icone/", {"taille": 64}).status_code == 404
    assert client.get("/api/pwa/icone/", {"taille": "grand"}).status_code == 404


@pytest.mark.django_db
def test_la_marque_du_domaine_donne_nom_couleur_et_icone(client, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    settings.ALLOWED_HOSTS = ["*"]
    itype = InstitutionType.objects.create(code="AASC_PWA", libelle="Association agréée")
    institution = Institution.objects.create(nom="Réserve Résilience", nom_affichage="Réserve Résilience",
                                             couleur_primaire="#0f766e", type=itype)
    institution.logo = SimpleUploadedFile("logo.png", _png(), content_type="image/png")
    institution.save()
    InstitutionWebDomaine.objects.create(institution=institution, hostname="marque-essai.exemple.fr")

    m = client.get("/api/pwa/manifeste/", HTTP_HOST="marque-essai.exemple.fr").json()
    assert m["name"] == "Réserve Résilience — Terrain" and m["theme_color"] == "#0f766e"
    assert m["short_name"] == "Réserve Rési"                     # 12 caractères au plus

    r = client.get("/api/pwa/icone/", {"taille": 192}, HTTP_HOST="marque-essai.exemple.fr")
    centre = Image.open(io.BytesIO(r.content)).getpixel((96, 96))
    assert centre[0] > 150 and centre[1] < 80                       # le rouge du logo de la marque
    masquable = Image.open(io.BytesIO(client.get(
        "/api/pwa/icone/", {"taille": 512, "masquable": "1"}, HTTP_HOST="marque-essai.exemple.fr").content))
    assert masquable.getpixel((40, 256)) == (255, 255, 255)        # marge de sûreté plus large
