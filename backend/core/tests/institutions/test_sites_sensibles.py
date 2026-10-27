"""Sites sensibles d'une commune : connecteurs open data, règles d'import et vue.

Ce que ces tests tiennent en place, dans l'ordre d'importance :
1. rien n'entre jamais ailleurs qu'en PROPOSE (l'open data propose, la commune décide) ;
2. un ré-import n'écrase JAMAIS le travail d'un agent ;
3. les lignes mortes des sources (établissement fermé, ICPE sortie du régime) ne remontent pas ;
4. aucun test ne touche le réseau : chaque connecteur est testé sur des enregistrements réels
   recopiés des API, et la vue sur des connecteurs remplacés."""
import datetime
import io
from unittest.mock import patch

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    CategorieSiteSensible, ContactInstitution, ImportOpenData, Institution, InstitutionType,
    PointOperationnel, PointType, SiteSensible, SourceSiteSensible, StatutImportOpenData,
    StatutSiteSensible,
)
from core.opendata import ecoles, equipements, finess, icpe
from core.opendata.base import SitePropose
from core.sites_sensibles import (
    _parse_date, enregistrer_proposes, executer_import, synthese_par_categorie,
)


# ── Fixtures ────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(
        nom="Mairie de Châteauneuf-du-Faou (sites sensibles)", type=itype,
        commune_code="29027", commune_nom="Châteauneuf-du-Faou",
    )


