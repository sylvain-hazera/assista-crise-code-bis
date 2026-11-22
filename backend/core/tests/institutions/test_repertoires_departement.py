"""Répertoires de crise redistribués du département vers les EPCI et les communes (22/11/2026).

Les enregistrements reprennent la forme réelle de l'Annuaire de l'administration (champ `pivot`
avec la compétence territoriale) ; aucune requête ne part pendant les essais."""
import json
from unittest import mock

import pytest
from django.contrib.gis.geos import Polygon

from core import repertoires_departement as rep
from core.amorcage_departement import etape_annuaire
from core.models import Commune, Institution, InstitutionType, InterlocuteurAlertePCS, ReferentCollectivite


def _type(code):
    return InstitutionType.objects.get_or_create(code=code, defaults={"libelle": code})[0]


def _rec(type_service, nom, commune, servies=None, ident=None):
    return {"fields": {
        "id": ident or f"id-{type_service}-{commune}",
        "pivot": json.dumps([{"type_service_local": type_service, "code_insee_commune": servies or [commune]}]),
        "nom": nom, "adresse_courriel": "contact@exemple.fr",
        "telephone": json.dumps([{"valeur": "05 00 00 00 00", "description": ""}]),
        "adresse": json.dumps([{"numero_voie": "1 place", "code_postal": "33000", "nom_commune": "X"}]),
    }}


# Département fictif (99) : la base de test porte le référentiel réel, dont les EPCI de la Gironde.
# Trois communes : A et B dans l'EPCI E1, C dans E2. A est la commune de la brigade, qui sert A et B.
ANNUAIRE = {
    "99001": [_rec("mairie", "Mairie - A", "99001"), _rec("epci", "CC E1", "99001"),
              _rec("gendarmerie", "Brigade - A", "99001", servies=["99001", "99002"]),
              _rec("ccas", "CCAS - A", "99001")],
    "99002": [_rec("mairie", "Mairie - B", "99002"),
              _rec("gendarmerie", "Brigade - A", "99001", servies=["99001", "99002"])],
    "99003": [_rec("mairie", "Mairie - C", "99003"), _rec("epci", "CC E2", "99003"),
              _rec("sdis", "SDIS - Gironde", "99003"), _rec("sous_pref", "Sous-préfecture - C", "99003")],
}
COMMUNES = ["99001", "99002", "99003"]


@pytest.fixture
def cg(db):
    for code, epci in (("99001", "E1"), ("99002", "E1"), ("99003", "E2")):
        Commune.objects.update_or_create(code=code, defaults={"nom": code, "departement_code": "99", "epci_code": epci})
    return Institution.objects.create(nom="Conseil départemental — Gironde", type=_type("cg"), commune_code="99003",
                                      departement_code="99", secteur_override="departement")


def _annuaire(cg, arrondissements=None):
    with mock.patch("core.repertoires_departement.arrondissements",
                    return_value=arrondissements or {"99001": "991", "99002": "992", "99003": "992"}), \
         mock.patch("core.notifications_admin.notifier_administrateurs"):
        return etape_annuaire(cg, COMMUNES, interroger=lambda c: ANNUAIRE[c], pause=0)


def _institution(nom):
    return Institution.objects.get(nom=nom)


def _repertoire(nom):
    return {c.nom for c in InterlocuteurAlertePCS.objects.filter(institutions=_institution(nom))}


@pytest.mark.django_db
def test_chaque_service_va_aux_communes_qu_il_sert_et_a_leur_epci(cg):
    _annuaire(cg)
    # Service départemental : toutes les mairies et tous les EPCI.
    for nom in ("Mairie - A", "Mairie - B", "Mairie - C", "CC E1", "CC E2"):
        assert "SDIS - Gironde" in _repertoire(nom)
    # La brigade sert A et B (compétence publiée), pas C.
    assert "Brigade - A" in _repertoire("Mairie - A") and "Brigade - A" in _repertoire("Mairie - B")
    assert "Brigade - A" not in _repertoire("Mairie - C") and "Brigade - A" in _repertoire("CC E1")
    # Le CCAS : sa commune et son EPCI seulement.
    assert "CCAS - A" in _repertoire("Mairie - A") and "CCAS - A" not in _repertoire("Mairie - B")
    # La sous-préfecture : les communes de son arrondissement (B et C), d'après le COG.
    assert "Sous-préfecture - C" in _repertoire("Mairie - B") and "Sous-préfecture - C" not in _repertoire("Mairie - A")
    # Et tout reste au répertoire du conseil départemental.
    assert {"SDIS - Gironde", "Brigade - A", "CCAS - A", "Sous-préfecture - C"} <= {c.nom for c in InterlocuteurAlertePCS.objects.filter(institutions=cg)}


