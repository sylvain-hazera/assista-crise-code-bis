"""Veille du territoire : vigilance Météo-France, événements routiers, stations de carburant,
défibrillateurs, et relais de la recherche d'adresse (15/11/2026).

Aucun test n'appelle l'extérieur : les réponses des sources sont des extraits réels réduits,
rejoués ici. Ce qui est vérifié, c'est ce que NOUS en faisons -- et, pour le relais d'adresse,
ce que nous laissons sortir."""
import base64
import datetime
import io
import json
from unittest import mock

import pytest
import requests
from django.contrib.gis.geos import Point
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from core import (
    carburants, meteo_france, observations_meteo, pluie, sources_ouvertes, trafic_routier,
)
from core.models import (
    CanalMeshCore, Commune, ConfigurationAlerteVigilance, ContactInstitution, EvenementRoutier,
    ImagePluie,
    Institution, InstitutionType, MessageCanalMeshCore, ObservationMeteo, ReleveSourceOuverte,
    StationCarburant,
    VigilanceDiffusee, VigilanceMeteo, VignetteVigilanceMeteo,
)
from core.opendata import CONNECTEURS, SOURCES_ASYNCHRONES, SOURCES_SANS_DECOUPAGE, dae

UTC = datetime.timezone.utc
# Un dimanche à 10 h 30, heure de Paris.
MAINTENANT = datetime.datetime(2026, 11, 15, 9, 30, tzinfo=UTC)


# ── Extraits de réponses ────────────────────────────────────────────────────────────────────

def _domaine(code, couleur, phenomenes):
    return {
        "domain_id": code, "max_color_id": couleur,
        "phenomenon_items": [
            {"phenomenon_id": str(identifiant), "phenomenon_max_color_id": niveau,
             "timelaps_items": [{"begin_time": debut, "end_time": fin, "color_id": niveau}] if debut else []}
            for identifiant, niveau, debut, fin in phenomenes
        ],
    }


def _carte(domaines_j, domaines_j1=()):
    return {"product": {
        "update_time": "2026-11-15T09:00:19Z",
        "periods": [
            {"echeance": "J", "begin_validity_time": "2026-11-15T09:00:00Z",
             "end_validity_time": "2026-11-15T23:00:00Z",
             "timelaps": {"domain_ids": list(domaines_j)}},
            {"echeance": "J1", "begin_validity_time": "2026-11-15T23:00:00Z",
             "end_validity_time": "2026-11-16T23:00:00Z",
             "timelaps": {"domain_ids": list(domaines_j1)}},
        ],
    }}


ORANGE_VENT_42 = _domaine("42", 3, [(1, 3, "2026-11-15T14:00:00Z", "2026-11-15T22:00:00Z"),
                                    (2, 1, "2026-11-15T09:00:00Z", "2026-11-15T23:00:00Z")])


def _enregistrer(*domaines_j, domaines_j1=(), maintenant=MAINTENANT):
    publie_le, departements = meteo_france.analyser_carte(_carte(domaines_j, domaines_j1))
    meteo_france.enregistrer(publie_le, departements, {}, maintenant=maintenant)


@pytest.fixture
def mairie(db):
    # Commune complète (nom, centre, département, région) : Institution.save() n'a alors rien
    # à demander au service géographique, et le test ne dépend pas du réseau.
    Commune.objects.create(code="42218", nom="Saint-Étienne", departement_code="42",
                           region_code="84", epci_code="244200770",
                           centre_latitude=45.44, centre_longitude=4.39)
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(
        nom="Mairie de Saint-Étienne (veille)", type=itype, commune_code="42218",
        commune_nom="Saint-Étienne", departement_code="42",
    )


@pytest.fixture
def abonnement(mairie):
    return ConfigurationAlerteVigilance.objects.create(institution=mairie, actif=True, couleur_min=3)


@pytest.fixture
def sans_messagerie():
    """Le message privé passe par Matrix, absent des tests : on vérifie qu'il est demandé."""
    with mock.patch("core.matrix.envoyer_dm") as envoi:
        yield envoi


# ── Vigilance : lecture de la carte ─────────────────────────────────────────────────────────

class TestLectureDeLaCarte:

    def test_seul_le_jaune_et_au_dela_est_retenu(self):
        _publie, departements = meteo_france.analyser_carte(_carte([ORANGE_VENT_42]))

        fiche = departements["42"]["J"]
        assert fiche["couleur"] == 3
        assert [p["id"] for p in fiche["phenomenes"]] == [1]

    def test_la_bande_littorale_est_rattachee_a_son_departement(self):
        """« 3010 » est le littoral du Gard : son phénomène vagues-submersion doit se lire sur
        le Gard, et sa couleur compter dans celle du département."""
        gard = _domaine("30", 1, [(1, 1, None, None)])
        littoral = _domaine("3010", 3, [(9, 3, "2026-11-15T12:00:00Z", "2026-11-15T20:00:00Z")])

        _publie, departements = meteo_france.analyser_carte(_carte([gard, littoral]))

        assert "3010" not in departements
        assert departements["30"]["J"]["couleur"] == 3
        assert departements["30"]["J"]["phenomenes"][0]["id"] == 9

    def test_un_domaine_illisible_ne_fait_pas_perdre_les_autres(self):
        casse = {"domain_id": "43", "max_color_id": 2,
                 "phenomenon_items": [{"phenomenon_id": "vent", "phenomenon_max_color_id": 2}]}

        _publie, departements = meteo_france.analyser_carte(_carte([casse, ORANGE_VENT_42]))

        assert departements["42"]["J"]["couleur"] == 3

    def test_les_phenomenes_sont_ranges_du_plus_grave_au_moins_grave(self):
        domaine = _domaine("42", 4, [(3, 2, None, None), (2, 4, None, None), (1, 3, None, None)])

        _publie, departements = meteo_france.analyser_carte(_carte([domaine]))

        assert [p["id"] for p in departements["42"]["J"]["phenomenes"]] == [2, 1, 3]

    def test_les_bulletins_gardent_le_national_et_les_departements(self):
        partie = {"bold_text": "Faits nouveaux :", "underline_text": "", "text": ["Vent fort.", ""]}
        bloc = lambda code: {"domain_id": code, "bloc_items": [{"type_name": "Situation", "text_items": [
            {"hazard_code": None, "hazard_name": "tous aléas", "term_items": [{"subdivision_text": [partie]}]}]}]}

        bulletins = meteo_france.analyser_textes(
            {"product": {"text_bloc_items": [bloc("FRA"), bloc("42"), bloc("ZDF_SUD")]}})

        assert set(bulletins) == {"FRA", "42"}
        assert bulletins["42"] == [{"rubrique": "Situation", "alea": "", "titre": "Faits nouveaux",
                                    "lignes": ["Vent fort."]}]

    @pytest.mark.django_db
    def test_des_bulletins_non_releves_ne_sont_pas_effaces(self):
        publie_le, departements = meteo_france.analyser_carte(_carte([ORANGE_VENT_42]))
        meteo_france.enregistrer(publie_le, departements, {"42": [{"titre": "A", "lignes": ["x"]}]})

        meteo_france.enregistrer(publie_le, departements, None)

        assert VigilanceMeteo.objects.get(pk="42").bulletin == [{"titre": "A", "lignes": ["x"]}]


# ── Vigilance : la clé ──────────────────────────────────────────────────────────────────────

class TestRepriseSurRefusDeConnexion:
    """La passerelle de Météo-France refuse par moments la connexion, une requête sur deux ou
    trois (constaté le 15/11/2026). Un refus de connexion se réessaie ; le reste, non."""

    @pytest.fixture(autouse=True)
    def sans_attente(self, monkeypatch):
        monkeypatch.setattr(meteo_france, "ATTENTE_ENTRE_TENTATIVES_S", 0)

    def test_un_refus_passager_est_reessaye(self):
        appel = mock.Mock(side_effect=[requests.ConnectionError("refusée"), requests.ConnectionError("refusée"), "réponse"])

        assert meteo_france.avec_reprise(appel) == "réponse"
        assert appel.call_count == 3

    def test_un_refus_persistant_finit_par_remonter(self):
        appel = mock.Mock(side_effect=requests.ConnectionError("refusée"))

        with pytest.raises(requests.ConnectionError):
            meteo_france.avec_reprise(appel)
        assert appel.call_count == meteo_france.TENTATIVES_DE_CONNEXION

    @pytest.mark.parametrize("panne", [requests.ReadTimeout("lent"), requests.ConnectTimeout("lent"), requests.HTTPError("500")])
    def test_un_delai_depasse_ou_une_erreur_du_service_ne_sont_pas_reessayes(self, panne):
        appel = mock.Mock(side_effect=panne)

        with pytest.raises(type(panne)):
            meteo_france.avec_reprise(appel)
        assert appel.call_count == 1

    def test_la_vigilance_passe_malgre_un_refus_passager(self, tmp_path, monkeypatch):
        fichier = tmp_path / "cle"
        fichier.write_text("a.b.c")
        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))
        bonne = mock.Mock(json=lambda: {"product": {}}, raise_for_status=lambda: None)

        with mock.patch("core.meteo_france.requests.get", side_effect=[requests.ConnectionError("refusée"), bonne]) as appel:
            assert meteo_france.telecharger_carte() == {"product": {}}
        assert appel.call_count == 2