@pytest.fixture
def agent_client(create_user, mairie):
    user = create_user(username="agent-sites@test.fr", email="agent-sites@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=mairie, utilisateur=user, actif=True)
    client = APIClient()
    client.force_authenticate(user=user)
    return client, user


def _propose(source_id="0290252S", nom="Collège de l'Aulne", **kwargs):
    defauts = dict(
        source=SourceSiteSensible.ANNUAIRE_EDUCATION,
        categorie=CategorieSiteSensible.ENSEIGNEMENT,
        adresse="29 rue des Fontaines, 29520 Châteauneuf-du-Faou",
        latitude=48.1908, longitude=-3.8180,
        telephone="0298730000",
        attributs={"uai": source_id, "date_maj_source": "2026-10-27"},
    )
    defauts.update(kwargs)
    return SitePropose(source_id=source_id, nom=nom, **defauts)


# ── Dates de fraîcheur ──────────────────────────────────────────────────────────────────────
class TestParseDate:
    def test_formats_des_sources(self):
        assert _parse_date("2026-10-27") == datetime.date(2026, 10, 27)
        assert _parse_date("27/10/2026") == datetime.date(2026, 10, 27)
        assert _parse_date("2026/10/27") == datetime.date(2026, 10, 27)
        # Géorisques colle l'heure derrière la date : « 2024-09-04/14-48-00 ».
        assert _parse_date("2024-09-04/14-48-00") == datetime.date(2024, 9, 4)

    def test_valeurs_inutilisables(self):
        assert _parse_date(None) is None
        assert _parse_date("") is None
        assert _parse_date("jamais") is None

    def test_sentinelle_1900_ignoree(self):
        """Vu en direct sur une ICPE réelle : `date_maj` à 1900-02-12. Afficher « données du
        12/02/1900 » tromperait l'agent plus que ne rien afficher."""
        assert _parse_date("1900-02-12") is None


# ── Enregistrement et ré-import ─────────────────────────────────────────────────────────────
@pytest.mark.django_db
class TestEnregistrerProposes:
    def test_cree_en_propose_avec_coordonnees(self, mairie):
        resultat = enregistrer_proposes(mairie, "PROD", "29027", "Châteauneuf-du-Faou", [_propose()])

        assert resultat == {"crees": 1, "mis_a_jour": 0, "inchanges": 0, "total": 1}
        site = SiteSensible.objects.get()
        assert site.statut == StatutSiteSensible.PROPOSE
        assert site.commune_code == "29027"
        assert site.date_source == datetime.date(2026, 10, 27)
        assert round(site.location.y, 4) == 48.1908
        assert round(site.location.x, 4) == -3.8180

    def test_sans_coordonnees_reste_sans_point(self, mairie):
        enregistrer_proposes(mairie, "PROD", "29027", None, [_propose(latitude=None, longitude=None)])
        assert SiteSensible.objects.get().location is None

    def test_reimport_ne_duplique_pas(self, mairie):
        enregistrer_proposes(mairie, "PROD", "29027", None, [_propose()])
        resultat = enregistrer_proposes(mairie, "PROD", "29027", None, [_propose()])

        assert SiteSensible.objects.count() == 1
        assert resultat["inchanges"] == 1
        assert resultat["crees"] == 0

    def test_reimport_preserve_le_travail_de_lagent(self, mairie):
        """La règle la plus importante du module : « Actualiser » ne doit jamais détruire des
        heures de relecture."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [_propose()])
        site = SiteSensible.objects.get()
        site.nom = "Collège de l'Aulne — bâtiment B"
        site.adresse = "29 rue des Fontaines (entrée arrière)"
        site.statut = StatutSiteSensible.RETENU
        site.effectif_estime = 320
        site.commentaire = "Clés chez le gardien"
        site.save()

        enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(nom="COLLEGE DE L'AULNE", adresse="29 rue des Fontaines BP 23")
        ])

        site.refresh_from_db()
        assert site.nom == "Collège de l'Aulne — bâtiment B"
        assert site.adresse == "29 rue des Fontaines (entrée arrière)"
        assert site.statut == StatutSiteSensible.RETENU
        assert site.effectif_estime == 320
        assert site.commentaire == "Clés chez le gardien"

    def test_reimport_rafraichit_les_attributs_de_la_source(self, mairie):
        """Un site qui passe Seveso seuil haut doit le dire, même si l'agent a déjà statué."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(source=SourceSiteSensible.ICPE, categorie=CategorieSiteSensible.INDUSTRIE,
                     source_id="0005520931", nom="SOCOPA VIANDES",
                     attributs={"statut_seveso": None, "date_maj_source": "2024-09-04"})
        ])
        site = SiteSensible.objects.get()
        site.statut = StatutSiteSensible.ECARTE
        site.save()

        resultat = enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(source=SourceSiteSensible.ICPE, categorie=CategorieSiteSensible.INDUSTRIE,
                     source_id="0005520931", nom="SOCOPA VIANDES",
                     attributs={"statut_seveso": "Seveso seuil haut", "date_maj_source": "2026-10-01"})
        ])

        site.refresh_from_db()
        assert resultat["mis_a_jour"] == 1
        assert site.attributs["statut_seveso"] == "Seveso seuil haut"
        assert site.date_source == datetime.date(2026, 10, 1)
        # La décision de l'agent n'a pas bougé pour autant.
        assert site.statut == StatutSiteSensible.ECARTE

    def test_reimport_complete_ce_qui_etait_vide(self, mairie):
        enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(adresse="", telephone="", latitude=None, longitude=None)
        ])
        enregistrer_proposes(mairie, "PROD", "29027", None, [_propose()])

        site = SiteSensible.objects.get()
        assert site.adresse.startswith("29 rue des Fontaines")
        assert site.telephone == "0298730000"
        assert site.location is not None

    def test_isolation_par_environnement(self, mairie):
        enregistrer_proposes(mairie, "PROD", "29027", None, [_propose()])
        enregistrer_proposes(mairie, "DEMO", "29027", None, [_propose()])
        assert SiteSensible.objects.count() == 2


# ── Connecteurs : enregistrements recopiés des API réelles ──────────────────────────────────
class TestConnecteurEcoles:
    ENREGISTREMENT = {
        "identifiant_de_l_etablissement": "0290252S",
        "nom_etablissement": "Collège Notre-Dame des Portes",
        "type_etablissement": "Collège",
        "statut_public_prive": "Privé",
        "adresse_1": "36 rue Paul Serusier", "adresse_2": None, "adresse_3": None,
        "code_postal": "29520", "nom_commune": "Châteauneuf-du-Faou",
        "latitude": 48.18793, "longitude": -3.81025,
        "telephone": "0298817104", "hebergement": 0, "restauration": 1,
        "etat": "OUVERT", "date_maj_ligne": "2026-10-27",
    }

    def test_mapping(self):
        site = ecoles._vers_site(self.ENREGISTREMENT)
        assert site.source_id == "0290252S"
        assert site.categorie == CategorieSiteSensible.ENSEIGNEMENT
        assert site.adresse == "36 rue Paul Serusier, 29520 Châteauneuf-du-Faou"
        assert site.attributs["restauration"] == 1

    def test_etablissement_ferme_ignore(self):
        assert ecoles._vers_site({**self.ENREGISTREMENT, "etat": "FERME"}) is None

    def test_sans_uai_ignore(self):
        """Sans identifiant stable, impossible de ré-importer sans dupliquer."""
        assert ecoles._vers_site({**self.ENREGISTREMENT, "identifiant_de_l_etablissement": None}) is None