@pytest.mark.django_db
def test_rejouer_l_annuaire_ne_double_rien(cg):
    _annuaire(cg)
    avant = InterlocuteurAlertePCS.objects.count()
    resultat = _annuaire(cg)
    assert InterlocuteurAlertePCS.objects.count() == avant
    assert resultat["comptes"]["annuaire_ajoutes"] == 0 and resultat["comptes"]["rattachements"] == 0


@pytest.mark.django_db
def test_une_fiche_d_un_ancien_import_est_reprise_sans_doublon(cg):
    ancienne = InterlocuteurAlertePCS.objects.create(nom="SDIS - Gironde", organisme="sdis", categorie="SDIS")
    ancienne.institutions.add(cg)
    _annuaire(cg)
    ancienne.refresh_from_db()
    assert ancienne.cle_source == "id-sdis-99003"
    assert InterlocuteurAlertePCS.objects.filter(organisme="sdis").count() == 1


@pytest.mark.django_db
def test_une_fiche_saisie_a_la_main_n_est_jamais_touchee(cg):
    _annuaire(cg)
    mairie = _institution("Mairie - A")
    perso = InterlocuteurAlertePCS.objects.create(nom="Voisin vigilant", organisme="", categorie="AUTRE")
    perso.institutions.add(mairie)
    _annuaire(cg)
    perso.refresh_from_db()
    assert perso.cle_source == "" and list(perso.institutions.all()) == [mairie]


def _carre(x, y):
    return Polygon(((x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1), (x, y)), srid=4326)


@pytest.mark.django_db
def test_epci_mairies_et_voisines(cg):
    _annuaire(cg)
    # A et B se touchent ; C est isolée.
    contours = [{"code": "99001", "contour": json.loads(_carre(0, 0).geojson)},
                {"code": "99002", "contour": json.loads(_carre(1, 0).geojson)},
                {"code": "99003", "contour": json.loads(_carre(5, 5).geojson)}]
    carte = rep.voisines("99", lire=lambda url, timeout=60: json.dumps(contours).encode())
    assert carte == {"99001": {"99002"}, "99002": {"99001"}, "99003": set()}
    comptes = rep.distribuer(cg, lire_voisines=lambda dep: carte)
    assert comptes["fiches_epci"] == 2 and comptes["fiches_mairies"] == 3 and comptes["voisinages"] == 2
    fiches_a = InterlocuteurAlertePCS.objects.filter(institutions=_institution("Mairie - A"))
    assert {(c.nom, c.categorie) for c in fiches_a} >= {("CC E1", "EPCI_INTERCOMMUNALITE"), ("Mairie - B", "COMMUNE_VOISINE")}
    assert "Mairie - C" not in {c.nom for c in fiches_a}
    assert {"Mairie - A", "Mairie - B"} <= _repertoire("CC E1") and "Mairie - C" not in _repertoire("CC E1")
    assert {"CC E1", "CC E2", "Mairie - A"} <= {c.nom for c in InterlocuteurAlertePCS.objects.filter(institutions=cg)}
    # Rejouable.
    total = InterlocuteurAlertePCS.objects.count()
    assert rep.distribuer(cg, lire_voisines=lambda dep: carte)["rattachements"] == 0
    assert InterlocuteurAlertePCS.objects.count() == total


@pytest.mark.django_db
def test_la_copie_suit_le_referent_et_les_coordonnees(cg):
    _annuaire(cg)
    rep.distribuer(cg, lire_voisines=lambda dep: {})
    mairie = _institution("Mairie - B")
    ReferentCollectivite.objects.create(institution=mairie, nom="Julie Martin", fonction="Secrétaire de mairie",
                                        email="j.martin@commune.exemple", environment=mairie.environment)
    assert rep.resynchroniser(mairie) == 1
    copie = InterlocuteurAlertePCS.objects.get(cle_source=f"institution:{mairie.id}")
    assert copie.email == "j.martin@commune.exemple" and copie.notes.startswith("Référent : Julie Martin")


def test_competence_lue_dans_le_pivot():
    record = _rec("gendarmerie", "Brigade", "99001", servies=["99002", "99001", ""])
    assert rep.competence(record, "gendarmerie") == ["99001", "99002"]
    assert rep.competence(record, "ccas") == []


def test_arrondissements_d_apres_le_cog():
    from django.core.cache import cache
    cache.delete("cog:arrondissements:33")
    csv_cog = ('"TYPECOM","COM","REG","DEP","CTCD","ARR","TNCC","NCC","NCCENR","LIBELLE","CAN","COMPARENT"\n'
               '"COM","33063","75","33","33D","992","0","BORDEAUX","Bordeaux","Bordeaux","3397",""\n'
               '"COMD","33999","75","33","33D","992","0","X","X","X","",""\n'
               '"COM","42218","84","42","42D","422","0","ST","St","St","",""\n')
    assert rep.arrondissements("33", lire=lambda url: csv_cog.encode()) == {"33063": "992"}
    cache.delete("cog:arrondissements:33")
