"""Référentiel d'adresses (core/referentiel_adresses.py, 20/11/2026) : la Base Adresse Nationale
copiée en local, par fichier départemental.

Le fichier est fabriqué ici avec l'en-tête exact des fichiers de la BAN (vérifié le 20/11/2026 sur
Mayotte et la Corse-du-Sud). Aucun test n'appelle l'extérieur."""
import datetime
import gzip
import io
from unittest.mock import patch

import pytest
from django.contrib.gis.geos import Point, Polygon
from django.urls import reverse
from rest_framework.test import APIClient

from core import rattachement_adresses, referentiel_adresses, sources_ouvertes
from core.models import AdresseBAN, Commune, Crisis, Habitation, Institution, InstitutionType

UTC = datetime.timezone.utc
EN_TETE = ("id;id_fantoir;numero;rep;nom_voie;code_postal;code_insee;nom_commune;code_insee_ancienne_commune;"
           "nom_ancienne_commune;x;y;lon;lat;type_position;alias;nom_ld;libelle_acheminement;nom_afnor;"
           "source_position;source_nom_voie;certification_commune;cad_parcelles")
LE_PORGE = "33333"
VOISINE = "33334"


def ligne(ban_id, numero, voie, commune=LE_PORGE, lon=-1.2, lat=44.87, rep="", lieu_dit="", nom="Le Porge"):
    return (f"{ban_id};x;{numero};{rep};{voie};33680;{commune};{nom};;;0;0;{lon};{lat};entrée;;{lieu_dit};"
            f"{nom.upper()};{voie.upper()};commune;commune;1;33333000AB0012")


def fichier(*lignes):
    tampon = io.BytesIO()
    with gzip.GzipFile(fileobj=tampon, mode="wb") as f:
        f.write("\n".join((EN_TETE,) + lignes).encode("utf-8"))
    tampon.seek(0)
    return gzip.GzipFile(fileobj=tampon)


BOURG = (ligne("33333_0010_00001", "1", "Rue des Pins", lon=-1.2000),
         ligne("33333_0010_00003", "3", "Rue des Pins", rep="bis", lon=-1.2003),
         ligne("33333_0020_00012", "12", "Allée des Chênes", lon=-1.2100, lieu_dit="Le Bourg"),
         ligne("33334_0001_00002", "2", "Route de la Plage", commune=VOISINE, lon=-1.25, nom="Voisine"),
         ligne("40001_0001_00001", "1", "Rue Ailleurs", commune="40001", lon=-1.0, nom="Landes"))


@pytest.mark.django_db
class TestChargement:
    def test_le_departement_d_une_commune(self):
        assert [referentiel_adresses.departement_de(c) for c in ("33236", "97411", "2A004", "01001")] == ["33", "974", "2A", "01"]

    def test_seules_les_communes_voulues_sont_chargees(self):
        comptes = referentiel_adresses.charger_departement("33", {LE_PORGE}, flux=fichier(*BOURG))
        assert comptes == {"lues": 3, "creees": 3, "modifiees": 0, "retirees": 0}
        assert set(AdresseBAN.objects.values_list("commune_code", flat=True)) == {LE_PORGE}
        bis = AdresseBAN.objects.get(ban_id="33333_0010_00003")
        assert bis.libelle == "3 bis Rue des Pins, 33680 Le Porge"
        assert AdresseBAN.objects.get(ban_id="33333_0020_00012").libelle == "12 Allée des Chênes, Le Bourg, 33680 Le Porge"
        assert bis.parcelles == "33333000AB0012" and bis.type_position == "entrée"

    def test_une_mise_a_jour_ajoute_modifie_retire_sans_effacer(self):
        referentiel_adresses.charger_departement("33", {LE_PORGE}, flux=fichier(*BOURG))
        apres = (ligne("33333_0010_00001", "1", "Rue des Pins", lon=-1.2001),     # déplacée
                 ligne("33333_0020_00012", "12", "Allée des Chênes", lon=-1.2100, lieu_dit="Le Bourg"),
                 ligne("33333_0030_00005", "5", "Impasse Neuve"))                  # nouvelle ; le 3 bis a disparu
        comptes = referentiel_adresses.charger_departement("33", {LE_PORGE}, flux=fichier(*apres))
        assert comptes == {"lues": 3, "creees": 1, "modifiees": 1, "retirees": 1}
        assert AdresseBAN.objects.get(ban_id="33333_0010_00003").retiree_le is not None    # gardée, marquée
        # Elle revient : elle n'est plus retirée.
        comptes = referentiel_adresses.charger_departement("33", {LE_PORGE}, flux=fichier(*BOURG))
        assert AdresseBAN.objects.get(ban_id="33333_0010_00003").retiree_le is None

    def test_un_fichier_sans_la_commune_ne_la_vide_pas(self):
        referentiel_adresses.charger_departement("33", {LE_PORGE}, flux=fichier(*BOURG))
        comptes = referentiel_adresses.charger_departement("33", {LE_PORGE}, flux=fichier(BOURG[3]))
        assert comptes["retirees"] == 0
        assert AdresseBAN.objects.filter(retiree_le__isnull=True).count() == 3

    def test_un_telechargement_par_departement(self):
        appels = []

        def telecharger(departement):
            appels.append(departement)
            return fichier(*BOURG)

        with patch.object(referentiel_adresses, "telecharger", side_effect=telecharger):
            total = referentiel_adresses.charger_communes([LE_PORGE, VOISINE, "40001"])
        assert sorted(appels) == ["33", "40"] and total["creees"] == 5