class TestConnecteurIcpe:
    ENREGISTREMENT = {
        "codeAIOT": "0005520931", "raisonSociale": "SOCOPA VIANDES",
        "adresse1": "ZAC KROAZ LESNEVEN", "adresse2": None, "adresse3": None,
        "codePostal": "29520", "commune": "Châteauneuf-du-Faou",
        "latitude": 48.199197, "longitude": -3.823971,
        "regime": "Autorisation", "statutSeveso": "Non Seveso", "ied": True, "industrie": True,
        "siret": "45370970100024", "date_maj": "2024-09-04/14-48-00",
    }

    def test_mapping(self):
        site = icpe._vers_site(self.ENREGISTREMENT)
        assert site.source_id == "0005520931"
        assert site.categorie == CategorieSiteSensible.INDUSTRIE
        assert site.attributs["ied"] is True
        assert site.attributs["date_maj_source"] == "2024-09-04"

    def test_non_icpe_ignore(self):
        """Géorisques garde les établissements sortis du régime : ils n'ont rien à faire dans un
        plan de sauvegarde."""
        assert icpe._vers_site({**self.ENREGISTREMENT, "regime": "Non ICPE"}) is None

    def test_abattoir_reste_un_site_industriel(self):
        """Un abattoir manipule des animaux mais se planifie comme une usine : il ne doit pas
        basculer en élevage sous prétexte que ses rubriques parlent de bêtes."""
        site = icpe._vers_site({**self.ENREGISTREMENT, "rubriques": [
            {"numeroRubrique": "3641", "nature": "Exploitation d’abattoirs",
             "quantiteTotale": "480.000", "unite": "t/j"},
            {"numeroRubrique": "4735", "nature": "Ammoniac", "quantiteTotale": "1.5",
             "unite": "t"},
        ]})
        assert site.categorie == CategorieSiteSensible.INDUSTRIE
        assert site.attributs["cheptel"] == []
        assert site.attributs["especes"] == []


