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
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.utils import timezone
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from core.models import (
    AuditLog, CategorieSiteSensible, ContactInstitution, EchelonCompetence,
    ImportOpenData, Institution, SuiviSiteSensible,
    InstitutionType, PointOperationnel, PointType, SiteSensible, SourceSiteSensible,
    StatutImportOpenData, StatutSiteSensible,
)
from core.opendata import ecoles, equipements, finess, icpe, sirene
from core.opendata.base import (
    Perimetre, SitePropose, perimetre_commune, plafond, where_territoire,
)
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


def _decider(site, institution, statut=None, **champs):
    """Pose la décision d'UNE collectivité sur une fiche partagée. L'absence de suivi vaut
    « à vérifier » : c'est pourquoi rien n'est créé à l'import."""
    suivi, _ = SuiviSiteSensible.objects.update_or_create(
        site=site, institution=institution,
        defaults={"environment": site.environment,
                  "statut": statut or StatutSiteSensible.PROPOSE, **champs},
    )
    return suivi


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
        # Aucun suivi : la fiche n'est retenue par personne, c'est l'état « à vérifier ».
        assert site.suivis.count() == 0
        assert site.institution_origine_id == mairie.id
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
        site.effectif_estime = 320
        site.corrige_le = timezone.now()
        site.save()
        _decider(site, mairie, StatutSiteSensible.RETENU, commentaire="Clés chez le gardien")

        enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(nom="COLLEGE DE L'AULNE", adresse="29 rue des Fontaines BP 23")
        ])

        site.refresh_from_db()
        assert site.nom == "Collège de l'Aulne — bâtiment B"
        assert site.adresse == "29 rue des Fontaines (entrée arrière)"
        assert site.effectif_estime == 320
        suivi = site.suivis.get()
        assert suivi.statut == StatutSiteSensible.RETENU
        assert suivi.commentaire == "Clés chez le gardien"

    def test_reimport_reclasse_une_ligne_que_personne_na_relue(self, mairie):
        """Le classement des sources s'améliore : les élevages ont d'abord atterri avec les
        usines. Tant qu'aucun agent n'a corrigé la fiche, un ré-import doit pouvoir les ranger
        correctement — sinon la correction n'atteint jamais les collectivités qui ont importé
        avant."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(source=SourceSiteSensible.ICPE, source_id="0004310066", nom="GAEC BAUT",
                     categorie=CategorieSiteSensible.INDUSTRIE)
        ])
        enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(source=SourceSiteSensible.ICPE, source_id="0004310066", nom="GAEC BAUT",
                     categorie=CategorieSiteSensible.ELEVAGE)
        ])

        site = SiteSensible.objects.get()
        assert site.categorie == CategorieSiteSensible.ELEVAGE

    def test_reimport_ne_reclasse_pas_une_fiche_corrigee(self, mairie, agent_client):
        """L'autre moitié de la règle : une fois qu'un agent a corrigé la fiche, son rangement
        prime. La fiche étant partagée, c'est la correction qui fait foi et non la décision —
        une mairie peut avoir redressé une fiche que le département avait déjà retenue."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(source=SourceSiteSensible.ICPE, source_id="0004310066", nom="GAEC BAUT",
                     categorie=CategorieSiteSensible.INDUSTRIE)
        ])
        site = SiteSensible.objects.get()
        site.corrige_par = agent_client[1]
        site.corrige_le = timezone.now()
        site.save()

        enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(source=SourceSiteSensible.ICPE, source_id="0004310066", nom="GAEC BAUT",
                     categorie=CategorieSiteSensible.ELEVAGE)
        ])

        site.refresh_from_db()
        assert site.categorie == CategorieSiteSensible.INDUSTRIE

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


class TestConnecteurSirene:
    """SIRENE apporte ce qu'aucune autre source ne donne — les moyens d'action — et le fait au
    prix de deux difficultés que ces tests tiennent : elle enregistre des personnes physiques
    chez elles, et elle ne distingue pas une activité réelle d'une simple domiciliation.

    Enregistrements recopiés de l'API « Recherche d'entreprises » (commune 29027)."""

    SOCIETE = {
        "siren": "443061841", "nom_complet": "G.A.E.C. DU SPERNEN",
        "nom_raison_sociale": "G.A.E.C. DU SPERNEN", "nature_juridique": "6533",
        "statut_diffusion": "O", "activite_principale": "01.46Z",
        "matching_etablissements": [{
            "siret": "44306184100018", "activite_principale": "01.46Z",
            "adresse": "1 LD VERU 29520 CHATEAUNEUF-DU-FAOU",
            "latitude": "48.168399", "longitude": "-3.837182",
            "etat_administratif": "A", "date_fermeture": None,
            "statut_diffusion_etablissement": "O", "tranche_effectif_salarie": "02",
            "liste_enseignes": None, "nom_commercial": None,
            "liste_uai": None, "liste_finess": None, "date_mise_a_jour": "2026-01-14",
        }],
    }

    PERSONNE = {
        "siren": "812345678", "nom_complet": "LUDOVIC CARIOU",
        "nom_raison_sociale": "LUDOVIC CARIOU", "nature_juridique": "1000",
        "statut_diffusion": "O", "activite_principale": "01.41Z",
        "matching_etablissements": [{
            "siret": "81234567800011", "activite_principale": "01.41Z",
            "adresse": "LD KERGOAT 29520 CHATEAUNEUF-DU-FAOU",
            "latitude": "48.171", "longitude": "-3.844",
            "etat_administratif": "A", "date_fermeture": None,
            "statut_diffusion_etablissement": "O", "tranche_effectif_salarie": "02",
            "liste_enseignes": None, "nom_commercial": None,
            "liste_uai": None, "liste_finess": None, "date_mise_a_jour": "2026-02-03",
        }],
    }

    THEME_ELEVAGE = sirene.THEMES["ELEVAGE"]

    def _site(self, entreprise, theme=None):
        return sirene._vers_site(
            entreprise, entreprise["matching_etablissements"][0], theme or self.THEME_ELEVAGE,
        )

    def test_mapping_dune_societe(self):
        site = self._site(self.SOCIETE)
        assert site.source_id == "44306184100018"
        assert site.categorie == CategorieSiteSensible.ELEVAGE
        assert site.personne_physique is False
        assert site.latitude == 48.168399
        # Le code NAF seul ne dit rien à un agent : le libellé officiel voyage avec.
        assert site.attributs["naf_libelle"] == "Élevage de porcins"
        assert site.attributs["tranche_effectif"] == "02"

    def test_une_ferme_est_a_la_fois_enjeu_et_ressource(self):
        """Le cheptel est à sauver, le tracteur et la cuve sont mobilisables. Les deux, pas
        l'un ou l'autre."""
        site = self._site(self.SOCIETE)
        assert site.est_enjeu is True
        assert site.est_ressource is True

    def test_un_transporteur_est_une_ressource_pas_un_enjeu(self):
        site = self._site(self.SOCIETE, sirene.THEMES["TRANSPORT_VOYAGEURS"])
        assert site.categorie == CategorieSiteSensible.MOYENS
        assert site.est_enjeu is False
        assert site.est_ressource is True

    def test_les_themes_sont_plus_fins_que_les_categories(self):
        """À l'échelle d'un département, « moyens et travaux » en bloc rend 3 270 établissements
        dans le Finistère — inexploitable — alors que « transport de voyageurs » en rend 57, et
        ce sont précisément les 57 autocaristes qui évacuent. Les thèmes se demandent fin, la
        catégorie reste large pour que les filtres restent lisibles."""
        themes_moyens = [code for code, theme in sirene.THEMES.items()
                         if theme.categorie == CategorieSiteSensible.MOYENS]
        assert len(themes_moyens) >= 3
        assert "TRANSPORT_VOYAGEURS" in themes_moyens

    def test_personne_physique_marquee(self):
        """Nature juridique 1000 = entrepreneur individuel : l'adresse est un domicile. Le
        marquage est ce qui déclenche tout le reste (masquage, dévoilement tracé, refus de
        créer un point public)."""
        site = self._site(self.PERSONNE)
        assert site.personne_physique is True

    def test_opposition_a_diffusion_respectee(self):
        """Droit d'opposition INSEE : une unité non diffusible n'entre pas, même si l'API la
        renvoie."""
        assert self._site({**self.SOCIETE, "statut_diffusion": "N"}) is None
        etablissement = {**self.SOCIETE["matching_etablissements"][0],
                         "statut_diffusion_etablissement": "N"}
        assert sirene._vers_site(self.SOCIETE, etablissement, self.THEME_ELEVAGE) is None

    def test_etablissement_ferme_ignore(self):
        etablissement = {**self.SOCIETE["matching_etablissements"][0],
                         "date_fermeture": "2024-03-01"}
        assert sirene._vers_site(self.SOCIETE, etablissement, self.THEME_ELEVAGE) is None

    def test_accueil_du_jeune_enfant_hors_themes_par_defaut(self):
        """En commune rurale, ce thème ramène surtout des assistantes maternelles, donc des noms
        de personnes à leur domicile. Il s'active en connaissance de cause."""
        assert "PETITE_ENFANCE" not in sirene.THEMES_PAR_DEFAUT
        assert "PETITE_ENFANCE" in sirene.THEMES

    def test_collecte_limitee_aux_themes_demandes(self):
        appels = []

        def faux_fetch(url, params=None):
            appels.append(params["activite_principale"])
            return {"results": [], "total_pages": 1}

        with patch.object(sirene, "fetch_json", side_effect=faux_fetch):
            sirene.collecter(perimetre_commune("29027"), ["VETERINAIRE"])
        assert appels == ["75.00Z"]


