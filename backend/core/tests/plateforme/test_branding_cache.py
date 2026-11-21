"""La charte est gardée 5 minutes par le navigateur (19/11/2026, « le site rame »)."""
import pytest
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_la_charte_est_gardee_cinq_minutes_par_le_navigateur():
    reponse = APIClient().get("/api/branding/")
    assert reponse.status_code == 200
    assert reponse["Cache-Control"] == "public, max-age=300"


@pytest.mark.django_db
def test_les_autres_reponses_de_l_api_restent_sans_cache():
    reponse = APIClient().get("/api/sonde/")
    assert reponse["Cache-Control"] == "no-store"


@pytest.mark.django_db
def test_le_pied_de_page_porte_l_adresse_de_contact_de_la_marque(settings):
    """Sur le domaine d'une marque blanche, l'adresse de contact est la sienne ; sur le site
    généraliste, aucune (le site affiche alors celle d'Assista-Crise)."""
    from core.models import Institution, InstitutionType, InstitutionWebDomaine
    assert APIClient().get("/api/branding/").data["email_contact"] is None
    itype, _ = InstitutionType.objects.get_or_create(code="aasc", defaults={"libelle": "AASC"})
    marque = Institution.objects.create(nom="Marque test", type=itype, nom_affichage="Marque test",
                                        email_reply_to="contact@marque.exemple")
    InstitutionWebDomaine.objects.create(institution=marque, hostname="app.marque.exemple")
    settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "app.marque.exemple"]
    reponse = APIClient().get("/api/branding/", HTTP_HOST="app.marque.exemple")
    assert reponse.data["email_contact"] == "contact@marque.exemple"