@pytest.mark.django_db
class TestQuellesCommunes:
    def test_territoire_communal_intercommunal_et_departemental(self):
        Commune.objects.create(code=LE_PORGE, nom="Le Porge", epci_code="200000001", departement_code="33")
        Commune.objects.create(code=VOISINE, nom="Voisine", epci_code="200000001", departement_code="33")
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        mairie = Institution(nom="Mairie", type=itype, commune_code=LE_PORGE, secteur_niveau_effectif="commune")
        epci = Institution(nom="Com com", type=itype, epci_code="200000001", secteur_niveau_effectif="epci")
        prefecture = Institution(nom="Préfecture", type=itype, departement_code="33", secteur_niveau_effectif="departement")
        assert referentiel_adresses.communes_d_institution(mairie) == {LE_PORGE}
        assert referentiel_adresses.communes_d_institution(epci) == {LE_PORGE, VOISINE}
        assert referentiel_adresses.communes_d_institution(prefecture) == set()      # pas tout le département d'avance

    def test_communes_d_une_crise(self):
        Commune.objects.create(code=LE_PORGE, nom="Le Porge", departement_code="33", centre_latitude=44.87, centre_longitude=-1.2)
        Commune.objects.create(code="40001", nom="Landes", departement_code="40", centre_latitude=43.9, centre_longitude=-0.5)
        par_liste = Crisis(name="a", zone_communes=[VOISINE], zone_departements=["40"])
        assert referentiel_adresses.communes_de_crise(par_liste) == {VOISINE, "40001"}
        dessinee = Crisis(name="b", zone=Polygon.from_bbox((-1.3, 44.8, -1.1, 44.9)))
        assert referentiel_adresses.communes_de_crise(dessinee) == {LE_PORGE}

    def test_une_crise_ouverte_charge_ses_communes_manquantes_seulement(self, settings, django_capture_on_commit_callbacks):
        settings.CHARGEMENT_ADRESSES_AUTO = True
        AdresseBAN.objects.create(ban_id="x", commune_code=LE_PORGE, location=Point(-1.2, 44.87, srid=4326),
                                  modifie_le=datetime.datetime(2026, 11, 1, tzinfo=UTC))
        with patch("core.tasks.charger_adresses_departement_task.delay") as charger:
            with django_capture_on_commit_callbacks(execute=True):
                Crisis.objects.create(name="Feu", type="INCENDIE", location=Point(-1.2, 44.87, srid=4326),
                                      zone_communes=[LE_PORGE, VOISINE])
        charger.assert_called_once_with([VOISINE])
        # Close : plus rien n'est chargé à chaque modification.
        with patch("core.tasks.charger_adresses_departement_task.delay") as charger:
            with django_capture_on_commit_callbacks(execute=True):
                Crisis.objects.create(name="Close", type="INCENDIE", location=Point(-1.2, 44.87, srid=4326),
                                      zone_communes=["40001"], end_date=datetime.datetime(2026, 11, 2, tzinfo=UTC))
        charger.assert_not_called()

    def test_une_mairie_creee_charge_sa_commune(self, settings, django_capture_on_commit_callbacks):
        settings.CHARGEMENT_ADRESSES_AUTO = True
        itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
        with patch("core.tasks.charger_adresses_departement_task.delay") as charger, \
             patch.object(referentiel_adresses, "communes_d_institution", return_value={LE_PORGE}):
            with django_capture_on_commit_callbacks(execute=True):
                Institution.objects.create(nom="Mairie du Porge", type=itype, commune_code=LE_PORGE)
        charger.assert_called_once_with([LE_PORGE])

    def test_rien_n_est_charge_pendant_les_essais(self, django_capture_on_commit_callbacks):
        with patch("core.tasks.charger_adresses_departement_task.delay") as charger:
            with django_capture_on_commit_callbacks(execute=True):
                Crisis.objects.create(name="Feu", type="INCENDIE", location=Point(-1.2, 44.87, srid=4326), zone_communes=[LE_PORGE])
        charger.assert_not_called()

    def test_la_mise_a_jour_hebdomadaire_est_une_source(self):
        source = sources_ouvertes.SOURCES["ADRESSES_BAN"]
        assert source.intervalle == datetime.timedelta(days=7)
        assert list(sources_ouvertes.SOURCES)[-1] == "RAFALES_PREVISION"


