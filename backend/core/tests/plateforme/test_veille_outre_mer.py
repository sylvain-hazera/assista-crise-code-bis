"""Veille du territoire : vigilance météorologique outre-mer (15/11/2026). Même API et même clé
que la métropole, autre produit : une archive, un fichier par territoire. Voir la partie
« Outre-mer » de core/meteo_france.py. Aucun test n'appelle l'extérieur."""
import datetime
import io
import json
import zipfile
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from core import meteo_france, sources_ouvertes
from core.models import VigilanceMeteo

UTC = datetime.timezone.utc
MAINTENANT = datetime.datetime(2026, 11, 15, 11, 0, tzinfo=UTC)


def _phenomene(identifiant, couleur, tranches=None):
    return {"phenomenon_id": identifiant, "phenomenon_max_color_id": couleur,
            "timelaps_items": tranches or [{"color_id": couleur, "begin_time": "2026-11-15T09:21:00Z"}]}


def _niveaux(domaines, publie="2026-11-15T09:21:00Z"):
    return json.dumps({"warning_type": "vigilance", "update_time": publie, "timelaps": {"domain_ids": [
        {"domain_id": domaine, "max_color_id": max([p["phenomenon_max_color_id"] for p in phenomenes] + [1]),
         "phenomenon_items": phenomenes} for domaine, phenomenes in domaines]}}).encode()


def _tranches_horaires(couleur, debut_h, fin_h):
    return [{"color_id": couleur if debut_h <= heure < fin_h else 1,
             "begin_time": f"2026-11-15T{heure:02d}:00:00Z", "end_time": f"2026-11-15T{heure + 1:02d}:00:00Z"}
            for heure in range(8, 20)]


# La Réunion : un cyclone en violet sur une zone de 10 h à 14 h TU, vent en orange sur une autre.
REUNION = _niveaux([
    ("VIGI974-12", [_phenomene(10, 5, _tranches_horaires(5, 10, 14)), _phenomene(1, 2)]),
    ("VIGI974-53", [_phenomene(10, 3, _tranches_horaires(3, 10, 14)), _phenomene(1, 3), _phenomene(9, -1)]),
    ("VIGI974", [_phenomene(10, 5, _tranches_horaires(5, 10, 14)), _phenomene(12, 0)]),
], publie="2026-11-15T08:10:13Z")
BULLETIN_REUNION = json.dumps({
    "report_type": "vigilance", "report_subtype": "Bulletin de suivi", "domain_id": "VIGI974",
    "update_time": "2026-11-15T08:10:13Z", "text_bloc_items": [{"domain_id": "VIGI974", "text_items": [
        {"title": "Cyclone", "text": ["Le cyclone passe au plus près de l'île en milieu de journée.", " "]},
        {"title": "Vagues-submersion", "text": ["Pas de vigilance particulière."]}]}]}).encode()
MARTINIQUE_VERTE = _niveaux([("VIGI972-01", [_phenomene(2, 1), _phenomene(9, 0)]), ("VIGI972", [_phenomene(1, 1)])])
ILES_DU_NORD = _niveaux([("VIGI978-977-54", [_phenomene(2, 2)]), ("VIGI978-977", [_phenomene(2, 2)])])
SAINT_PIERRE = (b'<?xml version="1.0" encoding="UTF-8" ?>\n<CV><EV dateinsert="20261115144105" '
                b'dateprevue="20261116024105" producteur="SPM"> </EV>\n<DV dep="975" name="Archipel" coul="3">\n</DV>\n</CV>')


def _archive(**fichiers):
    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w") as archive:
        for nom, contenu in fichiers.items():
            archive.writestr(nom.replace("__", ".") if "__" in nom else nom, contenu)
    return sortie.getvalue()


ARCHIVE = _archive(**{
    "CDPV95_FMEE_.txt": REUNION, "CDPV96_FMEE_.txt": BULLETIN_REUNION, "CDPV85_TFFF_.txt": MARTINIQUE_VERTE,
    "CDPV85_TFFJ_.txt": ILES_DU_NORD, "NXFR33_LFVP_.xml": SAINT_PIERRE,
    "WXFP01_LFVP_.txt": "WXFP01 LFVP 241723\n\nVIGILANCE VERT\n".encode("latin-1"),
    "PBVB99_TFFF_.pdf": b"%PDF-1.4 ...", "CDPV85_SOCA_.txt": b"{ pas du json",
})


@pytest.fixture
def cle_meteo(tmp_path, monkeypatch):
    fichier = tmp_path / "cle"
    fichier.write_text("a.b.c")
    monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))


def _reponse_archive(contenu=ARCHIVE):
    return mock.Mock(status_code=200, content=contenu, raise_for_status=lambda: None)