class TestElevagesIcpe:
    """Les élevages sortent de la même API que les usines, et sont la raison d'être d'une
    catégorie à part : la protection des animaux est une mission du plan de sauvegarde. Un
    élevage rangé en « site industriel » au milieu de cinquante stations-service est un élevage
    que personne ne retrouve le jour où il faut évacuer un cheptel ou gérer une coupure longue.

    Tous les enregistrements ci-dessous sont recopiés de l'API Géorisques (communes 29027 et
    29019) : ils documentent aussi ce que la source ne dit pas."""

    PORCS = {
        "codeAIOT": "0004310066", "raisonSociale": "GAEC BAUT",
        "adresse1": "KERDUDAL", "codePostal": "29520", "commune": "Châteauneuf-du-Faou",
        "latitude": 48.158, "longitude": -3.843,
        "regime": "Enregistrement", "statutSeveso": "Non Seveso", "ied": False,
        "industrie": False, "codeNaf": "01", "bovins": False, "porcs": True, "volailles": False,
        "etatActivite": "En exploitation avec titre", "date_maj": "2024-09-04/14-48-00",
        "rubriques": [{"numeroRubrique": "2102",
                       "nature": "Elevage de porcs de plus de 450 animaux-équivalents",
                       "alinea": "1", "regimeAutoriseAlinea": "Enregistrement",
                       "quantiteTotale": "1232.0", "unite": "Animaux-Eq"}],
    }

    def test_elevage_classe_a_part_avec_son_cheptel(self):
        site = icpe._vers_site(self.PORCS)
        assert site.categorie == CategorieSiteSensible.ELEVAGE
        assert site.attributs["especes"] == ["porcs"]
        assert site.attributs["cheptel"] == [{
            "rubrique": "2102",
            "nature": "Elevage de porcs de plus de 450 animaux-équivalents",
            "espece": "porcs", "quantite": 1232.0, "unite": "Animaux-Eq",
        }]

    def test_rubrique_ied_sans_indicateur_despece(self):
        """Géorisques laisse ses trois indicateurs (`bovins`/`porcs`/`volailles`) à faux sur des
        élevages industriels que la rubrique désigne noir sur blanc : EARL MADEC, 56 000
        emplacements de volailles, les trois indicateurs à faux."""
        site = icpe._vers_site({
            "codeAIOT": "0004310112", "raisonSociale": "EARL MADEC", "regime": "Autorisation",
            "codePostal": "29520", "commune": "Châteauneuf-du-Faou", "statutSeveso": "Non Seveso",
            "ied": True, "industrie": True, "codeNaf": None,
            "bovins": False, "porcs": False, "volailles": False,
            "rubriques": [{"numeroRubrique": "3660",
                           "nature": "avec plus de 40 000 emplacements pour les volailles",
                           "quantiteTotale": "56000.000", "unite": "u",
                           "dateMotif": "21/10/2013"}],
        })
        assert site.categorie == CategorieSiteSensible.ELEVAGE
        assert site.attributs["especes"] == ["volailles"]
        assert site.attributs["cheptel"][0]["quantite"] == 56000.0

    def test_indicateur_despece_sans_rubrique(self):
        """L'inverse arrive aussi : l'indicateur est vrai, la rubrique absente. L'élevage doit
        remonter quand même, sans effectif — « on ne sait pas combien » reste exploitable,
        « on ne sait pas qu'il existe » non."""
        site = icpe._vers_site({**self.PORCS, "rubriques": [], "codeNaf": None})
        assert site.categorie == CategorieSiteSensible.ELEVAGE
        assert site.attributs["especes"] == ["porcs"]
        assert site.attributs["cheptel"] == []

    def test_exploitation_declaree_sans_rubrique_ni_naf(self):
        """Le cas le plus fréquent en commune rurale, et celui qui faisait tout rater : régime
        « Autres régimes », aucune rubrique détaillée, aucun code NAF, aucun indicateur. Seule
        la forme juridique dit la vérité — un GAEC, une EARL ou une SCEA ne peut rien être
        d'autre qu'une exploitation agricole."""
        for raison_sociale in ("KERGANEZ (GAEC de)", "EARL DE TRAON BIHAN", "CONAN (SCEA)"):
            site = icpe._vers_site({
                "codeAIOT": "0000100001", "raisonSociale": raison_sociale,
                "regime": "Autres régimes", "codePostal": "29520", "commune": "Plonévez",
                "statutSeveso": None, "ied": False, "industrie": False, "codeNaf": None,
                "bovins": False, "porcs": False, "volailles": False, "rubriques": [],
            })
            assert site.categorie == CategorieSiteSensible.ELEVAGE, raison_sociale

    def test_forme_juridique_voisine_ne_trompe_pas(self):
        """« EURL » n'est pas « EARL » : la frontière de mot compte, sinon toutes les EURL de la
        commune deviendraient des fermes."""
        site = icpe._vers_site({
            "codeAIOT": "0000100002", "raisonSociale": "AUGUSTE B EURL",
            "regime": "Autorisation", "codePostal": "29200", "commune": "Brest",
            "statutSeveso": None, "ied": False, "industrie": True, "codeNaf": "45",
            "rubriques": [],
        })
        assert site.categorie == CategorieSiteSensible.INDUSTRIE

    def test_exploitation_hors_regime_remonte_quand_meme(self):
        """Une ferme repassée sous les seuils ICPE garde ses animaux. On écarte les « Non ICPE »
        — mais pas celles-là, justement parce qu'il faut savoir qu'elles sont là."""
        site = icpe._vers_site({**self.PORCS, "regime": "Non ICPE"})
        assert site is not None
        assert site.categorie == CategorieSiteSensible.ELEVAGE

    def test_parc_animalier(self):
        """Océanopolis (Brest) relève de la rubrique 2140. Ce ne sont pas des bêtes de ferme,
        mais une coupure électrique longue les tue aussi."""
        site = icpe._vers_site({
            "codeAIOT": "0001900100", "raisonSociale": "OCEANOPOLIS", "regime": "Autorisation",
            "codePostal": "29200", "commune": "Brest", "statutSeveso": "Non Seveso",
            "ied": False, "industrie": False, "codeNaf": None, "rubriques": [
                {"numeroRubrique": "2140",
                 "nature": "Présentation au public d’animaux d’espèces non domestiques",
                 "quantiteTotale": None, "unite": None},
            ],
        })
        assert site.categorie == CategorieSiteSensible.ELEVAGE
        assert site.attributs["especes"] == ["animaux d'espèces non domestiques"]
        assert site.attributs["cheptel"][0]["quantite"] is None

    def test_deux_rubriques_du_meme_batiment_restent_brutes(self):
        """EARL MERCIER porte deux fois 50 000 volailles (autorisation puis enregistrement du
        même bâtiment). Le connecteur ne tranche pas : il remonte les deux lignes telles quelles,
        c'est l'affichage qui dédoublonne pour ne pas annoncer 100 000 animaux."""
        rubrique = {"numeroRubrique": "2111", "nature": "Elevages de plus de 30 000 volailles",
                    "quantiteTotale": "50000.000", "unite": "u"}
        site = icpe._vers_site({**self.PORCS, "raisonSociale": "EARL MERCIER",
                                "rubriques": [rubrique, dict(rubrique)]})
        assert len(site.attributs["cheptel"]) == 2
        assert site.attributs["especes"] == ["porcs", "volailles"]

    def test_etat_dactivite_remonte_sans_filtrer(self):
        """« En fin d'exploitation » n'est pas « vide » : le temps de la remise en état, il y a
        encore du stock, parfois des animaux. On le montre, on ne décide pas à la place."""
        site = icpe._vers_site({**self.PORCS, "etatActivite": "En fin d'exploitation"})
        assert site is not None
        assert site.attributs["etat_activite"] == "En fin d'exploitation"