class TestPersonnePhysiqueEnBase:
    """Ce que « on ne stocke rien en clair » veut dire concrètement, vérifié en SQL brut."""

    def _propose_personne(self, **kwargs):
        defauts = dict(
            source=SourceSiteSensible.SIRENE, source_id="81234567800011",
            categorie=CategorieSiteSensible.ELEVAGE, nom="LUDOVIC CARIOU",
            adresse="LD KERGOAT 29520 CHATEAUNEUF-DU-FAOU",
            latitude=48.171, longitude=-3.844, personne_physique=True,
            est_enjeu=True, est_ressource=True,
            attributs={"naf": "01.41Z", "date_maj_source": "2026-02-03"},
        )
        defauts.update(kwargs)
        return SitePropose(**defauts)

    def test_adresse_illisible_en_base(self, mairie):
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._propose_personne()])
        site = SiteSensible.objects.get()
        with connection.cursor() as curseur:
            curseur.execute("SELECT adresse FROM core_sitesensible WHERE id = %s", [str(site.id)])
            brut = curseur.fetchone()[0]
        assert "KERGOAT" not in brut
        # Et pourtant relue en clair par le modèle : c'est tout l'intérêt.
        assert site.adresse == "LD KERGOAT 29520 CHATEAUNEUF-DU-FAOU"

    def test_pas_de_coordonnees_en_clair_pour_un_domicile(self, mairie):
        """Un point GPS désigne un domicile aussi sûrement que l'adresse : la colonne
        géographique, elle, n'est pas chiffrable (elle sert aux requêtes spatiales). On n'y met
        donc rien, et les coordonnées vont dans le champ chiffré."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._propose_personne()])
        site = SiteSensible.objects.get()
        assert site.location is None
        assert site.donnees_personnelles == {"latitude": 48.171, "longitude": -3.844}

    def test_une_adresse_en_clair_se_rechiffre_a_la_relecture(self, mairie):
        """Le mécanisme sur lequel repose la migration 0220 : les lignes antérieures au
        chiffrement contiennent du texte en clair, le champ les relit telles quelles, et une
        simple réécriture les chiffre. Sans ça, la bascule des sites déjà importés serait
        impossible sans perdre leurs adresses."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._propose_personne()])
        site = SiteSensible.objects.get()
        with connection.cursor() as curseur:
            # On remet du clair en base, comme avant la migration.
            curseur.execute("UPDATE core_sitesensible SET adresse = %s WHERE id = %s",
                            ["LD KERGOAT 29520 CHATEAUNEUF-DU-FAOU", str(site.id)])

        relu = SiteSensible.objects.get(pk=site.pk)
        assert relu.adresse == "LD KERGOAT 29520 CHATEAUNEUF-DU-FAOU"

        relu.save(update_fields=["adresse"])
        with connection.cursor() as curseur:
            curseur.execute("SELECT adresse FROM core_sitesensible WHERE id = %s", [str(site.id)])
            assert "KERGOAT" not in curseur.fetchone()[0]

    def test_un_etablissement_garde_ses_coordonnees_utilisables(self, mairie):
        """L'inverse, sans quoi la carte et la création de points ne marcheraient plus pour les
        écoles et les ICPE."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [
            self._propose_personne(personne_physique=False, nom="G.A.E.C. DU SPERNEN")
        ])
        site = SiteSensible.objects.get()
        assert site.location is not None
        assert site.donnees_personnelles == {}


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

    def test_adresse_hors_perimetre_non_retenue(self):
        assert finess._adresse_du_perimetre(self.EGE, {"29026"}) is None
        assert finess._adresse_du_perimetre(self.EGE, {"29027"}) is not None
        # Le flux est national : un département passe ses 277 communes d'un coup.
        assert finess._adresse_du_perimetre(self.EGE, {"29026", "29027"}) is not None

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
        _decider(SiteSensible.objects.get(nom="Usine"), mairie, StatutSiteSensible.RETENU)

        synthese = synthese_par_categorie(SiteSensible.objects.all(), mairie, "PROD")

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
        assert SiteSensible.objects.get().suivis.count() == 0

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
        assert site.effectif_estime == 320
        # La décision et son auteur vivent dans le suivi de la collectivité, pas sur la fiche.
        suivi = site.suivis.get()
        assert suivi.statut == StatutSiteSensible.RETENU
        assert suivi.institution_id == mairie.id
        assert suivi.valide_par_id == user.id
        # La correction de l'effectif, elle, est partagée — et datée pour survivre au ré-import.
        assert site.corrige_par_id == user.id and site.corrige_le is not None

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
        assert site.institution_origine_id == mairie.id
        assert site.suivis.get().statut == StatutSiteSensible.RETENU

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
        suivi = site.suivis.get()
        assert suivi.point_operationnel_id == point.id
        assert suivi.statut == StatutSiteSensible.RETENU

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


@pytest.mark.django_db
class TestMasquageEtDevoilement:
    """Le dispositif qui rend SIRENE acceptable : une personne en nom propre est recensée chez
    elle, donc son adresse ne part jamais avec la liste. Elle s'obtient par un appel serveur qui
    laisse une ligne de main courante — « qui a vu cette fiche » reste interrogeable, comme pour
    une personne vulnérable."""

    ADRESSE = "LD KERGOAT 29520 CHATEAUNEUF-DU-FAOU"

    def _personne(self, mairie, **kwargs):
        champs = dict(
            source=SourceSiteSensible.SIRENE, source_id="81234567800011",
            categorie=CategorieSiteSensible.ELEVAGE, nom="LUDOVIC CARIOU",
            adresse=self.ADRESSE, latitude=48.171, longitude=-3.844,
            personne_physique=True, est_enjeu=True, est_ressource=True,
            attributs={"naf": "01.41Z", "date_maj_source": "2026-02-03"},
        )
        champs.update(kwargs)
        enregistrer_proposes(mairie, "PROD", "29027", "Châteauneuf-du-Faou", [_propose(**champs)])
        return SiteSensible.objects.get()

    def test_la_liste_masque_adresse_et_coordonnees(self, agent_client, mairie):
        client, _ = agent_client
        self._personne(mairie)

        ligne = client.get(reverse("sitesensible-list")).data[0]

        assert ligne["adresse"] is None
        assert ligne["latitude"] is None and ligne["longitude"] is None
        # L'agent doit voir qu'il y a quelque chose à dévoiler, sinon il croit la fiche vide.
        assert ligne["adresse_masquee"] is True
        assert ligne["personne_physique"] is True

    def test_le_champ_chiffre_ne_sort_jamais_par_la_liste(self, agent_client, mairie):
        client, _ = agent_client
        self._personne(mairie)
        assert "donnees_personnelles" not in client.get(reverse("sitesensible-list")).data[0]

    def test_devoiler_rend_la_donnee_et_laisse_une_trace(self, agent_client, mairie):
        client, user = agent_client
        site = self._personne(mairie)

        reponse = client.get(reverse("sitesensible-devoiler", args=[site.id]))

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["adresse"] == self.ADRESSE
        assert reponse.data["latitude"] == 48.171
        ligne = AuditLog.objects.filter(objet_type="SiteSensible", utilisateur=user).latest(
            "date_action")
        assert ligne.exposition == AuditLog.Exposition.FICHE
        assert ligne.objet_id == site.id
        assert "nom propre" in ligne.commentaire

    def test_un_etablissement_reste_visible_sans_devoilement(self, agent_client, mairie):
        """Le masquage ne doit pas se répandre : une école garde son adresse dans la liste."""
        client, _ = agent_client
        self._personne(mairie, personne_physique=False)
        ligne = client.get(reverse("sitesensible-list")).data[0]
        assert ligne["adresse"] == self.ADRESSE
        assert ligne["adresse_masquee"] is False

    def test_la_provenance_personne_physique_nest_pas_modifiable(self, agent_client, mairie):
        """Sinon il suffirait d'un PATCH pour faire tomber le masquage."""
        client, _ = agent_client
        site = self._personne(mairie)

        client.patch(reverse("sitesensible-detail", args=[site.id]),
                     {"personne_physique": False}, format="json")

        site.refresh_from_db()
        assert site.personne_physique is True

    def test_creer_point_refuse_une_personne_physique(self, agent_client, mairie):
        """La sortie par laquelle tout le dispositif se viderait : un PointOperationnel est
        public, il est montré aux habitants sur la carte."""
        client, _ = agent_client
        site = self._personne(mairie)
        ptype, _ = PointType.objects.get_or_create(
            code="HEBERGEMENT", defaults={"libelle": "Centre d'hébergement"})
        _decider(site, mairie, StatutSiteSensible.RETENU)

        reponse = client.post(reverse("sitesensible-creer-point", args=[site.id]),
                              {"type": str(ptype.id)}, format="json")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert "domicile" in reponse.data["error"]
        assert not PointOperationnel.objects.exists()

    def test_lagent_peut_corriger_le_role(self, agent_client, mairie):
        """Le rôle vient de la source mais appartient à l'agent dès qu'il le touche."""
        client, _ = agent_client
        site = self._personne(mairie)

        client.patch(reverse("sitesensible-detail", args=[site.id]),
                     {"est_ressource": False}, format="json")

        site.refresh_from_db()
        assert site.est_ressource is False