@pytest.mark.django_db
class TestLecture:
    @pytest.fixture(autouse=True)
    def bourg(self):
        referentiel_adresses.charger_departement("33", {LE_PORGE}, flux=fichier(*BOURG))

    def test_les_plus_proches_dans_l_ordre(self):
        proches = referentiel_adresses.proches(44.87, -1.2001, rayon_m=100)
        assert [a.ban_id for a in proches] == ["33333_0010_00001", "33333_0010_00003"]
        assert proches[0].distance_m < proches[1].distance_m < 100

    def test_au_dela_de_60_m_ce_n_est_plus_son_adresse(self):
        assert referentiel_adresses.la_plus_proche(44.87, -1.2001).ban_id == "33333_0010_00001"
        assert referentiel_adresses.la_plus_proche(44.875, -1.2001) is None          # 550 m au nord

    def test_une_adresse_retiree_n_est_plus_proposee(self):
        AdresseBAN.objects.filter(ban_id="33333_0010_00001").update(retiree_le=datetime.datetime(2026, 11, 1, tzinfo=UTC))
        assert referentiel_adresses.la_plus_proche(44.87, -1.2001).ban_id == "33333_0010_00003"

    def test_le_registre_se_rattache_au_referentiel(self):
        releve = rattachement_adresses.Releve(LE_PORGE, "PROD")
        assert releve.disponible
        assert [a.ban_id for a in releve.chercher("3 bis pins")] == ["33333_0010_00003"]

    def test_le_releve_simple_ne_recharge_pas_une_commune_connue(self):
        with patch.object(referentiel_adresses, "telecharger") as telecharger:
            assert rattachement_adresses.relever_les_adresses(LE_PORGE) == 0
        telecharger.assert_not_called()


@pytest.mark.django_db
class TestPointage:
    def test_le_pointage_prend_l_adresse_chez_nous_sans_rien_demander_dehors(self, create_user):
        referentiel_adresses.charger_departement("33", {LE_PORGE}, flux=fichier(*BOURG))
        admin = create_user(username="admin-ref@test.fr", email="admin-ref@test.fr", type="ADMIN")
        client = APIClient()
        client.force_authenticate(user=admin)
        feu = Crisis.objects.create(name="Feu du Porge", type="INCENDIE", location=Point(-1.2, 44.87, srid=4326))
        with patch("core.views.commune_code_from_point", return_value=LE_PORGE), \
             patch("core.views_adresses._interroger", side_effect=AssertionError("aucun appel extérieur")):
            reponse = client.post(reverse("habitation-pointer"),
                                  {"crise": str(feu.id), "latitude": 44.87, "longitude": -1.2001}, format="json")
        assert reponse.status_code == 201, reponse.data
        maison = Habitation.objects.get()
        assert maison.ban_id == "33333_0010_00001" and maison.adresse == "1 Rue des Pins, 33680 Le Porge"
