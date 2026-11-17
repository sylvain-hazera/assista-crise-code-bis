"""Les chemins par lesquels la zone d'une crise s'agrandit (17/11/2026).

Une commune qui rejoint une crise y fait entrer tout son territoire, OU dessine une zone en plus
de la zone initiale. Dans le second cas son code est inscrit quand même — il porte les droits
et l'accord du maire — mais « partielle » : son contour entier n'entre pas dans la zone.
"""
import pytest
from django.contrib.gis.geos import Point, Polygon
from django.urls import reverse
from rest_framework.test import APIClient

from core import zones_crise
from core.models import (
    ContactInstitution, ContributionZoneCommune, Crisis, ImplicationInstitution, Institution,
    InstitutionType, ZoneAjouteeCrise,
)

INITIALE = "POLYGON ((4.0 45.0, 4.1 45.0, 4.1 45.1, 4.0 45.1, 4.0 45.0))"
LOIN = "POLYGON ((4.5 45.5, 4.6 45.5, 4.6 45.6, 4.5 45.6, 4.5 45.5))"       # ne touche pas l'initiale
PAPILLON = "POLYGON ((4.5 45.5, 4.6 45.6, 4.6 45.5, 4.5 45.6, 4.5 45.5))"   # se recoupe


@pytest.fixture
def crise(db):
    return Crisis.objects.create(
        name="Crise à zones", type="INONDATION", location="POINT (4.05 45.05)",
        zone=Polygon.from_bbox((4.0, 45.0, 4.1, 45.1)), zone_communes=["42001"],
    )