@pytest.mark.django_db
class TestImportSirene:
    def test_sirene_part_en_tache_de_fond(self, agent_client, mairie):
        """Jusqu'à sept thèmes paginés 25 par 25 : une cinquantaine d'appels sur une grande
        ville, impossible pendant que le navigateur attend."""
        client, _ = agent_client
        with patch("core.tasks.importer_sites_sensibles_task.delay") as delay:
            reponse = client.post(reverse("sitesensible-importer"),
                                  {"sources": [SourceSiteSensible.SIRENE]}, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        assert reponse.data["resultats"][SourceSiteSensible.SIRENE]["asynchrone"] is True
        assert delay.called

    def test_les_themes_demandes_sont_transmis(self, agent_client, mairie):
        client, _ = agent_client
        with patch("core.tasks.importer_sites_sensibles_task.delay") as delay:
            client.post(reverse("sitesensible-importer"),
                        {"sources": [SourceSiteSensible.SIRENE],
                         "themes": ["ELEVAGE"]}, format="json")

        assert delay.call_args[0][-1] == {"themes": ["ELEVAGE"]}

    def test_theme_inconnu_refuse(self, agent_client, mairie):
        client, _ = agent_client
        reponse = client.post(reverse("sitesensible-importer"),
                              {"sources": [SourceSiteSensible.SIRENE],
                               "themes": ["PISCINES"]}, format="json")
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST

    def test_un_theme_ne_sapplique_pas_aux_autres_sources(self, agent_client, mairie):
        """`themes` ne concerne que SIRENE : les quatre autres sources n'ont pas de thème et ne
        doivent pas recevoir une option qu'elles ne savent pas lire."""
        client, _ = agent_client
        with patch.object(ecoles, "collecter", return_value=[]) as collecter:
            client.post(reverse("sitesensible-importer"),
                        {"sources": [SourceSiteSensible.ANNUAIRE_EDUCATION],
                         "themes": ["ELEVAGE"]}, format="json")
        assert collecter.call_args.kwargs == {}
        assert collecter.call_args.args[0] == perimetre_commune("29027")


@pytest.mark.django_db
class TestRapprochementParSiret:
    """Un même établissement ne doit produire qu'une ligne, quel que soit le nombre de sources
    qui le connaissent. Mesuré sur Châteauneuf-du-Faou : 15 des 25 installations classées sont
    aussi des établissements SIRENE. Sans rapprochement, l'agent relit quinze fermes deux fois
    et le plan les compte double."""

    SIRET = "38087767000014"

    def _icpe(self, **kwargs):
        champs = dict(
            source=SourceSiteSensible.ICPE, source_id="0004310066",
            categorie=CategorieSiteSensible.ELEVAGE, nom="GAEC BAUT",
            adresse="KERDUDAL, 29520 Châteauneuf-du-Faou", latitude=48.158, longitude=-3.843,
            est_enjeu=True, est_ressource=False,
            attributs={"siret": self.SIRET, "code_aiot": "0004310066",
                       "cheptel": [{"espece": "porcs", "quantite": 1232.0}],
                       "regime": "Enregistrement", "date_maj_source": "2024-09-04"},
        )
        champs.update(kwargs)
        return _propose(**champs)

    def _sirene(self, **kwargs):
        champs = dict(
            source=SourceSiteSensible.SIRENE, source_id=self.SIRET,
            categorie=CategorieSiteSensible.ELEVAGE, nom="GAEC BAUT (SIRENE)",
            adresse="1 LD VERU 29520 CHATEAUNEUF-DU-FAOU", latitude=48.159, longitude=-3.844,
            est_enjeu=True, est_ressource=True,
            attributs={"siret": self.SIRET, "naf": "01.46Z",
                       "naf_libelle": "Élevage de porcins", "tranche_effectif": "02",
                       "date_maj_source": "2026-01-14"},
        )
        champs.update(kwargs)
        return _propose(**champs)

    def test_deux_sources_un_seul_site(self, mairie):
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._icpe()])
        resultat = enregistrer_proposes(mairie, "PROD", "29027", None, [self._sirene()])

        assert SiteSensible.objects.count() == 1
        assert resultat == {"crees": 0, "mis_a_jour": 1, "inchanges": 0, "total": 1}
        site = SiteSensible.objects.get()
        # La ligne reste celle de la source qui l'a créée : son identifiant ne bouge pas.
        assert site.source == SourceSiteSensible.ICPE
        assert site.attributs["sources_liees"] == ["ICPE", "SIRENE"]

    def test_chaque_source_apporte_ce_quelle_sait(self, mairie):
        """Géorisques a le cheptel, SIRENE a l'activité et l'effectif salarié. La fusion doit
        donner les deux, sinon elle appauvrit au lieu d'enrichir."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._icpe()])
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._sirene()])

        attributs = SiteSensible.objects.get().attributs
        assert attributs["cheptel"][0]["quantite"] == 1232.0
        assert attributs["naf_libelle"] == "Élevage de porcins"
        assert attributs["tranche_effectif"] == "02"
        assert attributs["code_aiot"] == "0004310066"

    def test_le_nom_de_lautre_source_est_propose_pas_impose(self, mairie):
        """SIRENE écrit « SCEA CONAN » là où Géorisques écrit « CONAN (SCEA) ». Souvent mieux,
        mais renommer une ligne n'est pas le travail d'un import."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._icpe()])
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._sirene()])

        site = SiteSensible.objects.get()
        assert site.nom == "GAEC BAUT"
        assert site.attributs["nom_autre_source"] == "GAEC BAUT (SIRENE)"

    def test_une_source_peut_reveler_un_role(self, mairie):
        """La ferme était un enjeu pour Géorisques ; SIRENE y voit aussi un moyen d'action."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._icpe()])
        assert SiteSensible.objects.get().est_ressource is False

        enregistrer_proposes(mairie, "PROD", "29027", None, [self._sirene()])
        site = SiteSensible.objects.get()
        assert (site.est_enjeu, site.est_ressource) == (True, True)

    def test_une_fiche_corrigee_garde_son_role(self, mairie, agent_client):
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._icpe()])
        site = SiteSensible.objects.get()
        site.corrige_par = agent_client[1]
        site.corrige_le = timezone.now()
        site.save()

        enregistrer_proposes(mairie, "PROD", "29027", None, [self._sirene()])

        site.refresh_from_db()
        assert site.est_ressource is False

    def test_personne_physique_decouverte_masque_la_ligne_entiere(self, mairie):
        """Le cas qui rend le masquage crédible : Géorisques publie l'adresse d'un exploitant en
        nom propre (c'est un registre public), SIRENE révèle que c'en est un. La ligne doit
        basculer, sinon le même exploitant est masqué d'un côté et exposé de l'autre."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._icpe()])
        assert SiteSensible.objects.get().location is not None

        enregistrer_proposes(mairie, "PROD", "29027", None,
                             [self._sirene(personne_physique=True)])

        site = SiteSensible.objects.get()
        assert site.personne_physique is True
        assert site.location is None
        # Les coordonnées ne sont pas perdues : elles passent dans le champ chiffré.
        assert site.donnees_personnelles["latitude"] == 48.159

    def test_sans_siret_aucun_rapprochement(self, mairie):
        """Deux sources sans clé commune : on ne devine pas sur le nom, qui ne s'écrit jamais
        pareil (« LE MOAL (GAEC) » contre « EARL LE MOAL »)."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [
            self._icpe(attributs={"code_aiot": "0004310066"})])
        enregistrer_proposes(mairie, "PROD", "29027", None, [
            self._sirene(attributs={"naf": "01.46Z"})])
        assert SiteSensible.objects.count() == 2

    def test_un_reimport_ne_recree_pas_la_ligne_fusionnee(self, mairie):
        """La fusion doit être idempotente : le second passage de SIRENE ne retrouve pas la
        ligne par son propre identifiant, il doit la retrouver par le SIRET."""
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._icpe()])
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._sirene()])
        resultat = enregistrer_proposes(mairie, "PROD", "29027", None, [self._sirene()])

        assert SiteSensible.objects.count() == 1
        assert resultat["inchanges"] == 1

    def test_la_fiche_est_partagee_entre_collectivites(self, mairie, create_user):
        """Le cœur du dispositif, et l'inverse de ce que faisait la version précédente : deux
        collectivités qui recensent le même établissement obtiennent UNE fiche. Qui importe le
        premier en fait profiter l'autre, dans les deux sens."""
        itype = InstitutionType.objects.get(code="MAIRIE")
        voisine = Institution.objects.create(nom="Conseil départemental", type=itype,
                                             commune_code="29019", commune_nom="Brest")
        enregistrer_proposes(mairie, "PROD", "29027", None, [self._icpe()])
        resultat = enregistrer_proposes(voisine, "PROD", "29019", None, [self._sirene()])

        assert SiteSensible.objects.count() == 1
        assert resultat["crees"] == 0
        site = SiteSensible.objects.get()
        # La fiche garde son origine, mais l'apport de la seconde collectivité est bien là.
        assert site.institution_origine_id == mairie.id
        assert site.attributs["sources_liees"] == ["ICPE", "SIRENE"]


@pytest.mark.django_db
class TestConvention:
    """Une ressource recensée n'est pas une ressource acquise : seule une convention engage. Ce
    que ces tests tiennent, c'est que la convention est traçable (qui l'a déclarée, quand) et que
    son document est protégé comme une pièce d'identité."""

    PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"

    def _site(self, mairie):
        enregistrer_proposes(mairie, "PROD", "29027", "Châteauneuf-du-Faou", [
            _propose(source=SourceSiteSensible.SIRENE, source_id="51050510000014",
                     categorie=CategorieSiteSensible.MOYENS, nom="SARL TREHOAT",
                     adresse="29520 Châteauneuf-du-Faou", est_enjeu=False, est_ressource=True,
                     attributs={"siret": "51050510000014", "naf": "49.41B"})
        ])
        return SiteSensible.objects.get()

    def test_declarer_une_convention_laisse_une_trace(self, agent_client, mairie):
        client, user = agent_client
        site = self._site(mairie)

        reponse = client.patch(reverse("sitesensible-detail", args=[site.id]), {
            "convention_existe": True, "convention_numero": "2026-TR-14",
            "convention_date_signature": "2026-03-12", "convention_echeance": "2029-03-11",
        }, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        suivi = site.suivis.get()
        assert suivi.institution_id == mairie.id
        assert suivi.convention_existe is True
        assert suivi.convention_numero == "2026-TR-14"
        assert str(suivi.convention_echeance) == "2029-03-11"
        ligne = AuditLog.objects.filter(objet_type="SiteSensible").latest("date_action")
        assert "Convention" in ligne.commentaire and "2026-TR-14" in ligne.commentaire
        assert ligne.utilisateur == user

    def test_declarer_une_convention_ne_fait_pas_de_lagent_le_decideur(self, agent_client,
                                                                       mairie):
        """`valide_par` veut dire « a statué sur le sort du site », pas « a touché la ligne »."""
        client, _ = agent_client
        site = self._site(mairie)

        client.patch(reverse("sitesensible-detail", args=[site.id]),
                     {"convention_existe": True}, format="json")

        suivi = site.suivis.get()
        assert suivi.valide_par is None
        assert suivi.statut == StatutSiteSensible.PROPOSE

    def test_televerser_puis_telecharger(self, agent_client, mairie):
        client, _ = agent_client
        site = self._site(mairie)
        fichier = SimpleUploadedFile("convention.pdf", self.PDF, content_type="application/pdf")

        envoi = client.patch(reverse("sitesensible-detail", args=[site.id]),
                             {"convention_existe": True, "convention_document": fichier},
                             format="multipart")

        assert envoi.status_code == status.HTTP_200_OK
        # Le fichier ne sort jamais comme URL : seul un booléen dit qu'il existe.
        assert envoi.data["a_convention_document"] is True
        assert "convention_document" not in envoi.data

        telechargement = client.get(
            reverse("sitesensible-telecharger-convention", args=[site.id]))
        assert telechargement.status_code == status.HTTP_200_OK
        assert b"".join(telechargement.streaming_content) == self.PDF

    def test_le_document_est_chiffre_sur_le_disque(self, agent_client, mairie):
        """Comme une pièce d'identité : un accès au volume média ne doit pas donner la
        convention en clair."""
        client, _ = agent_client
        site = self._site(mairie)
        fichier = SimpleUploadedFile("convention.pdf", self.PDF, content_type="application/pdf")
        client.patch(reverse("sitesensible-detail", args=[site.id]),
                     {"convention_document": fichier}, format="multipart")

        with open(site.suivis.get().convention_document.path, "rb") as brut:
            octets = brut.read()
        assert not octets.startswith(b"%PDF-")
        assert b"%%EOF" not in octets

    def test_le_telechargement_est_trace(self, agent_client, mairie):
        client, user = agent_client
        site = self._site(mairie)
        fichier = SimpleUploadedFile("convention.pdf", self.PDF, content_type="application/pdf")
        client.patch(reverse("sitesensible-detail", args=[site.id]),
                     {"convention_document": fichier}, format="multipart")

        client.get(reverse("sitesensible-telecharger-convention", args=[site.id]))

        ligne = AuditLog.objects.filter(objet_type="SiteSensible",
                                        action__code="TELECHARGEMENT").latest("date_action")
        assert ligne.utilisateur == user
        assert "Convention" in ligne.commentaire

    def test_sans_convention_le_telechargement_rend_404(self, agent_client, mairie):
        client, _ = agent_client
        site = self._site(mairie)
        reponse = client.get(reverse("sitesensible-telecharger-convention", args=[site.id]))
        assert reponse.status_code == status.HTTP_404_NOT_FOUND

    def test_un_fichier_non_pdf_est_refuse(self, agent_client, mairie):
        client, _ = agent_client
        site = self._site(mairie)
        fichier = SimpleUploadedFile("convention.exe", b"MZ\x90\x00 pas un document",
                                     content_type="application/octet-stream")

        reponse = client.patch(reverse("sitesensible-detail", args=[site.id]),
                               {"convention_document": fichier}, format="multipart")

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST


class TestEchelonScolaire:
    """La hiérarchie des compétences scolaires, que l'annuaire de l'éducation porte en clair.

    C'est elle qui rend la page utilisable par autre chose qu'une mairie : sur les 852
    établissements du Finistère, 75 collèges publics relèvent du département. Sans cette
    distinction, un conseil départemental reçoit 852 lignes à relire au lieu de 75."""

    def _echelon(self, type_etablissement, statut="Public"):
        return ecoles._echelon({"type_etablissement": type_etablissement,
                                "statut_public_prive": statut})

    def test_la_hierarchie(self):
        assert self._echelon("Ecole") == EchelonCompetence.COMMUNE
        assert self._echelon("Collège") == EchelonCompetence.DEPARTEMENT
        assert self._echelon("Lycée") == EchelonCompetence.REGION

    def test_laccent_ne_change_rien(self):
        """« Collège » et « Lycée » arrivent accentués dans le jeu de données."""
        assert self._echelon("College") == EchelonCompetence.DEPARTEMENT
        assert self._echelon("LYCEE") == EchelonCompetence.REGION

    def test_le_prive_nest_la_charge_daucune_collectivite(self):
        """302 des 852 établissements du Finistère. Un collège privé sous contrat reste un enjeu
        en crise, mais son bâtiment n'appartient pas au département."""
        assert self._echelon("Collège", "Privé") == EchelonCompetence.PRIVE
        assert self._echelon("Ecole", "Privé") == EchelonCompetence.PRIVE

    def test_un_service_administratif_releve_de_letat(self):
        assert self._echelon("Service Administratif", None) == EchelonCompetence.ETAT

    def test_ce_quon_ne_sait_pas_reste_a_determiner(self):
        """Médico-social public, « Information et orientation », types à venir : on ne devine
        pas, l'agent tranche."""
        assert self._echelon("Médico-social") == EchelonCompetence.INDETERMINE
        assert self._echelon("Information et orientation") == EchelonCompetence.INDETERMINE

    def test_lechelon_voyage_jusquau_site(self):
        site = ecoles._vers_site({
            "identifiant_de_l_etablissement": "0290123X", "etat": "OUVERT",
            "nom_etablissement": "Collège de l'Aulne", "type_etablissement": "Collège",
            "statut_public_prive": "Public", "code_commune": "29027",
            "nom_commune": "Châteauneuf-du-Faou", "code_postal": "29520",
        })
        assert site.echelon_competence == EchelonCompetence.DEPARTEMENT
        # La commune du SITE, pas celle de l'institution qui importe.
        assert site.commune_code == "29027"
        assert site.commune_nom == "Châteauneuf-du-Faou"


class TestPerimetreDesSources:
    """Chaque source sait-elle répondre à l'échelle d'un département sans 277 appels ?"""

    def test_un_jeu_opendatasoft_utilise_son_champ_departemental(self):
        perimetre = Perimetre("departement", "29", ["29027", "29019"])
        where = where_territoire("code_commune", perimetre,
                                 champs_secteur={"departement": "code_departement"},
                                 codes_secteur={"departement": "029"})
        # L'annuaire de l'éducation zéro-complète le code sur trois caractères.
        assert where == 'code_departement="029"'

    def test_sans_champ_pour_ce_niveau_repli_sur_les_communes(self):
        """Aucun des jeux branchés ne porte l'EPCI : on liste ses communes."""
        perimetre = Perimetre("epci", "242900561", ["29027", "29019"])
        where = where_territoire("code_commune", perimetre,
                                 champs_secteur={"departement": "code_departement"})
        assert where == 'code_commune IN ("29027", "29019")'

    def test_georisques_a_un_filtre_departemental_natif(self):
        assert icpe._filtre_territoire(Perimetre("departement", "29", [])) == {"departement": "29"}
        assert icpe._filtre_territoire(Perimetre("region", "53", [])) == {"region": "53"}
        assert icpe._filtre_territoire(perimetre_commune("29027")) is None

    def test_sirene_interroge_le_departement_en_une_fois(self):
        assert sirene._filtres_territoire(Perimetre("departement", "29", ["a"] * 277)) == [
            {"departement": "29"}]
        # Sans filtre de secteur, une requête par commune — et c'est le coût à éviter.
        assert sirene._filtres_territoire(Perimetre("epci", "x", ["29027", "29019"])) == [
            {"code_commune": "29027"}, {"code_commune": "29019"}]

    def test_le_plafond_suit_le_perimetre(self):
        """852 établissements scolaires dans le Finistère : un plafond communal de 500 les
        tronquerait."""
        assert plafond(perimetre_commune("29027")) == 500
        assert plafond(Perimetre("departement", "29", [])) > 852


@pytest.mark.django_db
class TestCollectiviteSupraCommunale:
    """Ce qui change pour un conseil départemental : le périmètre d'import, le compteur borné à
    sa compétence, et la lecture du territoire plutôt qu'une copie de 5 000 lignes."""

    @pytest.fixture
    def communes_29(self, db):
        from core.models import Commune

        for code, nom in (("29027", "Châteauneuf-du-Faou"), ("29019", "Brest")):
            Commune.objects.update_or_create(
                code=code, defaults={"nom": nom, "departement_code": "29", "region_code": "53",
                                     "epci_code": "242900561"})
        Commune.objects.update_or_create(
            code="22168", defaults={"nom": "Pleudihen-sur-Rance", "departement_code": "22",
                                    "region_code": "53"})

    @pytest.fixture
    def conseil_departemental(self, communes_29):
        itype, _ = InstitutionType.objects.get_or_create(
            code="CG", defaults={"libelle": "Conseil départemental"})
        return Institution.objects.create(
            nom="Conseil départemental du Finistère", type=itype,
            commune_code="29019", commune_nom="Brest",
        )

    @pytest.fixture
    def client_cd(self, conseil_departemental, create_user):
        user = create_user(username="agent-cd@test.fr", email="agent-cd@test.fr",
                           type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=conseil_departemental, utilisateur=user,
                                          actif=True)
        client = APIClient()
        client.force_authenticate(user=user)
        return client, user

    def test_le_niveau_du_conseil_departemental_est_deduit_de_son_type(self,
                                                                      conseil_departemental):
        assert conseil_departemental.secteur_niveau_effectif == "departement"
        assert conseil_departemental.departement_code == "29"

    def test_un_departement_peut_importer_son_departement(self, client_cd):
        client, _ = client_cd
        with patch("core.tasks.importer_sites_sensibles_task.delay") as delay:
            reponse = client.post(reverse("sitesensible-importer"), {
                "sources": [SourceSiteSensible.SIRENE], "themes": ["TRANSPORT_VOYAGEURS"],
                "perimetre": "departement",
            }, format="json")

        assert reponse.status_code == status.HTTP_200_OK
        # Seuls le niveau et le code voyagent dans Celery : pas les 277 codes commune.
        assert delay.call_args[0][2] == {"niveau": "departement", "code": "29"}

    def test_une_mairie_ne_peut_pas_importer_le_departement(self, agent_client, mairie):
        """Même règle que partout : on restreint, on n'élargit jamais."""
        client, _ = agent_client
        reponse = client.post(reverse("sitesensible-importer"), {
            "sources": [SourceSiteSensible.ANNUAIRE_EDUCATION], "perimetre": "departement",
        }, format="json")
        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert reponse.data["perimetres"] == ["commune"]

    def test_la_synthese_annonce_le_secteur_et_les_perimetres(self, client_cd):
        client, _ = client_cd
        donnees = client.get(reverse("sitesensible-synthese")).data
        assert donnees["niveau"] == "departement"
        assert donnees["echelon_propre"] == EchelonCompetence.DEPARTEMENT
        assert donnees["perimetres_possibles"] == ["commune", "epci", "departement"]
        assert "TRANSPORT_VOYAGEURS" in [t["code"] for t in donnees["themes"]]

    def test_a_relire_est_borne_a_la_competence_du_departement(self, client_cd,
                                                               conseil_departemental):
        """Le compteur doit annoncer le travail réel : les collèges, pas les 374 écoles."""
        enregistrer_proposes(conseil_departemental, "PROD", "29", None, [
            _propose(source_id="college-1", nom="Collège A",
                     echelon_competence=EchelonCompetence.DEPARTEMENT, commune_code="29027"),
            _propose(source_id="ecole-1", nom="École B",
                     echelon_competence=EchelonCompetence.COMMUNE, commune_code="29027"),
            _propose(source_id="lycee-1", nom="Lycée C",
                     echelon_competence=EchelonCompetence.REGION, commune_code="29019"),
        ])
        donnees = client.get if False else client_cd[0].get(reverse("sitesensible-synthese"))
        assert donnees.data["a_relire"] == 1
        # Le total reste disponible : rien n'est caché, c'est le compteur qui est cadré.
        assert donnees.data["a_relire_tous_echelons"] == 3

    def test_une_mairie_voit_tout_ce_qui_est_sur_sa_commune(self, agent_client, mairie):
        """L'inverse du cas départemental : une installation classée ou un commerce n'est la
        charge d'aucune collectivité, mais une mairie doit le compter — c'est son plan."""
        client, _ = agent_client
        enregistrer_proposes(mairie, "PROD", "29027", None, [
            _propose(source=SourceSiteSensible.ICPE, source_id="aiot-1", nom="Usine",
                     categorie=CategorieSiteSensible.INDUSTRIE,
                     echelon_competence=EchelonCompetence.INDETERMINE),
        ])
        assert client.get(reverse("sitesensible-synthese")).data["a_relire"] == 1

    def test_la_commune_de_chaque_site_est_la_sienne(self, conseil_departemental):
        """Un import départemental ne doit pas estampiller 277 communes avec celle du chef-lieu."""
        enregistrer_proposes(conseil_departemental, "PROD", "29", "Finistère", [
            _propose(source_id="a", nom="Collège de Châteauneuf", commune_code="29027",
                     commune_nom="Châteauneuf-du-Faou"),
            _propose(source_id="b", nom="Collège de Brest", commune_code="29019",
                     commune_nom="Brest"),
        ])
        communes = set(SiteSensible.objects.values_list("commune_code", flat=True))
        assert communes == {"29027", "29019"}


@pytest.mark.django_db
class TestPartageEntreCollectivites:
    """Le cœur du dispositif : UNE fiche par établissement, chacun prend ce dont il a besoin.

    Qui importe le premier en fait profiter les autres, dans les deux sens — c'est ce que ces
    tests tiennent, parce que c'est l'inverse qui se produisait avant : chaque collectivité avait
    sa copie, et deux inventaires du même territoire divergeaient tranquillement."""

    @pytest.fixture
    def decor(self, db, create_user):
        from core.models import Commune

        for code, nom in (("29027", "Châteauneuf-du-Faou"), ("29019", "Brest")):
            Commune.objects.update_or_create(
                code=code, defaults={"nom": nom, "departement_code": "29", "region_code": "53"})
        Commune.objects.update_or_create(
            code="22168", defaults={"nom": "Pleudihen-sur-Rance", "departement_code": "22",
                                    "region_code": "53"})

        type_cg, _ = InstitutionType.objects.get_or_create(
            code="CG", defaults={"libelle": "Conseil départemental"})
        type_mairie, _ = InstitutionType.objects.get_or_create(
            code="MAIRIE", defaults={"libelle": "Mairie"})
        cd = Institution.objects.create(nom="CD 29", type=type_cg, commune_code="29019",
                                        commune_nom="Brest")
        commune = Institution.objects.create(nom="Mairie de Châteauneuf", type=type_mairie,
                                             commune_code="29027",
                                             commune_nom="Châteauneuf-du-Faou")
        hors = Institution.objects.create(nom="Mairie de Pleudihen", type=type_mairie,
                                          commune_code="22168",
                                          commune_nom="Pleudihen-sur-Rance")
        return {"cd": cd, "commune": commune, "hors": hors,
                "client_cd": self._client(create_user, cd, "cd@test.fr"),
                "client_commune": self._client(create_user, commune, "mairie@test.fr"),
                "client_hors": self._client(create_user, hors, "hors@test.fr")}

    @staticmethod
    def _client(create_user, institution, email):
        user = create_user(username=email, email=email, type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=institution, utilisateur=user, actif=True)
        client = APIClient()
        client.force_authenticate(user=user)
        return client, user

    @staticmethod
    def _college(institution, nom="Collège de l'Aulne"):
        enregistrer_proposes(institution, "PROD", "29027", "Châteauneuf-du-Faou", [
            _propose(source_id="0290252S", nom=nom, commune_code="29027",
                     commune_nom="Châteauneuf-du-Faou",
                     echelon_competence=EchelonCompetence.DEPARTEMENT)])
        return SiteSensible.objects.get(source_id="0290252S")

    def test_la_mairie_profite_de_limport_du_departement(self, decor):
        """Le département importe ses collèges : la mairie les voit sans rien faire."""
        self._college(decor["cd"])
        client, _ = decor["client_commune"]

        lignes = client.get(reverse("sitesensible-list")).data

        assert [l["nom"] for l in lignes] == ["Collège de l'Aulne"]
        # Pour elle, personne n'a encore statué : c'est SA décision qui manque, pas la fiche.
        assert lignes[0]["statut"] == StatutSiteSensible.PROPOSE

    def test_le_departement_profite_de_limport_de_la_mairie(self, decor):
        """Et dans l'autre sens, ce qui est tout l'objet de la bascule."""
        self._college(decor["commune"])
        client, _ = decor["client_cd"]

        lignes = client.get(reverse("sitesensible-list")).data

        assert [l["nom"] for l in lignes] == ["Collège de l'Aulne"]

    def test_une_seule_fiche_meme_si_les_deux_importent(self, decor):
        self._college(decor["commune"])
        self._college(decor["cd"])
        assert SiteSensible.objects.count() == 1

    def test_chacun_sa_decision_sur_la_meme_fiche(self, decor):
        """Un collège est retenu au plan du département et peut être écarté de celui de la
        commune, qui n'en a pas la charge. Une fiche, deux décisions."""
        site = self._college(decor["cd"])
        client_cd, _ = decor["client_cd"]
        client_commune, _ = decor["client_commune"]

        client_cd.patch(reverse("sitesensible-detail", args=[site.id]),
                        {"statut": StatutSiteSensible.RETENU}, format="json")
        client_commune.patch(reverse("sitesensible-detail", args=[site.id]),
                             {"statut": StatutSiteSensible.ECARTE}, format="json")

        assert SuiviSiteSensible.objects.count() == 2
        vue_cd = client_cd.get(reverse("sitesensible-detail", args=[site.id])).data
        vue_commune = client_commune.get(reverse("sitesensible-detail", args=[site.id])).data
        assert vue_cd["statut"] == StatutSiteSensible.RETENU
        assert vue_commune["statut"] == StatutSiteSensible.ECARTE

    def test_la_correction_de_lun_profite_a_lautre(self, decor):
        """La raison d'être du partage : la mairie connaît le terrain, le département en
        bénéficie sans avoir à ressaisir."""
        site = self._college(decor["cd"], nom="COLLEGE DE L AULNE")
        client_commune, _ = decor["client_commune"]
        client_cd, _ = decor["client_cd"]

        client_commune.patch(reverse("sitesensible-detail", args=[site.id]),
                             {"nom": "Collège de l'Aulne — entrée rue des Fontaines"},
                             format="json")

        vue_cd = client_cd.get(reverse("sitesensible-detail", args=[site.id])).data
        assert vue_cd["nom"] == "Collège de l'Aulne — entrée rue des Fontaines"

    def test_on_voit_ce_que_les_autres_ont_decide(self, decor):
        """Rendre le partage visible : la mairie voit que le département a retenu son collège."""
        site = self._college(decor["cd"])
        client_cd, _ = decor["client_cd"]
        client_commune, _ = decor["client_commune"]
        client_cd.patch(reverse("sitesensible-detail", args=[site.id]),
                        {"statut": StatutSiteSensible.RETENU}, format="json")

        vue = client_commune.get(reverse("sitesensible-detail", args=[site.id])).data

        assert vue["decisions_autres"] == [
            {"institution_nom": "CD 29", "statut": StatutSiteSensible.RETENU,
             "statut_libelle": "Retenu au plan de sauvegarde", "convention": False}]

    def test_la_convention_de_lun_nest_pas_celle_de_lautre(self, decor):
        """Une convention lie une collectivité précise à une entreprise précise : elle n'est pas
        transposable à la voisine."""
        site = self._college(decor["cd"])
        client_cd, _ = decor["client_cd"]
        client_commune, _ = decor["client_commune"]

        client_cd.patch(reverse("sitesensible-detail", args=[site.id]),
                        {"convention_existe": True, "convention_numero": "CD-2026-01"},
                        format="json")

        assert client_commune.get(
            reverse("sitesensible-detail", args=[site.id])).data["convention_existe"] is False

    def test_chacun_son_point_operationnel(self, decor):
        """Commune et département peuvent chacun ouvrir leur centre sur le même bâtiment."""
        site = self._college(decor["cd"])
        ptype, _ = PointType.objects.get_or_create(
            code="HEBERGEMENT", defaults={"libelle": "Centre d'hébergement"})
        client_cd, _ = decor["client_cd"]
        client_commune, _ = decor["client_commune"]

        premier = client_cd.post(reverse("sitesensible-creer-point", args=[site.id]),
                                 {"type": str(ptype.id)}, format="json")
        second = client_commune.post(reverse("sitesensible-creer-point", args=[site.id]),
                                     {"type": str(ptype.id)}, format="json")

        assert premier.status_code == status.HTTP_201_CREATED
        assert second.status_code == status.HTTP_201_CREATED
        assert PointOperationnel.objects.count() == 2

    def test_le_second_point_de_la_meme_collectivite_est_refuse(self, decor):
        site = self._college(decor["cd"])
        ptype, _ = PointType.objects.get_or_create(
            code="HEBERGEMENT", defaults={"libelle": "Centre d'hébergement"})
        client_cd, _ = decor["client_cd"]

        client_cd.post(reverse("sitesensible-creer-point", args=[site.id]),
                       {"type": str(ptype.id)}, format="json")
        second = client_cd.post(reverse("sitesensible-creer-point", args=[site.id]),
                                {"type": str(ptype.id)}, format="json")

        assert second.status_code == status.HTTP_400_BAD_REQUEST
        assert PointOperationnel.objects.count() == 1

    def test_supprimer_retire_de_son_plan_sans_effacer_celui_des_autres(self, decor):
        """Depuis que la fiche est partagée, une suppression qui l'effacerait vraiment ferait
        disparaître le travail d'une autre collectivité."""
        site = self._college(decor["cd"])
        client_cd, _ = decor["client_cd"]
        client_commune, _ = decor["client_commune"]
        client_cd.patch(reverse("sitesensible-detail", args=[site.id]),
                        {"statut": StatutSiteSensible.RETENU}, format="json")
        client_commune.patch(reverse("sitesensible-detail", args=[site.id]),
                             {"statut": StatutSiteSensible.ECARTE}, format="json")

        client_commune.delete(reverse("sitesensible-detail", args=[site.id]))

        assert SiteSensible.objects.filter(pk=site.pk).exists()
        assert SuiviSiteSensible.objects.filter(site=site).count() == 1
        assert SuiviSiteSensible.objects.get(site=site).institution == decor["cd"]

    def test_une_commune_dun_autre_departement_ne_voit_rien(self, decor):
        """Le partage est territorial, pas universel."""
        self._college(decor["cd"])
        client_hors, _ = decor["client_hors"]
        assert client_hors.get(reverse("sitesensible-list")).data == []

    def test_le_filtre_a_verifier_porte_sur_ma_propre_decision(self, decor):
        """« À vérifier » veut dire « je n'ai pas encore statué », pas « personne n'a statué »."""
        site = self._college(decor["cd"])
        client_cd, _ = decor["client_cd"]
        client_commune, _ = decor["client_commune"]
        client_cd.patch(reverse("sitesensible-detail", args=[site.id]),
                        {"statut": StatutSiteSensible.RETENU}, format="json")

        assert client_cd.get(reverse("sitesensible-list"),
                             {"statut": StatutSiteSensible.PROPOSE}).data == []
        restent = client_commune.get(reverse("sitesensible-list"),
                                     {"statut": StatutSiteSensible.PROPOSE}).data
        assert [l["nom"] for l in restent] == ["Collège de l'Aulne"]