class TestCle:

    def _cle(self, tmp_path, monkeypatch, charge):
        segment = base64.urlsafe_b64encode(json.dumps(charge).encode()).decode().rstrip("=")
        fichier = tmp_path / "cle"
        fichier.write_text(f"entete.{segment}.signature\n")
        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))

    def test_l_echeance_est_lue_dans_la_cle(self, tmp_path, monkeypatch):
        self._cle(tmp_path, monkeypatch, {"exp": 1889413774})

        assert meteo_france.echeance_cle() == datetime.datetime.fromtimestamp(1889413774, tz=UTC)

    def test_sans_cle_rien_ne_part(self, tmp_path, monkeypatch):
        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(tmp_path / "absente"))

        assert meteo_france.lire_cle() is None
        assert meteo_france.echeance_cle() is None
        with mock.patch("core.meteo_france.requests.get") as appel:
            with pytest.raises(meteo_france.CleAbsente):
                meteo_france.telecharger_carte()
        appel.assert_not_called()

    def test_une_cle_illisible_ne_fait_rien_planter(self, tmp_path, monkeypatch):
        fichier = tmp_path / "cle"
        fichier.write_text("pas.un.jeton")
        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))

        assert meteo_france.echeance_cle() is None

    def test_la_cle_part_en_en_tete_jamais_dans_l_adresse(self, tmp_path, monkeypatch):
        self._cle(tmp_path, monkeypatch, {"exp": 1889413774})
        with mock.patch("core.meteo_france.requests.get") as appel:
            appel.return_value.json.return_value = {}
            meteo_france.telecharger_carte()

        (adresse,), options = appel.call_args
        assert "signature" not in adresse and "params" not in options
        assert options["headers"]["apikey"].endswith(".signature")


# ── Vigilance : l'annonce ───────────────────────────────────────────────────────────────────

class TestTexteDeLAnnonce:

    def test_un_episode_a_venir_dit_le_jour_et_les_heures_de_paris(self):
        niveau = {"couleur": 3, "debut": datetime.datetime(2026, 11, 15, 14, 0, tzinfo=UTC),
                  "fin": datetime.datetime(2026, 11, 15, 22, 0, tzinfo=UTC)}

        texte = meteo_france.texte_alerte("42", 1, niveau, MAINTENANT)

        assert texte == ("Vigilance ORANGE vent violent - Loire (42), aujourd'hui de 15h a 23h. "
                         "Source Meteo-France.")

    def test_un_episode_en_cours_dit_jusqu_a_quand(self):
        niveau = {"couleur": 4, "debut": datetime.datetime(2026, 11, 15, 8, 0, tzinfo=UTC),
                  "fin": datetime.datetime(2026, 11, 15, 23, 0, tzinfo=UTC)}

        texte = meteo_france.texte_alerte("26", 2, niveau, MAINTENANT)

        assert "ROUGE pluie-inondation - Drome (26), en cours jusqu'a minuit" in texte

    def test_le_texte_ne_porte_aucun_accent(self):
        """Il part tel quel sur la radio, où les accents se perdent."""
        niveau = {"couleur": 3, "debut": datetime.datetime(2026, 11, 16, 5, 0, tzinfo=UTC),
                  "fin": datetime.datetime(2026, 11, 16, 17, 0, tzinfo=UTC)}

        texte = meteo_france.texte_alerte("2B", 5, niveau, MAINTENANT)

        assert texte.isascii() and "demain de 6h a 18h" in texte

    def test_une_echeance_terminee_n_est_plus_un_niveau_en_cours(self):
        _publie, departements = meteo_france.analyser_carte(_carte([ORANGE_VENT_42]))
        apres = datetime.datetime(2026, 11, 16, 1, 0, tzinfo=UTC)

        assert meteo_france.niveaux_en_cours(departements["42"], apres) == {}
        assert meteo_france.niveaux_en_cours(departements["42"], MAINTENANT)[1]["couleur"] == 3