class TestConnecteurEquipements:
    ENREGISTREMENT = {
        "numero": "I290270001", "nom": "Complexe sportif et culturel Ar Sterenn",
        "adresse": "rue du gymnase", "cp": "29520", "commune": "Châteauneuf-du-Faou",
        "coordonnees": {"lat": 48.192002, "lon": -3.817959},
        "acces_handi": ["Handicap moteur"], "install_nb": 1, "maj_date": "2025-03-31",
    }

    def test_mapping(self):
        site = equipements._vers_site(self.ENREGISTREMENT)
        assert site.categorie == CategorieSiteSensible.RASSEMBLEMENT
        assert site.latitude == 48.192002
        assert site.attributs["acces_handicap"] == ["Handicap moteur"]

    def test_sans_numero_ignore(self):
        assert equipements._vers_site({**self.ENREGISTREMENT, "numero": None}) is None


class TestConnecteurFiness:
    EGE = {
        "informationsGeneralesEGE": {
            "numFinessEge": "290029289", "nomEgeLong": "EHPAD RESIDENCE LE VERGER D'YVONNE",
            "nomEgeCourt": "EHPAD LE VERGER", "dateFermeture": None,
            "dateOuverture": "1977-01-16", "siret": "40094447600185",
        },
        "categorieentiteGeographiqueExercice": "500",
        "etatObjet": "A",
        "adresse": [{
            "cogCommune": "29027", "ligneQuatre": "1 RUE SIMONE VEIL",
            "codePostal": "29520", "ligneAcheminement": "CHATEAUNEUF DU FAOU",
            "coordonneesGeographique": {"directionLatitude": "48.191997",
                                        "directionLongitude": "-3.813085"},
        }],
        "contact": [{"telecom": {"telephone": "0298818096"}}],
    }
    DATE = datetime.date(2026, 10, 27)

    def test_mapping(self):
        site = finess._vers_site(self.EGE, self.EGE["adresse"][0], "ASSOCIATION X", self.DATE)
        assert site.source_id == "290029289"
        assert site.categorie == CategorieSiteSensible.SOINS
        assert site.adresse == "1 RUE SIMONE VEIL, 29520 CHATEAUNEUF DU FAOU"
        # Coordonnées BAN du producteur, rendues en texte dans le flux.
        assert site.latitude == 48.191997
        assert site.telephone == "0298818096"
        assert site.attributs["entite_juridique"] == "ASSOCIATION X"

    def test_etablissement_ferme_ignore(self):
        """FINESS conserve l'historique : sur une commune réelle, la moitié des entités sont
        fermées (pharmacies radiées en 2009…)."""
        ege = {**self.EGE, "informationsGeneralesEGE": {
            **self.EGE["informationsGeneralesEGE"], "dateFermeture": "2009-06-22"}}
        assert finess._vers_site(ege, ege["adresse"][0], None, self.DATE) is None

    def test_entite_inactive_ignoree(self):
        ege = {**self.EGE, "etatObjet": "I"}
        assert finess._vers_site(ege, ege["adresse"][0], None, self.DATE) is None

    def test_adresse_dune_autre_commune_non_retenue(self):
        assert finess._adresse_de_la_commune(self.EGE, "29026") is None
        assert finess._adresse_de_la_commune(self.EGE, "29027") is not None

    def test_date_depuis_titre(self):
        assert finess._date_depuis_titre("finess-structures-journalier-20261027.json.gz") == self.DATE
        assert finess._date_depuis_titre("finess-structures-mensuel-202609.json.gz") == datetime.date(2026, 9, 1)
        assert finess._date_depuis_titre("sans-date.json.gz") is None