def _mairie(create_user, crise, code, impliquee=True):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom=f"Mairie {code}", type=itype, commune_code=code)
    user = create_user(username=f"m{code}@zones.fr", email=f"m{code}@zones.fr", type="AUT_LOCALE")
    user.institution = mairie
    user.save()
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    if impliquee:
        ImplicationInstitution.objects.create(
            crise=crise, institution=mairie, type_implication="IMPLIQUE", utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return mairie, user, client


def _ajouter(client, crise, wkt=LOIN, nom="Quartier des Granges"):
    return client.post(reverse('crisis-ajouter-zone', args=[crise.id]), {"wkt": wkt, "nom": nom}, format="json")


@pytest.mark.django_db
class TestZoneEnPlus:

    def test_une_zone_s_ajoute_sans_toucher_l_initiale_meme_a_distance(self, create_user, crise):
        """`fusionner-zone` refuse un tracé qui ne touche pas l'existant ; celui-ci l'accepte."""
        mairie, _, client = _mairie(create_user, crise, "42002")

        reponse = _ajouter(client, crise)

        assert reponse.status_code == 201, reponse.data
        crise.refresh_from_db()
        assert crise.zone.equals(Polygon.from_bbox((4.0, 45.0, 4.1, 45.1)))     # initiale intacte
        (zone,) = reponse.data["zones_ajoutees"]
        assert (zone["nom"], zone["institution_nom"], zone["peut_retirer"]) == (
            "Quartier des Granges", mairie.nom, True)

    def test_la_commune_qui_dessine_entre_dans_la_zone_sans_son_territoire_entier(self, create_user, crise):
        _, _, client = _mairie(create_user, crise, "42002")

        reponse = _ajouter(client, crise)

        assert reponse.data["zone_communes"] == ["42001", "42002"]            # elle porte les droits
        assert reponse.data["zone_communes_partielles"] == ["42002"]          # sans son contour

    def test_une_commune_deja_entiere_ne_devient_pas_partielle_en_dessinant(self, create_user, crise):
        _, _, client = _mairie(create_user, crise, "42001")
        reponse = _ajouter(client, crise)
        assert reponse.data["zone_communes_partielles"] == []

    def test_la_zone_ajoutee_compte_partout_ou_la_zone_compte(self, create_user, crise):
        _, _, client = _mairie(create_user, crise, "42002")
        dedans = Point(4.55, 45.55, srid=4326)
        assert not zones_crise.contient(crise, dedans)

        _ajouter(client, crise)

        crise = Crisis.objects.get(id=crise.id)
        assert zones_crise.contient(crise, dedans)
        assert zones_crise.contient(crise, Point(4.05, 45.05, srid=4326))     # l'initiale aussi
        assert not zones_crise.contient(crise, Point(5.0, 46.0, srid=4326))
        assert zones_crise.dessinee(crise).contains(dedans)

    def test_une_institution_etrangere_a_la_crise_n_y_dessine_pas(self, create_user, crise):
        _, _, client = _mairie(create_user, crise, "42003", impliquee=False)
        assert _ajouter(client, crise).status_code == 403
        assert not ZoneAjouteeCrise.objects.exists()

    def test_un_trace_qui_se_recoupe_est_refuse(self, create_user, crise):
        _, _, client = _mairie(create_user, crise, "42002")
        assert _ajouter(client, crise, wkt=PAPILLON).status_code == 400
        assert _ajouter(client, crise, wkt="POINT (4 45)").status_code == 400

    def test_seule_l_institution_qui_l_a_dessinee_la_retire(self, create_user, crise):
        _, _, client_b = _mairie(create_user, crise, "42002")
        _, _, client_c = _mairie(create_user, crise, "42003")
        zone_id = _ajouter(client_b, crise).data["zones_ajoutees"][0]["id"]
        url = reverse('crisis-retirer-zone-ajoutee', args=[crise.id, zone_id])

        assert client_c.delete(url).status_code == 403
        reponse = client_b.delete(url)

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["zones_ajoutees"] == []
        # La commune reste inscrite : elle porte des droits, son retrait est un autre geste.
        assert "42002" in reponse.data["zone_communes"]

    def test_une_crise_close_ne_se_redessine_plus(self, create_user, crise):
        from django.utils import timezone
        _, _, client = _mairie(create_user, crise, "42002")
        Crisis.objects.filter(id=crise.id).update(end_date=timezone.now())
        assert _ajouter(client, crise).status_code == 400


@pytest.mark.django_db
class TestLesDeuxCheminsALaDeclaration:

    def _declarer(self, client, mairie, crise, **extra):
        return client.post(reverse('implicationinstitution-list'), {
            "crise": str(crise.id), "institution": str(mairie.id), "type_implication": "IMPLIQUE", **extra,
        }, format="json")

    def test_par_defaut_tout_le_territoire(self, create_user, crise):
        mairie, _, client = _mairie(create_user, crise, "42002", impliquee=False)
        assert self._declarer(client, mairie, crise).status_code == 201
        crise.refresh_from_db()
        assert "42002" in crise.zone_communes
        assert not ContributionZoneCommune.objects.get(crise=crise, commune_code="42002").partielle

    def test_ou_seulement_une_partie_a_dessiner(self, create_user, crise):
        mairie, _, client = _mairie(create_user, crise, "42002", impliquee=False)
        reponse = self._declarer(client, mairie, crise, territoire_partiel=True)
        assert reponse.status_code == 201, reponse.data
        crise.refresh_from_db()
        assert "42002" in crise.zone_communes
        assert ContributionZoneCommune.objects.get(crise=crise, commune_code="42002").partielle

    def test_une_commune_partielle_peut_ensuite_entrer_en_entier(self, create_user, crise):
        mairie, _, client = _mairie(create_user, crise, "42002", impliquee=False)
        self._declarer(client, mairie, crise, territoire_partiel=True)
        url = reverse('crisis-territoire-commune', args=[crise.id])

        reponse = client.post(url, {"code": "42002", "partielle": False}, format="json")

        assert reponse.status_code == 200, reponse.data
        assert reponse.data["zone_communes_partielles"] == []

    def test_on_ne_change_pas_le_territoire_de_la_commune_d_une_autre(self, create_user, crise):
        mairie_b, _, client_b = _mairie(create_user, crise, "42002", impliquee=False)
        self._declarer(client_b, mairie_b, crise)
        _, _, client_c = _mairie(create_user, crise, "42003")
        url = reverse('crisis-territoire-commune', args=[crise.id])
        assert client_c.post(url, {"code": "42002", "partielle": True}, format="json").status_code == 403
