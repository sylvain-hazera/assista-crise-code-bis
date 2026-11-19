"""Un administrateur placé dans une institution agit pour elle et ses filles, pas pour toute la
plateforme (19/11/2026 : la page des campagnes proposait toutes les institutions)."""
import pytest
from rest_framework.test import APIClient

from core.models import Institution, InstitutionType
from core.perimetre_admin import institutions_descendantes

URL = "/api/campagnes-disponibilite/institutions/"


@pytest.fixture
def arbre(db):
    t, _ = InstitutionType.objects.get_or_create(code="CONSEIL_DEPARTEMENTAL", defaults={"libelle": "Conseil départemental"})
    cd = Institution.objects.create(nom="Conseil départemental - Loire", type=t)
    fille = Institution.objects.create(nom="Maison du département", type=t, institution_parente=cd)
    petite_fille = Institution.objects.create(nom="Antenne de Roanne", type=t, institution_parente=fille)
    etrangere = Institution.objects.create(nom="Mairie - Gruissan", type=t)
    return {"cd": cd, "fille": fille, "petite_fille": petite_fille, "etrangere": etrangere}


@pytest.fixture
def admin(db, create_user):
    compte = create_user(username="admin-filles@x.fr", email="admin-filles@x.fr", type="ADMIN")
    client = APIClient()
    client.force_authenticate(user=compte)
    return client


def _noms(reponse):
    return {i["nom"] for i in reponse.data["institutions"]}


def test_place_dans_une_institution_il_ne_voit_qu_elle_et_ses_filles(arbre, admin):
    reponse = admin.get(URL, HTTP_X_PERIMETRE=str(arbre["cd"].id))
    assert reponse.status_code == 200
    assert _noms(reponse) == {"Conseil départemental - Loire", "Maison du département", "Antenne de Roanne"}


def test_place_dans_une_fille_il_ne_remonte_pas_a_la_mere(arbre, admin):
    reponse = admin.get(URL, HTTP_X_PERIMETRE=str(arbre["fille"].id))
    assert _noms(reponse) == {"Maison du département", "Antenne de Roanne"}


def test_sur_toute_la_plateforme_il_voit_tout(arbre, admin):
    reponse = admin.get(URL, HTTP_X_PERIMETRE="TOUT")
    assert {"Conseil départemental - Loire", "Mairie - Gruissan"} <= _noms(reponse)


def test_un_cycle_pose_a_la_main_ne_fait_pas_boucler(arbre):
    Institution.objects.filter(pk=arbre["cd"].pk).update(institution_parente=arbre["petite_fille"])
    assert institutions_descendantes({arbre["cd"].id}) == {arbre["cd"].id, arbre["fille"].id, arbre["petite_fille"].id}
    assert institutions_descendantes(set()) == set()


def test_les_listes_suivent_le_perimetre_de_l_administrateur(arbre, admin):
    """Configurations d'alerte vigilance (et, sur le même modèle, alerte feux et messages à
    relire) : placé dans une institution, l'administrateur ne voit que la sienne."""
    from core.models import ConfigurationAlerteVigilance
    ConfigurationAlerteVigilance.objects.create(institution=arbre["cd"], actif=True)
    ConfigurationAlerteVigilance.objects.create(institution=arbre["etrangere"], actif=True)
    url = "/api/configurations-alerte-vigilance/"
    lire = lambda r: {str(c["institution"]) for c in (r.data["results"] if isinstance(r.data, dict) else r.data)}  # noqa: E731
    assert lire(admin.get(url, HTTP_X_PERIMETRE=str(arbre["cd"].id))) == {str(arbre["cd"].id)}
    assert lire(admin.get(url, HTTP_X_PERIMETRE="TOUT")) == {str(arbre["cd"].id), str(arbre["etrangere"].id)}