@pytest.mark.django_db
class TestAnnonceAuxInstitutions:

    def test_rien_ne_part_sans_abonnement(self, mairie, sans_messagerie):
        _enregistrer(ORANGE_VENT_42)

        assert meteo_france.diffuser_alertes(MAINTENANT) == []
        sans_messagerie.assert_not_called()

    def test_un_abonnement_inactif_ne_recoit_rien(self, abonnement, sans_messagerie):
        abonnement.actif = False
        abonnement.save()
        _enregistrer(ORANGE_VENT_42)

        assert meteo_france.diffuser_alertes(MAINTENANT) == []

    def test_l_orange_est_annonce_sur_la_radio_et_par_message(self, mairie, abonnement,
                                                               create_user, sans_messagerie):
        agent = create_user(username="agent-veille@test.fr", email="agent-veille@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie, utilisateur=agent, actif=True)
        canal = CanalMeshCore.objects.create(nom="Mairie", institution=mairie, actif=True,
                                             cle_partagee_hex="00" * 16)
        _enregistrer(ORANGE_VENT_42)

        annonces = meteo_france.diffuser_alertes(MAINTENANT)

        assert len(annonces) == 1 and "ORANGE vent violent - Loire (42)" in annonces[0]
        message = MessageCanalMeshCore.objects.get(canal=canal)
        assert message.contenu.startswith("Vigilance ORANGE vent violent")
        assert sans_messagerie.call_args_list[0].args[0] == agent
        assert VigilanceDiffusee.objects.get(institution=mairie, phenomene=1).couleur == 3

    def test_le_meme_episode_n_est_annonce_qu_une_fois(self, abonnement, sans_messagerie):
        _enregistrer(ORANGE_VENT_42)
        meteo_france.diffuser_alertes(MAINTENANT)

        _enregistrer(ORANGE_VENT_42)

        assert meteo_france.diffuser_alertes(MAINTENANT) == []

    def test_le_jaune_ne_franchit_pas_un_seuil_orange(self, abonnement, sans_messagerie):
        _enregistrer(_domaine("42", 2, [(1, 2, "2026-11-15T14:00:00Z", "2026-11-15T22:00:00Z")]))

        assert meteo_france.diffuser_alertes(MAINTENANT) == []

    def test_une_aggravation_est_annoncee_de_nouveau(self, abonnement, sans_messagerie):
        _enregistrer(ORANGE_VENT_42)
        meteo_france.diffuser_alertes(MAINTENANT)

        _enregistrer(_domaine("42", 4, [(1, 4, "2026-11-15T14:00:00Z", "2026-11-15T22:00:00Z")]))
        annonces = meteo_france.diffuser_alertes(MAINTENANT)

        assert len(annonces) == 1 and "ROUGE" in annonces[0]

    def test_une_baisse_au_dessus_du_seuil_ne_fait_aucun_bruit(self, mairie, abonnement, sans_messagerie):
        _enregistrer(_domaine("42", 4, [(1, 4, "2026-11-15T14:00:00Z", "2026-11-15T22:00:00Z")]))
        meteo_france.diffuser_alertes(MAINTENANT)

        _enregistrer(ORANGE_VENT_42)

        assert meteo_france.diffuser_alertes(MAINTENANT) == []
        assert VigilanceDiffusee.objects.get(institution=mairie, phenomene=1).couleur == 3

    def test_apres_un_retour_au_calme_l_episode_suivant_est_annonce(self, mairie, abonnement, sans_messagerie):
        _enregistrer(ORANGE_VENT_42)
        meteo_france.diffuser_alertes(MAINTENANT)
        _enregistrer(_domaine("42", 1, []))
        assert meteo_france.diffuser_alertes(MAINTENANT) == []
        assert not VigilanceDiffusee.objects.filter(institution=mairie).exists()

        _enregistrer(ORANGE_VENT_42)

        assert len(meteo_france.diffuser_alertes(MAINTENANT)) == 1

    def test_une_vigilance_annoncee_pour_demain_ne_l_est_pas_deux_fois(self, abonnement, sans_messagerie):
        demain = _domaine("42", 3, [(5, 3, "2026-11-16T05:00:00Z", "2026-11-16T17:00:00Z")])
        _enregistrer(_domaine("42", 1, []), domaines_j1=[demain])
        annonces = meteo_france.diffuser_alertes(MAINTENANT)
        assert "demain de 6h a 18h" in annonces[0]

        # Le lendemain, le même épisode est passé dans l'échéance du jour.
        lendemain = datetime.datetime(2026, 11, 16, 5, 30, tzinfo=UTC)
        _enregistrer(_domaine("42", 3, [(5, 3, "2026-11-15T14:00:00Z", "2026-11-15T22:00:00Z")]),
                     maintenant=lendemain)

        assert meteo_france.diffuser_alertes(MAINTENANT) == []

    def test_une_copie_trop_ancienne_n_annonce_rien(self, abonnement, sans_messagerie):
        _enregistrer(ORANGE_VENT_42, maintenant=MAINTENANT - datetime.timedelta(hours=7))

        assert meteo_france.diffuser_alertes(MAINTENANT) == []

    def test_les_administrateurs_recoivent_un_seul_resume(self, abonnement, create_user, sans_messagerie):
        administrateur = create_user(username="adm-veille@test.fr", email="adm-veille@test.fr",
                                     type="ADMIN")
        orage = (3, 3, "2026-11-15T14:00:00Z", "2026-11-15T22:00:00Z")
        vent = (1, 3, "2026-11-15T14:00:00Z", "2026-11-15T22:00:00Z")
        _enregistrer(_domaine("42", 3, [vent, orage]))

        annonces = meteo_france.diffuser_alertes(MAINTENANT)

        assert len(annonces) == 2
        resumes = [appel for appel in sans_messagerie.call_args_list if appel.args[0] == administrateur]
        assert len(resumes) == 1 and "vent violent" in resumes[0].args[1] and "orages" in resumes[0].args[1]

    def test_un_echec_de_messagerie_n_empeche_pas_l_annonce_radio(self, mairie, abonnement, create_user):
        agent = create_user(username="agent-veille2@test.fr", email="agent-veille2@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie, utilisateur=agent, actif=True)
        canal = CanalMeshCore.objects.create(nom="Mairie", institution=mairie, actif=True,
                                             cle_partagee_hex="00" * 16)
        _enregistrer(ORANGE_VENT_42)

        with mock.patch("core.matrix.envoyer_dm", side_effect=RuntimeError("Matrix en panne")):
            annonces = meteo_france.diffuser_alertes(MAINTENANT)

        assert len(annonces) == 1
        assert MessageCanalMeshCore.objects.filter(canal=canal).count() == 1


# ── Événements routiers ─────────────────────────────────────────────────────────────────────

def _fragment(genre, contenu, lat="45.44", lon="4.39", fin="2026-11-20T05:00:00+01:00"):
    fin_xml = f"<overallEndTime>{fin}</overallEndTime>" if fin else ""
    return f"""<situationRecord xsi:type="ns2:{genre}" id="x" version="1">
      <source><sourceIdentification>Direction interdépartementale des routes/DIR Centre-Est</sourceIdentification></source>
      <validity><validityTimeSpecification><overallStartTime>2026-11-14T08:00:00+01:00</overallStartTime>{fin_xml}</validityTimeSpecification></validity>
      <generalPublicComment><comment><values><value>Poids lourd couché.
Prudence.</value></values></comment><commentType>description</commentType></generalPublicComment>
      <generalPublicComment><comment><values><value>De Lyon vers Saint-Étienne</value></values></comment><commentType>locationDescriptor</commentType></generalPublicComment>
      <groupOfLocations xsi:type="ns2:Point"><tpegPointLocation><point>
        <pointCoordinates><latitude>{lat}</latitude><longitude>{lon}</longitude></pointCoordinates>
        <name><descriptor><values><value>Saint-Chamond</value></values></descriptor><tpegOtherPointDescriptorType>townName</tpegOtherPointDescriptorType></name>
        <name><descriptor><values><value>N88</value></values></descriptor><tpegOtherPointDescriptorType>linkName</tpegOtherPointDescriptorType></name>
      </point></tpegPointLocation>
      <pointAlongLinearElement><distanceAlongLinearElement><fromReferent><referentIdentifier>42PR12D</referentIdentifier></fromReferent></distanceAlongLinearElement></pointAlongLinearElement>
      </groupOfLocations>
      {contenu}
    </situationRecord>"""


def _flux(*situations):
    corps = "".join(
        f'<situation id="{reference}" version="1"><overallSeverity>high</overallSeverity>'
        f"<situationVersionTime>2026-11-15T10:00:00+01:00</situationVersionTime>{fragments}</situation>"
        for reference, fragments in situations
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<d2LogicalModel xmlns="http://datex2.eu/schema/2/2_0" xmlns:ns2="http://datex2.eu/schema/2/2_0" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><payloadPublication>'
        f"<publicationTime>2026-11-15T11:24:33+01:00</publicationTime>{corps}"
        "</payloadPublication></d2LogicalModel>"
    ).encode()


ACCIDENT = _fragment("Accident", "<accidentType>accident</accidentType>")
TRAVAUX = _fragment("MaintenanceWorks", "<roadMaintenanceType>roadworks</roadMaintenanceType>")
FERMEE = _fragment("RoadOrCarriagewayOrLaneManagement",
                   "<roadOrCarriagewayOrLaneManagementType>roadClosed</roadOrCarriagewayOrLaneManagementType>")


class TestLectureDuFluxRoutier:

    def test_une_situation_devient_une_ligne_lisible(self):
        publie_le, evenements = trafic_routier.analyser(_flux(("s1", ACCIDENT)))

        assert publie_le == datetime.datetime(2026, 11, 15, 10, 24, 33, tzinfo=UTC)
        (evenement,) = evenements
        assert evenement["reference"] == "s1"
        assert evenement["categorie"] == "ACCIDENT" and evenement["natures"] == ["Accident"]
        assert evenement["route"] == "N88" and evenement["commune_nom"] == "Saint-Chamond"
        assert evenement["departement_code"] == "42"
        assert evenement["gestionnaire"] == "DIR Centre-Est"
        assert evenement["description"] == "Poids lourd couché. Prudence."
        assert (evenement["location"].x, evenement["location"].y) == (4.39, 45.44)
        assert evenement["gravite"] == "high"

    def test_la_categorie_est_celle_du_fragment_le_plus_contraignant(self):
        """Des travaux AVEC route fermée sont une fermeture : c'est ce qu'un agent doit lire."""
        _publie, (evenement,) = trafic_routier.analyser(_flux(("s1", TRAVAUX + FERMEE)))

        assert evenement["categorie"] == "FERMETURE"
        assert evenement["natures"] == ["Travaux", "Route fermée"]

    def test_une_fin_inconnue_sur_un_fragment_rend_la_fin_inconnue(self):
        sans_fin = _fragment("Accident", "<accidentType>accident</accidentType>", fin=None)

        _publie, (evenement,) = trafic_routier.analyser(_flux(("s1", TRAVAUX + sans_fin)))

        assert evenement["fin"] is None

    def test_une_valeur_inconnue_ne_montre_jamais_d_anglais(self):
        inconnu = _fragment("GeneralObstruction", "<obstructionType>spillageOnTheRoad</obstructionType>")

        _publie, (evenement,) = trafic_routier.analyser(_flux(("s1", inconnu)))

        assert evenement["natures"] == ["Obstacle"]

    def test_une_situation_sans_position_est_ignoree(self):
        sans_position = _fragment("Accident", "", lat="?", lon="?")

        _publie, evenements = trafic_routier.analyser(_flux(("s1", sans_position), ("s2", ACCIDENT)))

        assert [e["reference"] for e in evenements] == ["s2"]

    @pytest.mark.django_db
    def test_ce_qui_quitte_le_flux_quitte_la_table(self):
        _publie, premiers = trafic_routier.analyser(_flux(("s1", ACCIDENT), ("s2", TRAVAUX)))
        trafic_routier.enregistrer(premiers)

        _publie, suivants = trafic_routier.analyser(_flux(("s2", FERMEE), ("s3", ACCIDENT)))
        trafic_routier.enregistrer(suivants)

        assert set(EvenementRoutier.objects.values_list("reference", "categorie")) == {
            ("s2", "FERMETURE"), ("s3", "ACCIDENT")}

    @pytest.mark.django_db
    def test_un_flux_vide_n_efface_rien(self):
        _publie, premiers = trafic_routier.analyser(_flux(("s1", ACCIDENT)))
        trafic_routier.enregistrer(premiers)

        with pytest.raises(ValueError):
            trafic_routier.enregistrer([])

        assert EvenementRoutier.objects.count() == 1


# ── Stations de carburant ───────────────────────────────────────────────────────────────────

def _station(identifiant, **champs):
    return {
        "id": identifiant, "geom": {"lon": 4.39, "lat": 45.44}, "cp": "42000",
        "adresse": "1 rue de la Veille", "ville": "Saint-Étienne", "code_departement": "42",
        "carburants_disponibles": ["Gazole"], "carburants_rupture_temporaire": None,
        "carburants_rupture_definitive": "E85;GPLc", "horaires_automate_24_24": "Oui",
        "gazole_prix": 1.699, "gazole_maj": "2026-11-15T06:00:00+00:00", **champs,
    }


class TestLectureDesStations:

    def test_rupture_temporaire_et_definitive_ne_sont_pas_confondues(self):
        (station,) = carburants.analyser([_station(1, carburants_rupture_temporaire="SP95;E10")])

        assert station["ruptures_temporaires"] == ["SP95", "E10"]
        assert station["ruptures_definitives"] == ["E85", "GPLc"]
        assert station["carburants_disponibles"] == ["Gazole"]
        assert station["automate_24_24"] is True
        assert station["prix"] == {"Gazole": {"prix": 1.699, "maj": "2026-11-15T06:00:00+00:00"}}
        assert station["mis_a_jour_le"] == datetime.datetime(2026, 11, 15, 6, 0, tzinfo=UTC)

    def test_une_station_sans_position_est_ignoree(self):
        stations = carburants.analyser([_station(1, geom=None), _station(2)])

        assert [s["reference"] for s in stations] == ["2"]

    @pytest.mark.django_db
    def test_un_export_tronque_ne_remplace_pas_la_copie(self, monkeypatch):
        monkeypatch.setattr(carburants, "MINIMUM_PLAUSIBLE", 2)
        carburants.enregistrer(carburants.analyser([_station(1), _station(2), _station(3)]))

        with pytest.raises(ValueError):
            carburants.enregistrer(carburants.analyser([_station(1)]))

        assert StationCarburant.objects.count() == 3

    @pytest.mark.django_db
    def test_une_station_fermee_disparait_au_releve_suivant(self, monkeypatch):
        monkeypatch.setattr(carburants, "MINIMUM_PLAUSIBLE", 2)
        carburants.enregistrer(carburants.analyser([_station(1), _station(2), _station(3)]))

        carburants.enregistrer(carburants.analyser(
            [_station(1, carburants_rupture_temporaire="Gazole"), _station(2)]))

        assert set(StationCarburant.objects.values_list("reference", flat=True)) == {"1", "2"}
        assert StationCarburant.objects.get(pk="1").ruptures_temporaires == ["Gazole"]


# ── Mesures des stations météorologiques ────────────────────────────────────────────────────

def _mesure(station="42005001", **champs):
    return {"lat": 45.53, "lon": 4.29, "geo_id_insee": station, "validity_time": "2026-11-15T09:12:00Z",
            "t": 289.55, "u": 59, "dd": 180, "ff": 6.4, "raf10": 9.0, "rr_per": 0.2, "sss": None, **champs}


def _horaire(station="42005001", heure="2026-11-15T09:00:00Z", pluie=1.5, rafale=12.8):
    return {"geo_id_insee": station, "validity_time": heure, "rr1": pluie, "raf": rafale}


class TestMesuresDesStations:

    def test_les_unites_de_la_source_sont_converties_une_fois(self):
        (mesure,) = observations_meteo.analyser_6_minutes([_mesure()]).values()

        assert mesure["temperature_c"] == 16.4          # 289,55 K
        assert mesure["vent_kmh"] == 23 and mesure["rafale_kmh"] == 32      # 6,4 et 9,0 m/s
        assert mesure["pluie_6min_mm"] == 0.2 and mesure["humidite_pct"] == 59
        assert mesure["departement_code"] == "42"
        assert mesure["mesure_le"] == datetime.datetime(2026, 11, 15, 9, 12, tzinfo=UTC)

    def test_une_mesure_absente_reste_absente(self):
        """Quatre stations sur dix seulement mesurent le vent : « pas de mesure » ne doit jamais
        s'afficher comme « vent nul »."""
        (mesure,) = observations_meteo.analyser_6_minutes([_mesure(ff=None, raf10=None, t=None)]).values()

        assert mesure["vent_kmh"] is None and mesure["rafale_kmh"] is None
        assert mesure["temperature_c"] is None

    def test_des_traces_de_pluie_valent_zero(self):
        """Constaté en production le 15/11/2026 : Paris-Montsouris affichait « -0,1 mm ». La
        source note ainsi une pluie non mesurable ; soustraite heure après heure, elle aurait
        aussi faussé le cumul."""
        (mesure,) = observations_meteo.analyser_6_minutes([_mesure(rr_per=-0.1)]).values()
        _heure, horaires = observations_meteo.analyser_horaire([_horaire(pluie=-0.1)])

        assert mesure["pluie_6min_mm"] == 0.0
        assert horaires["42005001"]["pluie_1h_mm"] == 0.0

    def test_l_outre_mer_garde_son_departement_a_trois_chiffres(self):
        assert observations_meteo.departement_de("97418110") == "974"
        assert observations_meteo.departement_de("42005001") == "42"
        assert observations_meteo.departement_de("abc") is None

    def test_une_ligne_sans_position_est_ignoree(self):
        mesures = observations_meteo.analyser_6_minutes([_mesure(lat=None), _mesure("69029001")])

        assert list(mesures) == ["69029001"]

    def test_le_cumul_de_pluie_s_additionne_heure_par_heure_sans_double_compte(self):
        h9 = datetime.datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
        h10 = h9 + datetime.timedelta(hours=1)

        cumuls, total, heures = observations_meteo.ajouter_au_cumul([], h9, 1.5, MAINTENANT)
        # Le même paquet horaire est relu à chaque passage tant que le suivant n'est pas paru.
        cumuls, total, heures = observations_meteo.ajouter_au_cumul(cumuls, h9, 1.5, MAINTENANT)
        assert (total, heures) == (1.5, 1)

        cumuls, total, heures = observations_meteo.ajouter_au_cumul(cumuls, h10, 4.0, h10)
        assert (total, heures) == (5.5, 2)

    def test_le_cumul_oublie_ce_qui_a_plus_de_vingt_quatre_heures(self):
        h9 = datetime.datetime(2026, 11, 15, 9, 0, tzinfo=UTC)
        cumuls, _total, _heures = observations_meteo.ajouter_au_cumul([], h9, 30.0, MAINTENANT)
        lendemain = h9 + datetime.timedelta(hours=25)

        cumuls, total, heures = observations_meteo.ajouter_au_cumul(cumuls, lendemain, 2.0, lendemain)

        assert (total, heures) == (2.0, 1)

    def test_le_creneau_pas_encore_publie_fait_reculer_au_precedent(self, tmp_path, monkeypatch):
        fichier = tmp_path / "cle"
        fichier.write_text("a.b.c")
        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))
        refus = mock.Mock(status_code=400)
        refus.raise_for_status.side_effect = requests.HTTPError(response=refus)
        vide = mock.Mock(status_code=200, json=lambda: [])
        plein = mock.Mock(status_code=200, json=lambda: [_mesure()])

        with mock.patch("core.observations_meteo.requests.get", side_effect=[refus, vide, plein]) as appel:
            paquet = observations_meteo.telecharger_6_minutes(MAINTENANT)

        assert paquet == [_mesure()]
        dates = [a.kwargs["params"]["date"] for a in appel.call_args_list]
        # 10 h 30 moins douze minutes, arrondi au créneau de six minutes, puis on recule.
        assert dates == ["2026-11-15T09:18:00Z", "2026-11-15T09:12:00Z", "2026-11-15T09:06:00Z"]
        assert all(a.kwargs["headers"]["apikey"] == "a.b.c" for a in appel.call_args_list)

    def test_une_panne_n_est_pas_prise_pour_un_creneau_en_retard(self, tmp_path, monkeypatch):
        fichier = tmp_path / "cle"
        fichier.write_text("a.b.c")
        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))
        panne = mock.Mock(status_code=503)
        panne.raise_for_status.side_effect = requests.HTTPError(response=panne)

        with mock.patch("core.observations_meteo.requests.get", return_value=panne) as appel:
            with pytest.raises(requests.HTTPError):
                observations_meteo.telecharger_6_minutes(MAINTENANT)

        assert appel.call_count == 1

    @pytest.mark.django_db
    def test_le_releve_ecrit_l_etat_courant_et_le_cumul(self, monkeypatch):
        monkeypatch.setattr(observations_meteo, "MINIMUM_PLAUSIBLE", 1)
        mesures = observations_meteo.analyser_6_minutes([_mesure(), _mesure("69029001", ff=None)])
        heure, horaires = observations_meteo.analyser_horaire([_horaire(), _horaire("69029001", pluie=None)])

        observations_meteo.enregistrer(mesures, heure, horaires, MAINTENANT)
        # Deuxième passage dix minutes plus tard, même paquet horaire.
        observations_meteo.enregistrer(mesures, heure, horaires, MAINTENANT + datetime.timedelta(minutes=10))

        boutheon = ObservationMeteo.objects.get(pk="42005001")
        assert boutheon.temperature_c == 16.4 and boutheon.vent_kmh == 23
        assert boutheon.pluie_1h_mm == 1.5 and boutheon.rafale_1h_kmh == 46
        assert (boutheon.pluie_24h_mm, boutheon.heures_cumulees) == (1.5, 1)
        autre = ObservationMeteo.objects.get(pk="69029001")
        assert autre.vent_kmh is None and autre.pluie_24h_mm is None and autre.heures_cumulees == 0

    @pytest.mark.django_db
    def test_sans_paquet_horaire_les_cumuls_connus_restent(self, monkeypatch):
        monkeypatch.setattr(observations_meteo, "MINIMUM_PLAUSIBLE", 1)
        mesures = observations_meteo.analyser_6_minutes([_mesure()])
        heure, horaires = observations_meteo.analyser_horaire([_horaire()])
        observations_meteo.enregistrer(mesures, heure, horaires, MAINTENANT)

        observations_meteo.enregistrer(mesures, None, None, MAINTENANT)

        assert ObservationMeteo.objects.get(pk="42005001").pluie_24h_mm == 1.5

    @pytest.mark.django_db
    def test_un_paquet_tronque_ne_remplace_pas_la_copie(self):
        with pytest.raises(ValueError):
            observations_meteo.enregistrer(observations_meteo.analyser_6_minutes([_mesure()]), None, None)

        assert ObservationMeteo.objects.count() == 0

    @pytest.mark.django_db
    def test_une_station_muette_depuis_deux_jours_est_retiree(self, monkeypatch):
        monkeypatch.setattr(observations_meteo, "MINIMUM_PLAUSIBLE", 1)
        ObservationMeteo.objects.create(
            station="01014002", location=Point(5.67, 46.28, srid=4326),
            mesure_le=MAINTENANT - datetime.timedelta(days=3), releve_le=MAINTENANT)

        observations_meteo.enregistrer(observations_meteo.analyser_6_minutes([_mesure()]), None, None, MAINTENANT)

        assert set(ObservationMeteo.objects.values_list("station", flat=True)) == {"42005001"}

    def test_la_liste_des_stations_donne_nom_et_altitude(self, tmp_path, monkeypatch):
        fichier = tmp_path / "cle"
        fichier.write_text("a.b.c")
        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))
        csv_source = ("Id_station;Id_omm;Nom_usuel;Latitude;Longitude;Altitude;Date_ouverture;Pack\n"
                      "42005001;07475;ST ETIENNE-BOUTHEON;45.53;4.29;395;1946-01-01;RADOME\n"
                      "42147001;;MONTBRISON_ÉCOLE;45.6;4.06;;2001-01-01;ETENDU\n").encode("iso-8859-1")

        with mock.patch("core.observations_meteo.requests.get") as appel:
            appel.return_value.content = csv_source
            stations = observations_meteo.telecharger_stations()

        assert stations == {"42005001": ("ST ETIENNE-BOUTHEON", 395), "42147001": ("MONTBRISON ÉCOLE", None)}

    @pytest.mark.django_db
    def test_les_mesures_se_lisent_de_la_station_la_plus_proche_a_la_plus_lointaine(self, api_client):
        def station(identifiant, nom, lon, lat):
            ObservationMeteo.objects.create(
                station=identifiant, nom=nom, location=Point(lon, lat, srid=4326),
                mesure_le=timezone.now(), temperature_c=12.5, rafale_kmh=85, releve_le=timezone.now())
        station("42005001", "BOUTHEON", 4.29, 45.53)
        station("42218001", "CENTRE", 4.39, 45.44)
        station("75114001", "PARIS", 2.34, 48.82)

        corps = api_client.get(reverse("observations_meteo"), {"lat": "45.44", "lon": "4.39"}).json()

        assert [r["nom"] for r in corps["resultats"]] == ["CENTRE", "BOUTHEON"]
        assert corps["resultats"][0]["distance_km"] == 0.0
        assert 10 < corps["resultats"][1]["distance_km"] < 15
        assert corps["resultats"][0]["rafale_kmh"] == 85 and corps["resultats"][0]["vent_kmh"] is None
        assert corps["source"] == "Météo-France" and corps["emprise_connue"] is True


