"""Métriques du parc de satellites (core/metrics.py:SatelliteCollector), 18/11/2026.

Le cas qui les a fait écrire : un satellite resté une journée sur une mise à jour échouée, son
serveur local en boucle de redémarrage, sans qu'aucune alerte ne le dise."""
import datetime

import pytest
from django.utils import timezone

from core.metrics import COLLECTEURS, SatelliteCollector
from core.models import (
    ActionSatellite, Institution, InstitutionType, MiseAJourSatellite, Satellite,
    StatutEnrolementSatellite, StatutMiseAJour,
)


def valeurs(nom):
    famille = {f.name: f for f in SatelliteCollector().collect()}[nom]
    return {tuple(sorted(e.labels.items())): e.value for e in famille.samples}


@pytest.fixture
def parc(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MET_SAT", defaults={"libelle": "Test"})
    institution = Institution.objects.create(nom="Mairie des métriques", type=itype)

    def creer(nom, silence_minutes=None, statut=StatutEnrolementSatellite.APPROUVE):
        return Satellite.objects.create(
            nom=nom, institution=institution, statut_enrolement=statut,
            dernier_contact=None if silence_minutes is None
            else timezone.now() - datetime.timedelta(minutes=silence_minutes))
    return creer


def _ordre(satellite, statut, action=ActionSatellite.MISE_A_JOUR, il_y_a_minutes=0, fini=True):
    ordre = MiseAJourSatellite.objects.create(satellite=satellite, action=action, statut=statut)
    quand = timezone.now() - datetime.timedelta(minutes=il_y_a_minutes)
    MiseAJourSatellite.objects.filter(pk=ordre.pk).update(
        date_demande=quand, date_fin=quand if fini else None)
    return ordre


@pytest.mark.django_db
class TestParc:

    def test_le_collecteur_est_bien_servi_en_production(self):
        """Un collecteur absent de COLLECTEURS disparaît en silence de /metrics sous gunicorn."""
        assert SatelliteCollector in COLLECTEURS

    def test_les_satellites_sont_comptes_par_etat(self, parc, settings):
        settings.SATELLITE_SEUIL_INACTIF_MINUTES, settings.SATELLITE_SEUIL_PERDU_MINUTES = 15, 120
        parc("actif", 1); parc("inactif", 30); parc("perdu", 600); parc("jamais vu")
        parc("pas encore approuvé", 600, statut=StatutEnrolementSatellite.EN_ATTENTE)
        etats = {dict(k)["etat"]: v for k, v in valeurs("assista_satellites").items()}
        assert etats == {"ACTIF": 1, "INACTIF": 1, "PERDU": 1, "JAMAIS_VU": 1}

    def test_aucune_etiquette_ne_nomme_un_satellite(self, parc):
        satellite = parc("Poste de commandement de Saint-Exemple", 1)
        _ordre(satellite, StatutMiseAJour.ECHOUEE)
        for famille in SatelliteCollector().collect():
            for echantillon in famille.samples:
                assert set(echantillon.labels) <= {"etat", "environment"}
                assert "Saint-Exemple" not in str(echantillon.labels) and str(satellite.id) not in str(echantillon.labels)


@pytest.mark.django_db
class TestResteSurUnEchec:

    def _echecs(self):
        return sum(valeurs("assista_satellites_mise_a_jour_echouee").values())

    def test_une_mise_a_jour_echouee_compte(self, parc):
        _ordre(parc("a", 1), StatutMiseAJour.ECHOUEE)
        assert self._echecs() == 1

    def test_une_reussite_ensuite_l_efface(self, parc):
        satellite = parc("a", 1)
        _ordre(satellite, StatutMiseAJour.ECHOUEE, il_y_a_minutes=60)
        _ordre(satellite, StatutMiseAJour.REUSSIE, il_y_a_minutes=5)
        assert self._echecs() == 0

    def test_un_diagnostic_reussi_ne_l_efface_pas(self, parc):
        """Regarder n'est pas réparer : le satellite reste à signaler."""
        satellite = parc("a", 1)
        _ordre(satellite, StatutMiseAJour.ECHOUEE, il_y_a_minutes=60)
        _ordre(satellite, StatutMiseAJour.REUSSIE, action=ActionSatellite.DIAGNOSTIC, il_y_a_minutes=5)
        assert self._echecs() == 1

    def test_sans_echec_la_serie_existe_et_vaut_zero(self, parc):
        """Sinon l'alerte ne pourrait pas se refermer."""
        parc("a", 1)
        assert list(valeurs("assista_satellites_mise_a_jour_echouee").values()) == [0]


@pytest.mark.django_db
class TestOrdreEnAttente:

    def test_l_age_du_plus_vieil_ordre_ouvert(self, parc):
        satellite = parc("a", 1)
        _ordre(satellite, StatutMiseAJour.DEMANDEE, action=ActionSatellite.DIAGNOSTIC, il_y_a_minutes=90, fini=False)
        _ordre(parc("b", 1), StatutMiseAJour.EN_COURS, il_y_a_minutes=10, fini=False)
        (age,) = valeurs("assista_satellites_ordre_en_attente_secondes").values()
        assert age == pytest.approx(90 * 60, abs=60)

    def test_un_ordre_fini_ne_compte_plus(self, parc):
        _ordre(parc("a", 1), StatutMiseAJour.REUSSIE, il_y_a_minutes=600)
        assert list(valeurs("assista_satellites_ordre_en_attente_secondes").values()) == [0]