class TestAnalyse:

    def test_le_niveau_d_un_territoire_est_le_plus_haut_de_ses_zones(self):
        reunion = meteo_france.analyser_outre_mer(ARCHIVE)["974"]

        assert reunion["publie_le"] == datetime.datetime(2026, 11, 15, 8, 10, 13, tzinfo=UTC)
        fiche = reunion["fiche"]
        assert fiche["couleur"] == 5
        # Le cyclone (violet) avant le vent (orange) ; ni le vert, ni le « sans objet » (-1, 0).
        assert [(p["id"], p["couleur"]) for p in fiche["phenomenes"]] == [(10, 5), (1, 3)]
        tranches = fiche["phenomenes"][0]["periodes"]
        assert len(tranches) == 4 and tranches[0]["debut"] == "2026-11-15T10:00:00Z"

    def test_le_bulletin_ne_reprend_pas_les_rubriques_sans_objet(self):
        bulletin = meteo_france.analyser_outre_mer(ARCHIVE)["974"]["bulletin"]

        assert [section["titre"] for section in bulletin] == ["Cyclone"]
        assert bulletin[0]["lignes"] == ["Le cyclone passe au plus près de l'île en milieu de journée."]

    def test_un_fichier_commun_a_deux_iles_les_renseigne_toutes_les_deux(self):
        territoires = meteo_france.analyser_outre_mer(ARCHIVE)

        assert territoires["977"]["fiche"]["couleur"] == 2 and territoires["978"]["fiche"]["couleur"] == 2
        assert territoires["977"]["fiche"]["phenomenes"][0]["id"] == 2

    def test_un_territoire_au_vert_est_ecrit_sans_phenomene(self):
        martinique = meteo_france.analyser_outre_mer(ARCHIVE)["972"]

        assert martinique["fiche"]["couleur"] == 1 and martinique["fiche"]["phenomenes"] == []
        assert martinique["bulletin"] == []

    def test_saint_pierre_et_miquelon_n_a_qu_une_couleur_d_ensemble(self):
        archipel = meteo_france.analyser_outre_mer(ARCHIVE)["975"]

        assert archipel["fiche"]["couleur"] == 3 and archipel["fiche"]["phenomenes"] == []
        assert archipel["publie_le"] == datetime.datetime(2026, 11, 15, 14, 41, 5, tzinfo=UTC)

    def test_un_fichier_illisible_n_emporte_pas_les_autres(self):
        """Dans l'archive : un fichier de Guyane tronqué, un PDF, un bulletin en texte libre."""
        territoires = meteo_france.analyser_outre_mer(ARCHIVE)

        assert sorted(territoires) == ["972", "974", "975", "977", "978"]

    def test_les_domaines_inconnus_ne_sont_rattaches_a_rien(self):
        assert meteo_france._territoires_du_domaine("VIGI974-12") == ["974"]
        assert meteo_france._territoires_du_domaine("VIGI978-977-54") == ["977", "978"]
        assert meteo_france._territoires_du_domaine("VIGI973-3") == ["973"]
        assert meteo_france._territoires_du_domaine("42") == [] and meteo_france._territoires_du_domaine("VIGI999") == []


class TestAnnonce:

    def test_les_niveaux_en_cours_se_lisent_comme_ceux_d_un_departement(self):
        fiche = meteo_france.analyser_outre_mer(ARCHIVE)["974"]["fiche"]

        niveaux = meteo_france.niveaux_en_cours({"J": fiche}, MAINTENANT)

        assert niveaux[10]["couleur"] == 5
        assert niveaux[10]["debut"] == datetime.datetime(2026, 11, 15, 10, 0, tzinfo=UTC)
        assert niveaux[10]["fin"] == datetime.datetime(2026, 11, 15, 14, 0, tzinfo=UTC)
        assert niveaux[1]["couleur"] == 3 and niveaux[1]["fin"] is None        # sans horaire de fin

    def test_l_annonce_dit_l_heure_du_territoire_et_connait_le_violet(self):
        niveau = {"couleur": 5, "debut": datetime.datetime(2026, 11, 15, 10, 0, tzinfo=UTC),
                  "fin": datetime.datetime(2026, 11, 15, 14, 0, tzinfo=UTC)}

        texte = meteo_france.texte_alerte("974", 10, niveau, MAINTENANT)

        # 14 h TU font 18 h à La Réunion, pas 15 h comme à Paris.
        assert texte == "Vigilance VIOLET cyclone - La Reunion (974), en cours jusqu'a 18h. Source Meteo-France."
        assert texte.isascii()

    def test_en_metropole_l_heure_reste_celle_de_paris(self):
        niveau = {"couleur": 3, "debut": datetime.datetime(2026, 11, 15, 10, 0, tzinfo=UTC),
                  "fin": datetime.datetime(2026, 11, 15, 14, 0, tzinfo=UTC)}

        assert "jusqu'a 15h" in meteo_france.texte_alerte("42", 1, niveau, MAINTENANT)

    def test_une_annonce_sans_horaire_de_fin_ne_l_invente_pas(self):
        texte = meteo_france.texte_alerte("972", 2, {"couleur": 3, "debut": MAINTENANT, "fin": None}, MAINTENANT)

        assert texte == "Vigilance ORANGE pluie-inondation - Martinique (972). Source Meteo-France."