# ── Pluie prévue ────────────────────────────────────────────────────────────────────────────

def _png(largeur=155, hauteur=105, ligne_rouge=None):
    """Image transparente aux proportions de l'emprise réelle (un pixel par dixième de degré),
    avec éventuellement une ligne rouge opaque à la hauteur donnée."""
    from PIL import Image

    image = Image.new("RGBA", (largeur, hauteur), (0, 0, 0, 0))
    if ligne_rouge is not None:
        for x in range(largeur):
            image.putpixel((x, ligne_rouge), (255, 0, 0, 255))
    sortie = io.BytesIO()
    image.save(sortie, format="PNG")
    return sortie.getvalue()


def _reponse_image(contenu=None):
    return mock.Mock(status_code=200, headers={"content-type": "image/png"},
                     content=contenu or _png(), raise_for_status=lambda: None)


def _reponse_erreur_xml():
    """Ce que rend le service pour un calcul pas encore paru : 200, mais un document XML."""
    return mock.Mock(status_code=200, headers={"content-type": "text/xml"},
                     content=b"<ServiceExceptionReport/>", raise_for_status=lambda: None)


@pytest.fixture
def cle_meteo(tmp_path, monkeypatch):
    fichier = tmp_path / "cle"
    fichier.write_text("a.b.c")
    monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(fichier))
    monkeypatch.setattr(pluie, "PAUSE_ENTRE_IMAGES_S", 0)