class TestLectureEnFlot:
    """`_objets_du_tableau` lit un tableau JSON sans charger le document : c'est ce qui permet de
    traiter les ~750 Mo décompressés du flux FINESS. Volontairement indépendant de la mise en
    forme du fichier — une évolution de l'indentation chez le producteur ne doit pas le casser."""

    def _lire(self, texte, taille=8):
        with patch.object(finess, "TAILLE_LECTURE", taille):
            return list(finess._objets_du_tableau(io.StringIO(texte), "pmej"))

    def test_document_indente(self):
        texte = '{\n  "schemaVersion" : "v1",\n  "pmej" : [ {\n    "a" : 1\n  }, {\n    "a" : 2\n  } ]\n}'
        assert self._lire(texte) == [{"a": 1}, {"a": 2}]

    def test_document_compact(self):
        assert self._lire('{"pmej":[{"a":1},{"a":2},{"a":3}]}') == [{"a": 1}, {"a": 2}, {"a": 3}]

    def test_objets_imbriques(self):
        texte = '{"pmej":[{"ege":[{"x":[1,2]}],"nom":"a, b"},{"ege":[]}]}'
        assert self._lire(texte) == [{"ege": [{"x": [1, 2]}], "nom": "a, b"}, {"ege": []}]

    def test_tableau_vide(self):
        assert self._lire('{"pmej":[]}') == []

    def test_cle_absente(self):
        assert self._lire('{"autre":[{"a":1}]}') == []

    def test_cle_a_cheval_sur_deux_blocs(self):
        """Le marqueur peut tomber à la frontière de deux lectures : le tampon garde un
        chevauchement pour ne pas le perdre."""
        assert self._lire('{"x":"' + "y" * 50 + '","pmej":[{"a":1}]}', taille=4) == [{"a": 1}]


# ── Orchestration ───────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
class TestExecuterImport:
    def test_trace_le_resultat(self, mairie):
        with patch.object(ecoles, "collecter", return_value=[_propose()]):
            resultat = executer_import(
                mairie, SourceSiteSensible.ANNUAIRE_EDUCATION, "29027", "Châteauneuf-du-Faou", "PROD")

        assert resultat["crees"] == 1
        trace = ImportOpenData.objects.get()
        assert trace.statut == StatutImportOpenData.TERMINEE
        assert trace.resultat["crees"] == 1
        assert trace.date_fin is not None

    def test_source_en_panne_nempeche_rien(self, mairie):
        """Une API injoignable doit laisser une trace d'échec, pas faire remonter d'exception :
        les autres sources de l'import doivent continuer."""
        with patch.object(ecoles, "collecter", side_effect=RuntimeError("502 Bad Gateway")):
            resultat = executer_import(
                mairie, SourceSiteSensible.ANNUAIRE_EDUCATION, "29027", None, "PROD")

        assert resultat["total"] == 0
        trace = ImportOpenData.objects.get()
        assert trace.statut == StatutImportOpenData.ECHEC
        assert "502" in trace.erreur

    def test_synthese_par_categorie(self, mairie):
        enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(), _propose(source_id="autre", nom="École B"),
            _propose(source=SourceSiteSensible.ICPE, categorie=CategorieSiteSensible.INDUSTRIE,
                     source_id="icpe-1", nom="Usine"),
        ])
        SiteSensible.objects.filter(nom="Usine").update(statut=StatutSiteSensible.RETENU)

        synthese = synthese_par_categorie(mairie, "PROD")

        assert synthese["a_relire"] == 2
        par_categorie = {ligne["categorie"]: ligne for ligne in synthese["par_categorie"]}
        assert par_categorie[CategorieSiteSensible.ENSEIGNEMENT][StatutSiteSensible.PROPOSE] == 2
        assert par_categorie[CategorieSiteSensible.INDUSTRIE][StatutSiteSensible.RETENU] == 1


