"""La mini veille du territoire de l'application (27/11/2026) : la crise ou la manifestation en
cours, six rubriques en texte, lues par les détecteurs des alertes automatiques."""
import datetime

import pytest
from django.contrib.gis.geos import Point, Polygon
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import veille_terrain
from core.models import (
    CelluleOrage, Commune, ContactInstitution, Crisis, FoyerActif, InscriptionPoste, Institution, InstitutionType,
    Manifestation, PosteManifestation, Seisme,
)


def _client(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


@pytest.fixture
def monde(db, create_user):
    Commune.objects.update_or_create(code="42218", defaults={"nom": "Saint-Étienne", "centre_latitude": 45.43,
                                                              "centre_longitude": 4.39, "departement_code": "42"})
    Commune.objects.update_or_create(code="42095", defaults={"nom": "Firminy", "centre_latitude": 45.39,
                                                              "centre_longitude": 4.29, "departement_code": "42"})
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    mairie = Institution.objects.create(nom="Mairie veille (essai)", type=itype, commune_code="42218")
    lea = create_user(username="lea-veille@test.fr", email="lea-veille@test.fr", type="VOLUNTEER")
    ContactInstitution.objects.create(institution=mairie, utilisateur=lea, actif=True)
    crise = Crisis.objects.create(name="Orages (essai)", location=Point(4.39, 45.43), environment="PROD",
                                  zone_communes=["42218"], essai=True)
    return {"lea": lea, "crise": crise, "mairie": mairie}


def _cellule(identifiant, touchees=(), estimees=(), mmh=42, grele=False):
    maintenant = timezone.now()
    contour = Polygon.from_bbox((4.0, 45.0, 4.1, 45.1))
    return CelluleOrage.objects.create(
        identifiant=identifiant, heure_image=maintenant, centre=Point(4.05, 45.05, srid=4326), contour=contour,
        ligne=0, colonne=0, max_mmh=mmh, moyenne_mmh=20, surface_km2=30, grele_prevue=grele, releve_le=maintenant,
        communes_touchees=list(touchees), communes_estimees=list(estimees))


def _rubrique(reponse, code, zone=0):
    return next(r for r in reponse.data["zones"][zone]["rubriques"] if r["code"] == code)


@pytest.mark.django_db
class TestVeilleTerrain:
    def test_six_rubriques_meme_sur_une_base_vide(self, monde):
        r = _client(monde["lea"]).get(reverse("carte_terrain_veille"))
        assert r.status_code == 200
        (zone,) = r.data["zones"]
        assert zone["nature"] == "crise" and zone["nom"] == "Orages (essai)" and zone["communes"] == 1
        assert [x["code"] for x in zone["rubriques"]] == ["METEO", "ORAGES", "PREVISIONS", "EAU", "SEISMES", "FEUX"]
        assert all(x["evenements"] == [] and x["etat"] in ("ok", "perimee") for x in zone["rubriques"])

    def test_orage_sur_la_zone_et_orage_en_approche(self, monde):
        _cellule("sur", touchees=[{"code": "42218", "nom": "Saint-Étienne"}], mmh=35)
        _cellule("vient", estimees=[{"code": "42218", "nom": "Saint-Étienne", "dans_min": 25}], mmh=65, grele=True)
        # Une cellule qui ne vient pas chez nous n'apparaît pas.
        _cellule("ailleurs", estimees=[{"code": "75056", "nom": "Paris", "dans_min": 10}])
        orages = _rubrique(_client(monde["lea"]).get(reverse("carte_terrain_veille")), "ORAGES")
        titres = [e["titre"] for e in orages["evenements"]]
        assert len(titres) == 2
        # Le plus grave d'abord : grêle en approche, exceptionnel.
        assert titres[0].startswith("Orage en approche de Saint-Étienne, dans 25 min environ (65 mm/h, grêle")
        assert orages["evenements"][0]["niveau"] == "EXCEPTIONNEL"
        assert "pas une prévision" in orages["evenements"][0]["detail"]
        assert titres[1].startswith("Orage intense sur Saint-Étienne (35 mm/h")
        assert orages["evenements"][1]["niveau"] == "ALERTE"

    def test_seisme_proche_et_micro_seisme_ecarte(self, monde):
        maintenant = timezone.now()
        Seisme.objects.create(reference="s-fort", date=maintenant - datetime.timedelta(hours=1), location=Point(4.5, 45.5),
                              magnitude=3.9, releve_le=maintenant)
        Seisme.objects.create(reference="s-micro", date=maintenant - datetime.timedelta(hours=1), location=Point(4.4, 45.4),
                              magnitude=1.2, releve_le=maintenant)
        seismes = _rubrique(_client(monde["lea"]).get(reverse("carte_terrain_veille")), "SEISMES")
        (s,) = seismes["evenements"]
        assert s["titre"].startswith("Séisme de magnitude 3.9") and s["niveau"] == "ALERTE"

    def test_points_chauds_detectes(self, monde):
        maintenant = timezone.now()
        FoyerActif.objects.create(reference="f1", date=maintenant - datetime.timedelta(hours=2), location=Point(4.40, 45.44, srid=4326),
                                  confiance="nominale", source_fixe=False, releve_le=maintenant)
        feux = _rubrique(_client(monde["lea"]).get(reverse("carte_terrain_veille")), "FEUX")
        (f,) = feux["evenements"]
        assert "détection(s) satellite" in f["titre"] and f["niveau"] == "INFO"

    def test_la_manifestation_du_jour_a_sa_zone(self, monde, create_user):
        itype, _ = InstitutionType.objects.get_or_create(code="ASSOCIATION", defaults={"libelle": "Association"})
        asso = Institution.objects.create(nom="Asso veille (essai)", type=itype)
        maintenant = timezone.now()
        m = Manifestation.objects.create(institution=asso, titre="Course (essai)", statut="PUBLIEE", communes=["42095"],
                                         debut=maintenant - datetime.timedelta(hours=1), fin=maintenant + datetime.timedelta(hours=3))
        poste = PosteManifestation.objects.create(manifestation=m, intitule="Carrefour", places=2, debut=m.debut, fin=m.fin)
        InscriptionPoste.objects.create(poste=poste, utilisateur=monde["lea"], statut="INSCRIT")
        # Une autre, demain : pas encore.
        demain = Manifestation.objects.create(institution=asso, titre="Demain (essai)", statut="PUBLIEE", communes=["42095"],
                                              debut=maintenant + datetime.timedelta(days=1), fin=maintenant + datetime.timedelta(days=1, hours=3))
        InscriptionPoste.objects.create(poste=PosteManifestation.objects.create(manifestation=demain, intitule="Départ", places=1,
                                                                                debut=demain.debut, fin=demain.fin),
                                        utilisateur=monde["lea"], statut="INSCRIT")
        _cellule("firminy", touchees=[{"code": "42095", "nom": "Firminy"}], mmh=31)
        r = _client(monde["lea"]).get(reverse("carte_terrain_veille"))
        assert [(z["nature"], z["nom"]) for z in r.data["zones"]] == [("crise", "Orages (essai)"), ("manifestation", "Course (essai)")]
        assert _rubrique(r, "ORAGES", 0)["evenements"] == []                       # Saint-Étienne : rien
        assert "Firminy" in _rubrique(r, "ORAGES", 1)["evenements"][0]["titre"]

    def test_sans_crise_ni_manifestation_aucune_zone(self, db, create_user):
        seul = create_user(username="seul-veille@test.fr", email="seul-veille@test.fr", type="VOLUNTEER")
        assert _client(seul).get(reverse("carte_terrain_veille")).data["zones"] == []

    def test_reserve_aux_comptes_connectes(self, db):
        assert APIClient().get(reverse("carte_terrain_veille")).status_code == 401

    def test_crise_sans_communes_prend_celles_du_rayon(self, monde):
        crise = Crisis(name="Sans zone (essai)", location=Point(4.30, 45.39), radius=3, environment="PROD")
        perimetre = veille_terrain.perimetre_de_crise(crise)
        assert [c[0] for c in perimetre.communes] == ["42095"]


def _station(reference, lat, lon, ruptures=(), **champs):
    from core.models import StationCarburant
    return StationCarburant.objects.create(
        reference=reference, adresse=f"{reference} route de Lyon", ville="Ville", location=Point(lon, lat, srid=4326),
        carburants_disponibles=["Gazole", "SP95"], ruptures_temporaires=list(ruptures), releve_le=timezone.now(), **champs)


@pytest.mark.django_db
class TestStationsProches:
    def test_les_cinq_plus_proches_de_ma_position(self, monde):
        for n in range(7):
            _station(f"s{n}", 45.43 + n * 0.01, 4.39)            # tous les ~1,1 km vers le nord
        _station("loin", 46.5, 4.39)
        r = _client(monde["lea"]).get(reverse("carte_terrain_veille"), {"lat": "45.43", "lon": "4.39"})
        stations = r.data["stations"]
        assert stations["autour_de"] == "votre position"
        assert [s["adresse"].split()[0] for s in stations["resultats"]] == ["s0", "s1", "s2", "s3", "s4"]
        assert stations["resultats"][0]["distance_km"] == 0.0
        assert stations["resultats"][1]["carburants_disponibles"] == ["Gazole", "SP95"]

    def test_sans_position_autour_de_la_zone_meme_loin(self, monde):
        # Aucune dans les 15 premiers kilomètres : la recherche s'élargit.
        _station("rupture", 45.75, 4.39, ruptures=["E10"], automate_24_24=True)
        r = _client(monde["lea"]).get(reverse("carte_terrain_veille"))
        assert r.data["stations"]["autour_de"] == "Orages (essai)"
        (s,) = r.data["stations"]["resultats"]
        assert s["ruptures_temporaires"] == ["E10"] and s["automate_24_24"] is True
        assert 30 < s["distance_km"] < 40

    def test_une_position_invalide_est_ignoree(self, monde):
        r = _client(monde["lea"]).get(reverse("carte_terrain_veille"), {"lat": "999", "lon": "4.39"})
        assert r.data["stations"]["autour_de"] == "Orages (essai)"