class TestPluiePrevue:

    def test_les_echeances_sont_les_quarts_d_heure_des_trois_heures_a_venir(self):
        echeances = pluie.echeances_voulues(MAINTENANT)        # 9 h 30 TU

        assert len(echeances) == 13
        assert echeances[0] == MAINTENANT and echeances[1] - echeances[0] == datetime.timedelta(minutes=15)
        assert echeances[-1] == MAINTENANT + datetime.timedelta(hours=3)
        # À 9 h 44, le quart d'heure en cours reste celui de 9 h 30.
        assert pluie.echeances_voulues(MAINTENANT + datetime.timedelta(minutes=14))[0] == MAINTENANT

    def test_la_reprojection_garde_les_bords_et_deplace_le_milieu_vers_le_nord(self):
        """En latitude/longitude, la ligne du milieu est à 46,25° ; en Mercator, le milieu de
        l'image est plus au nord (46,5° environ). Une pluie située à 46,25° doit donc se
        retrouver SOUS le milieu de l'image de sortie -- c'est toute la correction."""
        from PIL import Image

        # Ligne 52 sur 105 : le milieu de l'image source, soit 46,25° de latitude.
        sortie = Image.open(io.BytesIO(pluie.vers_mercator(_png(ligne_rouge=52)))).convert("RGBA")

        rouges = [y for y in range(sortie.height) if sortie.getpixel((5, y))[3] > 0]
        assert rouges, "la pluie a disparu à la reprojection"
        milieu = sum(rouges) / len(rouges)
        assert sortie.height / 2 < milieu < sortie.height * 0.56
        # Pixels carrés à l'écran : l'image s'allonge avec la latitude.
        assert sortie.width == 155 and sortie.height > 105

    def test_la_reprojection_garde_la_transparence(self):
        from PIL import Image

        sortie = Image.open(io.BytesIO(pluie.vers_mercator(_png(ligne_rouge=10)))).convert("RGBA")

        assert sortie.getpixel((0, sortie.height - 1))[3] == 0
        assert max(sortie.getpixel((0, y))[3] for y in range(sortie.height)) == 255

    def test_la_cle_part_en_en_tete_et_l_emprise_est_nationale(self, cle_meteo):
        with mock.patch("core.pluie.requests.get", return_value=_reponse_image()) as appel:
            pluie.telecharger_image(MAINTENANT, MAINTENANT)

        options = appel.call_args.kwargs
        assert options["headers"] == {"apikey": "a.b.c"}
        assert options["params"]["bbox"] == "41.0,-5.5,51.5,10.0"       # latitude d'abord
        assert options["params"]["reference_time"] == "2026-11-15T09:30:00Z"
        assert "apikey" not in options["params"]

    def test_une_reponse_qui_n_est_pas_une_image_vaut_pas_d_image(self, cle_meteo):
        with mock.patch("core.pluie.requests.get", return_value=_reponse_erreur_xml()):
            assert pluie.telecharger_image(MAINTENANT, MAINTENANT) is None

    @pytest.mark.django_db
    def test_le_releve_recule_jusqu_au_dernier_calcul_paru(self, cle_meteo):
        def service(_adresse, params=None, **_reste):
            # Le calcul de 9 h n'est pas encore paru ; celui de 8 h répond.
            return _reponse_erreur_xml() if params["reference_time"] == "2026-11-15T09:00:00Z" else _reponse_image()

        with mock.patch("core.pluie.requests.get", side_effect=service):
            assert pluie.relever(MAINTENANT) == 13

        calculs = set(ImagePluie.objects.values_list("calcul", flat=True))
        assert calculs == {datetime.datetime(2026, 11, 15, 8, 0, tzinfo=UTC)}
        assert ImagePluie.objects.order_by("echeance").first().echeance == MAINTENANT

    @pytest.mark.django_db
    def test_ce_qui_est_deja_copie_n_est_pas_redemande(self, cle_meteo):
        with mock.patch("core.pluie.requests.get", return_value=_reponse_image()) as appel:
            pluie.relever(MAINTENANT)
            premier_passage = appel.call_count
            pluie.relever(MAINTENANT + datetime.timedelta(minutes=10))

        assert premier_passage == 13
        # Rien au second passage : le calcul de l'heure est déjà copié et aucun quart d'heure
        # nouveau n'est à prendre.
        assert appel.call_count == premier_passage

    @pytest.mark.django_db
    def test_le_quart_d_heure_nouveau_est_le_seul_demande(self, cle_meteo):
        with mock.patch("core.pluie.requests.get", return_value=_reponse_image()) as appel:
            pluie.relever(MAINTENANT)
            pluie.relever(MAINTENANT + datetime.timedelta(minutes=20))       # 9 h 50

        assert appel.call_count == 13 + 1
        assert appel.call_args.kwargs["params"]["time"] == "2026-11-15T12:45:00Z"

    @pytest.mark.django_db
    def test_un_nouveau_calcul_remplace_les_images_et_les_echeances_passees_partent(self, cle_meteo):
        with mock.patch("core.pluie.requests.get", return_value=_reponse_image()):
            pluie.relever(MAINTENANT)
            plus_tard = MAINTENANT + datetime.timedelta(hours=1)
            pluie.relever(plus_tard)

        images = list(ImagePluie.objects.order_by("echeance"))
        # Le quart d'heure précédent est gardé vingt minutes (on vient peut-être de le regarder) ;
        # tout ce qui est plus ancien est parti.
        assert images[0].echeance == plus_tard - datetime.timedelta(minutes=15)
        assert images[-1].echeance == plus_tard + datetime.timedelta(hours=3) and len(images) == 14
        # Tout ce qui est à venir vient du nouveau calcul, y compris les échéances déjà copiées.
        assert {i.calcul for i in images if i.echeance >= plus_tard} == {
            datetime.datetime(2026, 11, 15, 10, 0, tzinfo=UTC)}

    @pytest.mark.django_db
    def test_une_image_en_panne_ne_fait_pas_perdre_les_autres(self, cle_meteo, monkeypatch):
        """Constaté en service le 15/11/2026 : Météo-France a refusé la connexion sur la
        quatrième image, et le relevé entier était compté en échec avec trois images."""
        monkeypatch.setattr(meteo_france, "TENTATIVES_DE_CONNEXION", 1)
        appels = {"n": 0}

        def service(*_positionnels, **_options):
            appels["n"] += 1
            if appels["n"] == 4:
                raise requests.ConnectionError("refusée")
            return _reponse_image()

        with mock.patch("core.pluie.requests.get", side_effect=service):
            assert pluie.relever(MAINTENANT) == 12

        # Au passage suivant, seule l'image manquante est redemandée.
        with mock.patch("core.pluie.requests.get", return_value=_reponse_image()) as appel:
            assert pluie.relever(MAINTENANT + datetime.timedelta(minutes=5)) == 13
        assert appel.call_count == 1

    @pytest.mark.django_db
    def test_si_rien_de_ce_qui_manque_ne_vient_le_releve_est_en_echec(self, cle_meteo, monkeypatch):
        """Une panne isolée n'est qu'un avertissement ; mais si le service ne rend plus rien de
        ce qu'on lui demande, le relevé doit échouer -- sans quoi la panne passerait inaperçue."""
        monkeypatch.setattr(meteo_france, "TENTATIVES_DE_CONNEXION", 1)
        with mock.patch("core.pluie.requests.get", return_value=_reponse_image()):
            pluie.relever(MAINTENANT)

        with mock.patch("core.pluie.requests.get", side_effect=requests.ConnectionError("refusée")):
            with pytest.raises(ValueError, match="aucune des 1 échéances manquantes"):
                pluie.relever(MAINTENANT + datetime.timedelta(minutes=20))

        assert ImagePluie.objects.count() == 13

    @pytest.mark.django_db
    def test_sans_aucun_calcul_la_copie_precedente_reste(self, cle_meteo):
        with mock.patch("core.pluie.requests.get", return_value=_reponse_image()):
            pluie.relever(MAINTENANT)

        with mock.patch("core.pluie.requests.get", return_value=_reponse_erreur_xml()):
            # Dix minutes plus tard rien ne manque : rien n'est demandé, rien n'échoue.
            assert pluie.relever(MAINTENANT + datetime.timedelta(minutes=10)) == 13
            # Une heure plus tard il manque quatre quarts d'heure, et le service ne rend rien.
            with pytest.raises(ValueError):
                pluie.relever(MAINTENANT + datetime.timedelta(hours=1))

        # Les images encore à venir restent ; seules les échéances passées sont parties.
        assert ImagePluie.objects.count() == 10

    @pytest.mark.django_db
    def test_la_carte_lit_les_echeances_et_les_images_sans_appel_sortant(self, api_client):
        echeance = timezone.now().replace(second=0, microsecond=0)
        ImagePluie.objects.create(echeance=echeance, calcul=echeance, image=_png(), releve_le=timezone.now())

        with mock.patch("core.pluie.requests.get") as appel:
            liste = api_client.get(reverse("pluie_prevue")).json()
            image = api_client.get(reverse("pluie_prevue_image"), {"echeance": liste["echeances"][0]})
            absente = api_client.get(reverse("pluie_prevue_image"), {"echeance": "2020-01-01T00:00:00Z"})

        appel.assert_not_called()
        assert liste["coins"] == [[-5.5, 51.5], [10.0, 51.5], [10.0, 41.0], [-5.5, 41.0]]
        assert liste["source"] == "Météo-France" and len(liste["echeances"]) == 1
        assert image.status_code == 200 and image["Content-Type"] == "image/png"
        assert image.content == _png()
        assert absente.status_code == 404
        assert api_client.get(reverse("pluie_prevue_image"), {"echeance": "pas une date"}).status_code == 404