# ── Vue ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
class TestSiteSensibleViewSet:
    def test_anonyme_refuse(self, api_client):
        assert api_client.get(reverse("sitesensible-list")).status_code in (
            status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN)

    def test_citoyen_refuse(self, api_client, create_user):
        user = create_user(username="citoyen-sites@test.fr", email="citoyen-sites@test.fr",
                           type="UTIL_SIMPLE")
        api_client.force_authenticate(user=user)
        assert api_client.get(reverse("sitesensible-list")).status_code == status.HTTP_403_FORBIDDEN

    def test_ne_voit_que_son_institution(self, agent_client, mairie, db):
        client, _ = agent_client
        autre_type, _ = InstitutionType.objects.get_or_create(
            code="MAIRIE", defaults={"libelle": "Mairie"})
        autre = Institution.objects.create(nom="Mairie voisine sites", type=autre_type,
                                           commune_code="29026")
        enregistrer_proposes(mairie, "PROD", "29027", None, [_propose()])
        enregistrer_proposes(autre, "PROD", "29026", None, [_propose(source_id="voisine")])

        reponse = client.get(reverse("sitesensible-list"))

        assert reponse.status_code == status.HTTP_200_OK
        resultats = reponse.data["results"] if isinstance(reponse.data, dict) else reponse.data
        assert [s["source_id"] for s in resultats] == ["0290252S"]

    def test_importer_une_source(self, agent_client, mairie):
        client, _ = agent_client
        with patch.object(ecoles, "collecter", return_value=[_propose()]):
            reponse = client.post(reverse("sitesensible-importer"),
                                  {"sources": [SourceSiteSensible.ANNUAIRE_EDUCATION]},
                                  format="json")

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["resultats"][SourceSiteSensible.ANNUAIRE_EDUCATION]["crees"] == 1
        assert SiteSensible.objects.get().statut == StatutSiteSensible.PROPOSE

    def test_importer_finess_part_en_tache_de_fond(self, agent_client, mairie):
        """FINESS ne tient pas dans une requête HTTP : la vue doit déléguer, pas télécharger
        50 Mo pendant que le navigateur attend."""
        client, _ = agent_client
        with patch("core.tasks.importer_sites_sensibles_task.delay") as delay:
            reponse = client.post(reverse("sitesensible-importer"),
                                  {"sources": [SourceSiteSensible.FINESS]}, format="json")

        assert reponse.data["resultats"][SourceSiteSensible.FINESS] == {"asynchrone": True}
        assert delay.called
        trace = ImportOpenData.objects.get()
        assert trace.statut == StatutImportOpenData.EN_COURS

    def test_importer_sans_commune_refuse(self, agent_client, mairie):
        client, _ = agent_client
        Institution.objects.filter(pk=mairie.pk).update(commune_code=None)
        reponse = client.post(reverse("sitesensible-importer"), {"sources": ["ICPE"]}, format="json")
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST

    def test_importer_source_inconnue_refuse(self, agent_client, mairie):
        client, _ = agent_client
        reponse = client.post(reverse("sitesensible-importer"),
                              {"sources": ["CADASTRE_IMAGINAIRE"]}, format="json")
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "CADASTRE_IMAGINAIRE" in reponse.data["error"]

    def test_statuer_trace_lauteur(self, agent_client, mairie):
        client, user = agent_client
        enregistrer_proposes(mairie, "PROD", "29027", None, [_propose()])
        site = SiteSensible.objects.get()

        reponse = client.patch(reverse("sitesensible-detail", args=[site.id]),
                               {"statut": StatutSiteSensible.RETENU, "effectif_estime": 320},
                               format="json")

        assert reponse.status_code == status.HTTP_200_OK
        site.refresh_from_db()
        assert site.statut == StatutSiteSensible.RETENU
        assert site.effectif_estime == 320
        assert site.valide_par_id == user.id

    def test_la_provenance_nest_pas_modifiable(self, agent_client, mairie):
        """Un agent corrige le nom et l'adresse, jamais la source : c'est elle qui permet de
        ré-importer sans dupliquer."""
        client, _ = agent_client
        enregistrer_proposes(mairie, "PROD", "29027", None, [_propose()])
        site = SiteSensible.objects.get()

        client.patch(reverse("sitesensible-detail", args=[site.id]),
                     {"source": SourceSiteSensible.SAISIE, "source_id": "bidon",
                      "nom": "Collège de l'Aulne (corrigé)"}, format="json")

        site.refresh_from_db()
        assert site.source == SourceSiteSensible.ANNUAIRE_EDUCATION
        assert site.source_id == "0290252S"
        assert site.nom == "Collège de l'Aulne (corrigé)"

    def test_saisie_manuelle_est_retenue_demblee(self, agent_client, mairie):
        client, _ = agent_client
        reponse = client.post(reverse("sitesensible-list"), {
            "nom": "Salle des fêtes", "categorie": CategorieSiteSensible.RASSEMBLEMENT,
            "adresse": "place de la Mairie",
        }, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED
        site = SiteSensible.objects.get()
        assert site.source == SourceSiteSensible.SAISIE
        assert site.statut == StatutSiteSensible.RETENU
        assert site.institution_id == mairie.id

    def test_synthese(self, agent_client, mairie):
        client, _ = agent_client
        enregistrer_proposes(mairie, "PROD", "29027", None, [_propose()])

        reponse = client.get(reverse("sitesensible-synthese"))

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["commune_code"] == "29027"
        assert reponse.data["a_relire"] == 1
        assert SourceSiteSensible.SAISIE not in [s["code"] for s in reponse.data["sources"]]


@pytest.mark.django_db
class TestCreerPoint:
    """Le point du dispositif : un gymnase retenu devient le centre d'accueil qu'on ouvrira le
    jour J, avec son adresse et ses coordonnées. C'est la réponse au défaut constaté en
    production (centres d'accueil sans adresse, donc inutilisables par un habitant)."""

    @pytest.fixture
    def point_type(self, db):
        ptype, _ = PointType.objects.get_or_create(
            code="HEBERGEMENT", defaults={"libelle": "Centre d'hébergement"})
        return ptype

    def _site_gymnase(self, mairie):
        enregistrer_proposes(mairie, "PROD", "29027", "Châteauneuf-du-Faou", [
            _propose(source=SourceSiteSensible.EQUIPEMENTS_SPORTIFS,
                     categorie=CategorieSiteSensible.RASSEMBLEMENT,
                     source_id="I290270001", nom="Complexe sportif Ar Sterenn",
                     adresse="rue du gymnase, 29520 Châteauneuf-du-Faou",
                     latitude=48.192002, longitude=-3.817959)
        ])
        return SiteSensible.objects.get()

    def test_cree_un_point_avec_adresse_et_coordonnees(self, agent_client, mairie, point_type):
        client, _ = agent_client
        site = self._site_gymnase(mairie)

        reponse = client.post(reverse("sitesensible-creer-point", args=[site.id]),
                              {"type": str(point_type.id), "capacite_accueil": 120},
                              format="json")

        assert reponse.status_code == status.HTTP_201_CREATED
        point = PointOperationnel.objects.get()
        assert point.nom == "Complexe sportif Ar Sterenn"
        assert point.adresse.startswith("rue du gymnase")
        assert round(point.location.y, 4) == 48.1920
        assert point.capacite_accueil == 120
        site.refresh_from_db()
        assert site.point_operationnel_id == point.id
        assert site.statut == StatutSiteSensible.RETENU

    def test_refuse_un_second_point(self, agent_client, mairie, point_type):
        client, _ = agent_client
        site = self._site_gymnase(mairie)
        client.post(reverse("sitesensible-creer-point", args=[site.id]),
                    {"type": str(point_type.id)}, format="json")

        reponse = client.post(reverse("sitesensible-creer-point", args=[site.id]),
                              {"type": str(point_type.id)}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert PointOperationnel.objects.count() == 1

    def test_type_obligatoire(self, agent_client, mairie, point_type):
        client, _ = agent_client
        site = self._site_gymnase(mairie)
        reponse = client.post(reverse("sitesensible-creer-point", args=[site.id]), {}, format="json")
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert not PointOperationnel.objects.exists()