@pytest.mark.django_db
class TestReleve:

    def test_la_source_est_inscrite_et_ses_annonces_partent_aussitot(self):
        source = sources_ouvertes.SOURCES["VIGILANCE_OUTRE_MER"]

        assert source.relever is meteo_france.relever_outre_mer and source.attribution == "Météo-France"
        assert list(sources_ouvertes.SOURCES)[:2] == ["VIGILANCE_METEO", "VIGILANCE_OUTRE_MER"]

    def test_les_territoires_rejoignent_la_table_des_departements(self, cle_meteo):
        VigilanceMeteo.objects.create(departement_code="42", couleur_j=3, publie_le=MAINTENANT, releve_le=MAINTENANT)

        with mock.patch("core.meteo_france.requests.get", return_value=_reponse_archive()) as appel:
            assert meteo_france.relever_outre_mer(MAINTENANT) == 5

        assert appel.call_args.args[0].endswith("/DPVigilance/v1/vigilanceom/flux/dernier")
        assert appel.call_args.kwargs["headers"]["apikey"] == "a.b.c"
        reunion = VigilanceMeteo.objects.get(pk="974")
        assert (reunion.couleur_j, reunion.couleur_j1) == (5, 1) and reunion.releve_le == MAINTENANT
        assert reunion.detail["J"]["phenomenes"][0]["id"] == 10 and "J1" not in reunion.detail
        assert reunion.bulletin[0]["titre"] == "Cyclone"
        # La métropole n'est pas touchée par ce relevé.
        assert VigilanceMeteo.objects.get(pk="42").couleur_j == 3

    def test_une_archive_sans_territoire_lisible_est_un_echec(self, cle_meteo):
        vide = _archive(**{"PBVB99_TFFF_.pdf": b"%PDF"})
        with mock.patch("core.meteo_france.requests.get", return_value=_reponse_archive(vide)):
            with pytest.raises(ValueError, match="aucun territoire"):
                meteo_france.relever_outre_mer(MAINTENANT)

    def test_sans_cle_rien_ne_part(self, monkeypatch, tmp_path):
        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(tmp_path / "absente"))
        with mock.patch("core.meteo_france.requests.get") as appel:
            with pytest.raises(meteo_france.CleAbsente):
                meteo_france.relever_outre_mer(MAINTENANT)
        appel.assert_not_called()


@pytest.mark.django_db
class TestLecture:

    def test_un_territoire_se_lit_comme_un_departement(self, api_client, cle_meteo):
        with mock.patch("core.meteo_france.requests.get", return_value=_reponse_archive()):
            meteo_france.relever_outre_mer(timezone.now())

        reponse = api_client.get(reverse("vigilance_meteo"), {"departement": "974"}).json()

        mien = reponse["mon_departement"]
        assert mien["nom"] == "La Réunion" and mien["couleur_j"] == 5 and reponse["perime"] is False
        assert reponse["couleurs"]["5"] == "violet" and reponse["phenomenes"]["10"] == "cyclone"
        assert {"974", "975", "977", "978"} <= {d["departement_code"] for d in reponse["departements"]}
        assert reponse["departements"][0]["departement_code"] == "974"        # le plus grave d'abord

    def test_un_territoire_dont_le_releve_a_cesse_est_dit_perime(self, api_client):
        """Métropole et outre-mer sont relevés à part : un relevé de métropole tout frais ne
        doit pas faire passer pour actuelle une vigilance outre-mer d'hier."""
        hier = timezone.now() - datetime.timedelta(hours=20)
        VigilanceMeteo.objects.create(departement_code="42", publie_le=timezone.now(), releve_le=timezone.now())
        VigilanceMeteo.objects.create(departement_code="974", couleur_j=3, publie_le=hier, releve_le=hier)

        outre_mer = api_client.get(reverse("vigilance_meteo"), {"departement": "974"}).json()
        metropole = api_client.get(reverse("vigilance_meteo"), {"departement": "42"}).json()

        assert outre_mer["perime"] is True and metropole["perime"] is False