# ── Le relevé planifié ──────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestRelevePlanifie:

    def _source(self, monkeypatch, relever, code="TRAFIC_ROUTIER"):
        source = sources_ouvertes.SOURCES[code]._replace(relever=relever)
        monkeypatch.setitem(sources_ouvertes.SOURCES, code, source)

    def test_un_releve_reussi_laisse_sa_trace(self, monkeypatch):
        self._source(monkeypatch, lambda: 250)

        assert sources_ouvertes.relever_source("TRAFIC_ROUTIER") == "réussi"

        trace = ReleveSourceOuverte.objects.get(pk="TRAFIC_ROUTIER")
        assert trace.lignes == 250 and trace.erreur == "" and trace.dernier_succes is not None
        assert sources_ouvertes.est_perime("TRAFIC_ROUTIER") is False

    def test_une_source_relevee_a_l_instant_n_est_pas_rappelee(self, monkeypatch):
        appels = []
        self._source(monkeypatch, lambda: appels.append(1) or 1)
        sources_ouvertes.relever_source("TRAFIC_ROUTIER")

        assert sources_ouvertes.relever_source("TRAFIC_ROUTIER") == "ignoré"
        assert sources_ouvertes.relever_source("TRAFIC_ROUTIER", forcer=True) == "réussi"
        assert len(appels) == 2

    def test_une_panne_est_consignee_sans_rien_faire_echouer(self, monkeypatch):
        def en_panne():
            raise requests.ConnectionError("réseau coupé")
        self._source(monkeypatch, en_panne)

        assert sources_ouvertes.relever_source("TRAFIC_ROUTIER") == "échec"

        trace = ReleveSourceOuverte.objects.get(pk="TRAFIC_ROUTIER")
        assert "réseau coupé" in trace.erreur and trace.dernier_succes is None
        assert sources_ouvertes.est_perime("TRAFIC_ROUTIER") is True

    def test_un_echec_ne_fait_pas_oublier_le_dernier_succes(self, monkeypatch):
        self._source(monkeypatch, lambda: 5)
        sources_ouvertes.relever_source("TRAFIC_ROUTIER")
        succes = ReleveSourceOuverte.objects.get(pk="TRAFIC_ROUTIER").dernier_succes

        def en_panne():
            raise ValueError("format inattendu")
        self._source(monkeypatch, en_panne)
        sources_ouvertes.relever_source("TRAFIC_ROUTIER", forcer=True)

        trace = ReleveSourceOuverte.objects.get(pk="TRAFIC_ROUTIER")
        assert trace.dernier_succes == succes and trace.lignes == 5

    def test_sans_cle_la_vigilance_se_tait(self, monkeypatch, tmp_path):
        monkeypatch.setenv("METEOFRANCE_CLE_API_FILE", str(tmp_path / "absente"))

        assert sources_ouvertes.relever_source("VIGILANCE_METEO") == "échec"
        assert ReleveSourceOuverte.objects.get(pk="VIGILANCE_METEO").erreur == "aucune clé sur cette machine"

    def test_la_supervision_voit_une_source_perimee(self, monkeypatch):
        from core.metrics import VeilleCollector

        self._source(monkeypatch, lambda: 9)
        sources_ouvertes.relever_source("TRAFIC_ROUTIER")
        ReleveSourceOuverte.objects.filter(pk="TRAFIC_ROUTIER").update(
            dernier_succes=timezone.now() - datetime.timedelta(hours=2))

        familles = {famille.name: famille for famille in VeilleCollector().collect()}

        perimee = {s.labels["source"]: s.value for s in familles["assista_source_ouverte_perimee"].samples}
        assert perimee == {"TRAFIC_ROUTIER": 1}
        assert familles["assista_source_ouverte_age_secondes"].samples[0].value > 7000


# ── Les lectures ────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestLectures:

    def test_la_vigilance_se_lit_sans_compte_et_sans_appel_sortant(self, api_client):
        _enregistrer(ORANGE_VENT_42, _domaine("FRA", 3, []), _domaine("01", 1, []),
                     maintenant=timezone.now())

        with mock.patch("core.meteo_france.requests.get") as appel:
            reponse = api_client.get(reverse("vigilance_meteo"), {"departement": "42"})

        appel.assert_not_called()
        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["disponible"] is True and corps["perime"] is False
        assert corps["source"] == "Météo-France"
        assert corps["mon_departement"]["nom"] == "Loire" and corps["mon_departement"]["couleur_j"] == 3
        assert [d["departement_code"] for d in corps["departements"]] == ["42"]
        assert "bulletin" not in corps["departements"][0]

    def test_le_departement_de_l_appelant_est_celui_de_son_institution(self, mairie, create_user):
        agent = create_user(username="agent-veille3@test.fr", email="agent-veille3@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie, utilisateur=agent, actif=True)
        client = APIClient()
        client.force_authenticate(user=agent)
        _enregistrer(ORANGE_VENT_42, maintenant=timezone.now())

        corps = client.get(reverse("vigilance_meteo")).json()

        assert corps["mon_departement"]["departement_code"] == "42"

    def test_sans_releve_la_page_le_dit(self, api_client):
        corps = api_client.get(reverse("vigilance_meteo")).json()

        assert corps["disponible"] is False and corps["mon_departement"] is None

    def test_la_carte_nationale_est_servie_depuis_la_copie(self, api_client):
        assert api_client.get(reverse("vigilance_meteo_vignette", args=["J"])).status_code == 404
        meteo_france.enregistrer_vignette("J", b"\x89PNG-image")

        reponse = api_client.get(reverse("vigilance_meteo_vignette", args=["J"]))

        assert reponse.status_code == 200 and reponse["Content-Type"] == "image/png"
        assert reponse.content == b"\x89PNG-image"
        assert VignetteVigilanceMeteo.objects.count() == 1

    def _evenement(self, reference, lon, lat, categorie="TRAVAUX"):
        EvenementRoutier.objects.create(
            reference=reference, categorie=categorie, natures=["Travaux"], route="N88",
            location=Point(lon, lat, srid=4326), releve_le=timezone.now())

    def test_les_evenements_routiers_sont_bornes_a_l_emprise(self, api_client):
        self._evenement("pres", 4.40, 45.45)
        self._evenement("ferme", 4.45, 45.40, categorie="FERMETURE")
        self._evenement("loin", 2.35, 48.85)

        corps = api_client.get(reverse("evenements_routiers"),
                               {"lat": "45.44", "lon": "4.39", "rayon_km": "20"}).json()

        # La fermeture passe devant les travaux.
        assert [e["reference"] for e in corps["resultats"]] == ["ferme", "pres"]
        assert corps["resultats"][0]["categorie_libelle"] == "Route fermée"
        assert corps["emprise_connue"] is True and corps["rayon_km"] == 20
        assert corps["perime"] is True      # aucun relevé consigné dans ce test

    def test_la_carte_demande_par_rectangle(self, api_client):
        self._evenement("pres", 4.40, 45.45)
        self._evenement("loin", 2.35, 48.85)

        corps = api_client.get(reverse("evenements_routiers"), {"bbox": "4,45,5,46"}).json()

        assert [e["reference"] for e in corps["resultats"]] == ["pres"]
        assert api_client.get(reverse("evenements_routiers"), {"bbox": "5,45,4,46"}).status_code == 400

    def test_sans_emprise_ni_institution_la_reponse_est_vide_et_le_dit(self, api_client):
        self._evenement("pres", 4.40, 45.45)

        corps = api_client.get(reverse("evenements_routiers")).json()

        assert corps["emprise_connue"] is False and corps["resultats"] == []

    def test_l_emprise_par_defaut_est_la_commune_de_l_institution(self, mairie, create_user):
        agent = create_user(username="agent-veille4@test.fr", email="agent-veille4@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie, utilisateur=agent, actif=True)
        client = APIClient()
        client.force_authenticate(user=agent)
        self._evenement("pres", 4.40, 45.45)
        self._evenement("loin", 2.35, 48.85)

        corps = client.get(reverse("evenements_routiers")).json()

        assert [e["reference"] for e in corps["resultats"]] == ["pres"]
        assert corps["centre"] == {"latitude": 45.44, "longitude": 4.39}

    def test_les_stations_disent_ou_l_on_peut_encore_faire_le_plein(self, api_client):
        def station(reference, disponibles, ruptures):
            StationCarburant.objects.create(
                reference=reference, ville="Saint-Étienne", location=Point(4.39, 45.44, srid=4326),
                carburants_disponibles=disponibles, ruptures_temporaires=ruptures,
                releve_le=timezone.now())
        station("pleine", ["Gazole", "E10"], [])
        station("partielle", ["Gazole"], ["E10"])
        station("vide", [], ["Gazole", "E10"])

        parametres = {"lat": "45.44", "lon": "4.39"}
        toutes = api_client.get(reverse("stations_carburant"), parametres).json()
        en_rupture = api_client.get(reverse("stations_carburant"), {**parametres, "rupture": "1"}).json()

        assert toutes["bilan"] == {"total": 3, "en_rupture": 2, "a_sec": 1}
        assert len(toutes["resultats"]) == 3
        assert {s["reference"] for s in en_rupture["resultats"]} == {"partielle", "vide"}
        assert en_rupture["bilan"] == toutes["bilan"]

    def test_au_dela_du_plafond_les_fermetures_restent_et_le_bilan_reste_juste(self, api_client, monkeypatch):
        from core import views_veille

        monkeypatch.setattr(views_veille, "RESULTATS_MAX", 2)
        for i in range(3):
            self._evenement(f"travaux-{i}", 4.40, 45.45)
        self._evenement("ferme", 4.41, 45.45, categorie="FERMETURE")
        for i in range(4):
            StationCarburant.objects.create(
                reference=f"s{i}", ville="Saint-Étienne", location=Point(4.39, 45.44, srid=4326),
                carburants_disponibles=[], ruptures_temporaires=["Gazole"], releve_le=timezone.now())

        parametres = {"lat": "45.44", "lon": "4.39"}
        routes = api_client.get(reverse("evenements_routiers"), parametres).json()
        stations = api_client.get(reverse("stations_carburant"), parametres).json()

        assert routes["tronque"] is True and routes["resultats"][0]["reference"] == "ferme"
        assert stations["tronque"] is True and len(stations["resultats"]) == 2
        assert stations["bilan"] == {"total": 4, "en_rupture": 4, "a_sec": 4}

    def test_seul_un_acteur_institutionnel_regle_l_annonce(self, mairie, create_user):
        citoyen = create_user(username="citoyen-veille@test.fr", email="citoyen-veille@test.fr")
        client = APIClient()
        client.force_authenticate(user=citoyen)
        adresse = reverse("configurationalertevigilance-list")

        assert client.post(adresse, {"institution": str(mairie.id), "actif": True}, format="json").status_code == 403

        agent = create_user(username="agent-veille5@test.fr", email="agent-veille5@test.fr", type="AUT_LOCALE")
        ContactInstitution.objects.create(institution=mairie, utilisateur=agent, actif=True)
        client.force_authenticate(user=agent)
        reponse = client.post(adresse, {"institution": str(mairie.id), "actif": True, "couleur_min": 4}, format="json")

        assert reponse.status_code == 201 and reponse.json()["couleur_min"] == 4
        assert client.post(adresse, {"institution": str(mairie.id), "actif": True}, format="json").status_code == 400
        assert len(client.get(adresse, {"institution": str(mairie.id)}).json()) == 1


# ── Défibrillateurs ─────────────────────────────────────────────────────────────────────────

ENTETE_DAE = ("gid;c_gid;c_etat_valid;c_nom;c_lat_coor1;c_long_coor1;c_adr_num;c_adr_voie;c_com_cp;"
              "c_com_insee;c_com_nom;c_acc;c_acc_lib;c_acc_etg;c_acc_complt;c_disp_complt;"
              "c_etat_fonct;c_dermnt;c_maj_don;c_expt_rais;c_etat;c_doublon;c_dispo_horaires")


def _ligne_dae(gid, insee="42218", etat="Actif", valide="validées", fonction="En fonctionnement",
               doublon="f", exploitant="COMMUNE DE SAINT-ETIENNE"):
    return (f"{gid};{gid};{valide};DAE G5;45.44;4.39;1;place de l'Hôtel de Ville;42000;{insee};"
            f"Saint-Étienne;Extérieur;t;0;Sous le porche;;{fonction};2026-03-01;2026-06-01;"
            f"{exploitant};{etat};{doublon};24/7")


class TestDefibrillateurs:

    def _lire(self, *lignes, communes=("42218",)):
        return dae.lire(io.StringIO("\n".join((ENTETE_DAE,) + lignes)), set(communes))

    def test_un_appareil_en_service_est_propose_comme_ressource(self):
        (site,) = self._lire(_ligne_dae(101))

        assert site.source == "GEODAE" and site.source_id == "101"
        assert site.categorie == "DEFIBRILLATEUR"
        assert site.est_ressource is True and site.est_enjeu is False
        assert site.nom == "Défibrillateur — COMMUNE DE SAINT-ETIENNE"
        assert site.adresse == "1 place de l'Hôtel de Ville, 42000 Saint-Étienne"
        assert (site.latitude, site.longitude) == (45.44, 4.39)
        assert site.commune_code == "42218"
        assert site.attributs["acces"] == "Extérieur" and site.attributs["acces_libre"] is True
        assert site.attributs["emplacement"] == "Sous le porche"
        assert site.attributs["disponibilite"] == "24/7"

    def test_seuls_les_appareils_du_perimetre_sont_lus(self):
        sites = self._lire(_ligne_dae(1), _ligne_dae(2, insee="69123"))

        assert [s.source_id for s in sites] == ["1"]

    @pytest.mark.parametrize("defaut", [
        {"etat": "Supprimé définitivement"}, {"valide": "en attente de validation"},
        {"fonction": "Hors service"}, {"doublon": "t"},
    ])
    def test_un_appareil_retire_ou_douteux_n_est_pas_propose(self, defaut):
        assert self._lire(_ligne_dae(1, **defaut)) == []

    def test_sans_exploitant_le_nom_saisi_est_garde(self):
        (site,) = self._lire(_ligne_dae(1, exploitant=""))

        assert site.nom == "DAE G5"

    def test_la_source_est_branchee_comme_les_autres_fichiers_nationaux(self):
        assert CONNECTEURS["GEODAE"] is dae
        assert "GEODAE" in SOURCES_ASYNCHRONES and "GEODAE" in SOURCES_SANS_DECOUPAGE

    def test_un_fichier_injoignable_est_dit_sans_exception(self):
        from core.opendata.base import perimetre_commune

        with mock.patch("core.opendata.dae._telecharger", side_effect=requests.ConnectionError("coupé")):
            collecte = dae.collecter(perimetre_commune("42218"))

        assert collecte == [] and "n'a pas pu être téléchargé" in collecte.tronque


# ── Relais de la recherche d'adresse ────────────────────────────────────────────────────────

REPONSE_ADRESSE = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [2.29, 49.89]},
     "properties": {"label": "8 Boulevard du Port 80000 Amiens", "citycode": "80021"}}]}


@pytest.fixture
def geocodage():
    from django.core.cache import cache

    cache.clear()       # le limiteur de débit compte dans le cache
    with mock.patch("core.views_adresses.requests.get") as appel:
        appel.return_value.json.return_value = REPONSE_ADRESSE
        yield appel


class TestRelaisDAdresse:

    def test_la_recherche_passe_par_le_serveur_et_rend_la_meme_reponse(self, api_client, geocodage):
        reponse = api_client.get(reverse("adresses_recherche"), {"q": "8 bd du port amiens"})

        assert reponse.status_code == 200 and reponse.json() == REPONSE_ADRESSE
        (adresse,), options = geocodage.call_args
        assert adresse == "https://data.geopf.fr/geocodage/search"
        assert options["params"] == {"q": "8 bd du port amiens", "limit": 5, "index": "address"}

    def test_rien_du_navigateur_ne_part_vers_le_service(self, api_client, geocodage):
        api_client.get(reverse("adresses_recherche"), {"q": "8 bd du port amiens"},
                       HTTP_USER_AGENT="NavigateurDeTest/1.0", HTTP_REFERER="https://exemple.test/demande",
                       HTTP_X_FORWARDED_FOR="203.0.113.7", HTTP_COOKIE="session=abc")

        _positionnels, options = geocodage.call_args
        assert set(options) == {"params", "timeout"}        # ni en-têtes, ni cookies

    def test_la_position_qui_sert_au_classement_est_arrondie_au_kilometre(self, api_client, geocodage):
        api_client.get(reverse("adresses_recherche"),
                       {"q": "rue de la paix", "lat": "45.439871", "lon": "4.387213"})

        parametres = geocodage.call_args.kwargs["params"]
        assert (parametres["lat"], parametres["lon"]) == (45.44, 4.39)

    def test_seuls_les_parametres_connus_sont_transmis(self, api_client, geocodage):
        api_client.get(reverse("adresses_recherche"), {
            "q": "mairie", "limit": "500", "type": "municipality", "citycode": "42218",
            "postcode": "42000 OR 1=1", "autocomplete": "0", "index": "poi", "callback": "x"})

        assert geocodage.call_args.kwargs["params"] == {
            "q": "mairie", "limit": 10, "index": "address", "type": "municipality", "citycode": "42218"}

    def test_une_question_trop_courte_ne_declenche_aucun_appel(self, api_client, geocodage):
        reponse = api_client.get(reverse("adresses_recherche"), {"q": " a "})

        assert reponse.json() == {"type": "FeatureCollection", "features": []}
        geocodage.assert_not_called()

    def test_une_question_demesuree_est_coupee(self, api_client, geocodage):
        api_client.get(reverse("adresses_recherche"), {"q": "x" * 5000})

        assert len(geocodage.call_args.kwargs["params"]["q"]) == 200

    def test_un_service_en_panne_rend_une_liste_vide_pas_une_erreur(self, api_client, geocodage, caplog):
        geocodage.side_effect = requests.ConnectionError("https://data.geopf.fr/geocodage/search?q=8+bd+du+port")

        reponse = api_client.get(reverse("adresses_recherche"), {"q": "8 bd du port amiens"})

        assert reponse.status_code == 200 and reponse.json()["features"] == []
        # La question posée ne doit pas finir dans le journal.
        assert "port" not in caplog.text

    def test_le_geocodage_inverse_garde_la_precision_d_un_numero_de_rue(self, api_client, geocodage):
        reponse = api_client.get(reverse("adresses_inverse"), {"lat": "45.4398712", "lon": "4.3872139"})

        assert reponse.status_code == 200 and reponse.json() == REPONSE_ADRESSE
        (adresse,), options = geocodage.call_args
        assert adresse == "https://data.geopf.fr/geocodage/reverse"
        assert options["params"] == {"lat": 45.4399, "lon": 4.3872, "limit": 1, "index": "address"}

    @pytest.mark.parametrize("parametres", [{}, {"lat": "45"}, {"lat": "abc", "lon": "4"},
                                            {"lat": "95", "lon": "4"}])
    def test_une_position_absente_ou_absurde_est_refusee(self, api_client, geocodage, parametres):
        assert api_client.get(reverse("adresses_inverse"), parametres).status_code == 400
        geocodage.assert_not_called()

    def test_le_relais_ne_sert_pas_a_moissonner(self, api_client, geocodage):
        from core.views_adresses import DebitGeocodage

        with mock.patch.object(DebitGeocodage, "rate", "3/min"), \
                mock.patch.object(DebitGeocodage, "THROTTLE_RATES", {"geocodage": "3/min"}, create=True):
            codes = [api_client.get(reverse("adresses_recherche"), {"q": "rue de la paix"}).status_code
                     for _ in range(5)]

        assert codes == [200, 200, 200, 429, 429]
        assert geocodage.call_count == 3


# ── Zone atteignable depuis un point ────────────────────────────────────────────────────────

CONTOUR = {"type": "Polygon", "coordinates": [[[4.38, 45.43], [4.40, 45.43], [4.40, 45.45], [4.38, 45.43]]]}


@pytest.fixture
def itineraires():
    from django.core.cache import cache

    cache.clear()
    with mock.patch("core.views_adresses.requests.get") as appel:
        appel.return_value.json.return_value = {"geometry": CONTOUR, "costValue": 600}
        yield appel


class TestZoneAtteignable:

    def test_le_serveur_pose_la_question_et_rend_le_contour(self, api_client, itineraires):
        reponse = api_client.get(reverse("zone_atteignable"), {"lat": "45.4398712", "lon": "4.3872139"})

        assert reponse.status_code == 200
        assert reponse.json() == {"minutes": 10, "mode": "voiture", "contour": CONTOUR,
                                  "source": "Géoplateforme IGN (BD TOPO)"}
        (adresse,), options = itineraires.call_args
        assert adresse == "https://data.geopf.fr/navigation/isochrone"
        # Longitude d'abord, arrondie à une dizaine de mètres ; dix minutes en secondes.
        assert options["params"]["point"] == "4.3872,45.4399"
        assert options["params"]["costValue"] == 600 and options["params"]["profile"] == "car"
        assert set(options) == {"params", "timeout"}        # rien du navigateur ne part

    def test_a_pied_et_sur_une_autre_duree(self, api_client, itineraires):
        corps = api_client.get(reverse("zone_atteignable"),
                               {"lat": "45.44", "lon": "4.39", "minutes": "20", "mode": "pied"}).json()

        assert (corps["minutes"], corps["mode"]) == (20, "pied")
        assert itineraires.call_args.kwargs["params"]["profile"] == "pedestrian"
        assert itineraires.call_args.kwargs["params"]["costValue"] == 1200

    @pytest.mark.parametrize("demande, attendu", [("0", 1), ("999", 60), ("abc", 10)])
    def test_la_duree_est_bornee(self, api_client, itineraires, demande, attendu):
        corps = api_client.get(reverse("zone_atteignable"), {"lat": "45.44", "lon": "4.39", "minutes": demande}).json()

        assert corps["minutes"] == attendu

    def test_un_mode_inconnu_revient_a_la_voiture(self, api_client, itineraires):
        corps = api_client.get(reverse("zone_atteignable"), {"lat": "45.44", "lon": "4.39", "mode": "helicoptere"}).json()

        assert corps["mode"] == "voiture"

    def test_sans_point_aucun_appel_ne_part(self, api_client, itineraires):
        assert api_client.get(reverse("zone_atteignable"), {"lat": "45.44"}).status_code == 400
        itineraires.assert_not_called()

    def test_un_service_en_panne_ou_sans_contour_est_dit_clairement(self, api_client, itineraires):
        itineraires.return_value.json.return_value = {"geometry": None}
        sans_contour = api_client.get(reverse("zone_atteignable"), {"lat": "45.44", "lon": "4.39"})
        itineraires.side_effect = requests.ConnectionError("coupé")
        en_panne = api_client.get(reverse("zone_atteignable"), {"lat": "45.44", "lon": "4.39"})

        assert sans_contour.status_code == 503 and en_panne.status_code == 503
        assert "n'a pas abouti" in en_panne.json()["detail"]


# ── La commande planifiée ───────────────────────────────────────────────────────────────────

class TestCommandeDeReleve:

    @pytest.fixture(autouse=True)
    def _verrou_propre(self, tmp_path, monkeypatch):
        """Le verrou de la commande est un fichier du dossier temporaire : partagé, il ferait se
        retirer la commande d'un processus d'essai pendant qu'un autre le tient (suite en
        parallèle, 19/11/2026)."""
        import tempfile
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    def _lancer(self, resultats, *arguments):
        from django.core.management import call_command

        ordre = []

        def relever(code, forcer=False):
            ordre.append(code)
            return resultats.get(code, "réussi")

        def annoncer():
            ordre.append("ANNONCE")
            return ["Mairie : Vigilance ORANGE"]

        def annoncer_un_foyer():
            ordre.append("ANNONCE_FOYER")
            return []

        sortie = io.StringIO()
        with mock.patch("core.sources_ouvertes.relever_source", side_effect=relever), \
                mock.patch("core.meteo_france.diffuser_alertes", side_effect=annoncer), \
                mock.patch("core.foyers_actifs.diffuser_alertes", side_effect=annoncer_un_foyer):
            call_command("relever_sources_ouvertes", *arguments, stdout=sortie)
        return ordre, sortie.getvalue()

    def test_l_annonce_part_aussitot_la_vigilance_relevee_sans_attendre_les_sources_lentes(self):
        ordre, sortie = self._lancer({})

        # Métropole, puis outre-mer : chacune annoncée dès son propre relevé.
        assert ordre[:4] == ["VIGILANCE_METEO", "ANNONCE", "VIGILANCE_OUTRE_MER", "ANNONCE"]
        assert set(ordre[4:]) == (set(sources_ouvertes.SOURCES) - sources_ouvertes.SOURCES_EN_CONTINU
                                  - {"VIGILANCE_METEO", "VIGILANCE_OUTRE_MER"}) | {"ANNONCE_FOYER"}
        # Les foyers aussi sont annoncés dès leur relevé, sans attendre la suite.
        assert ordre[ordre.index("FOYERS_ACTIFS") + 1] == "ANNONCE_FOYER"
        assert "2 annonce(s) de vigilance" in sortie

    def test_rien_n_est_annonce_sur_une_vigilance_non_rafraichie(self):
        for resultat in ("échec", "ignoré"):
            ordre, sortie = self._lancer({"VIGILANCE_METEO": resultat, "VIGILANCE_OUTRE_MER": resultat})

            assert "ANNONCE" not in ordre and "0 annonce(s)" in sortie

    def test_l_outre_mer_est_annonce_meme_si_la_metropole_n_a_pas_ete_relevee(self):
        ordre, sortie = self._lancer({"VIGILANCE_METEO": "échec"})

        assert ordre[:3] == ["VIGILANCE_METEO", "VIGILANCE_OUTRE_MER", "ANNONCE"]
        assert ordre.count("ANNONCE") == 1 and "1 annonce(s) de vigilance" in sortie

    def test_un_second_releve_lance_en_meme_temps_se_retire(self):
        """Constaté en service le 15/11/2026 : deux relevés forcés tournaient ensemble."""
        import fcntl
        import os
        import tempfile

        with open(os.path.join(tempfile.gettempdir(), "relever-sources-ouvertes.verrou"), "w") as tenu:
            fcntl.flock(tenu, fcntl.LOCK_EX)

            ordre, sortie = self._lancer({}, "--forcer")

        assert ordre == [] and "déjà en cours" in sortie
        # Verrou relâché : le relevé suivant passe.
        assert self._lancer({})[0][0] == "VIGILANCE_METEO"

    def test_une_source_seule_peut_etre_relevee(self):
        ordre, _sortie = self._lancer({}, "--source", "CARBURANTS")

        assert ordre == ["CARBURANTS"]
