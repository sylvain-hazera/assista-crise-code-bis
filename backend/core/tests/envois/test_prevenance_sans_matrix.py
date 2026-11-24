"""Depuis l'arrêt de Matrix (24/11/2026), toutes les prévenances passent par l'application et le
site : séisme, vigilance, SOS radio, panne d'un compagnon, alerte de terrain, annuaire PCS,
appel aux dons, erreurs serveur. Plus rien ne part vers Matrix."""
import logging
from unittest import mock

import pytest
from django.contrib.gis.geos import Point
from django.test import RequestFactory, override_settings

from core import matrix, notifications_application
from core.models import (
    Commune, ConfigurationAlerteSismique, ContactInstitution, Institution, InstitutionType, Notification,
    NotificationApplication, SeismeDiffuse,
)

CACHE_LOCAL = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "prevenance"}}


@pytest.fixture(autouse=True)
def matrix_interdit(monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("Matrix est arrêté : plus rien ne doit y partir")
    monkeypatch.setattr(matrix, "envoyer_dm", interdit)


@pytest.fixture
def mairie(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    Commune.objects.update_or_create(code="42218", defaults={"nom": "Saint-Étienne", "centre_latitude": 45.43,
                                                              "centre_longitude": 4.39, "departement_code": "42"})
    return Institution.objects.create(nom="Mairie de la prévenance", type=itype, commune_code="42218")


@pytest.fixture
def admin_avec_telephone(create_user):
    admin = create_user(username="admin-prev@test.fr", email="admin-prev@test.fr", type="ADMIN")
    notifications_application.enregistrer_appareil(admin, "installation-admin")
    return admin


def _recu(utilisateur):
    return (list(Notification.objects.filter(utilisateur=utilisateur)),
            list(NotificationApplication.objects.filter(utilisateur=utilisateur)))


@pytest.mark.django_db
class TestPrevenir:
    def test_le_site_et_l_application(self, admin_avec_telephone):
        assert notifications_application.prevenir(admin_avec_telephone, "Titre", "Corps", urgent=True, lien="/pilotage/alertes")
        (site,), (appli,) = _recu(admin_avec_telephone)
        assert site.titre == "Titre" and site.lien == "/pilotage/alertes"
        assert appli.urgent and appli.corps == "Corps"

    def test_sans_telephone_la_cloche_du_site_suffit(self, create_user):
        sans = create_user(username="sans-tel@test.fr", email="sans-tel@test.fr", type="AUT_LOCALE")
        assert notifications_application.prevenir(sans, "Titre", "Corps") is False
        site, appli = _recu(sans)
        assert len(site) == 1 and appli == []

    def test_ne_leve_jamais_et_refuse_un_lien_exterieur(self, admin_avec_telephone):
        with mock.patch.object(notifications_application, "notifier", side_effect=RuntimeError("panne")):
            assert notifications_application.prevenir(admin_avec_telephone, "T", lien="//ailleurs.example") is False
        (site,), _ = _recu(admin_avec_telephone)
        assert site.lien == ""


@pytest.mark.django_db
class TestSeisme:
    EVENEMENT = {"event_id": "fr-1", "date": None, "latitude": 45.5, "longitude": 4.4, "magnitude": 4.8,
                 "lieu": "Event of magnitude 4.8, near Saint-Etienne (France hexagonale)", "sources": {"FR"}}

    def test_l_alerte_de_la_commune_previent_les_administrateurs_par_l_application(self, mairie, admin_avec_telephone):
        from django.core.management import call_command
        from django.utils import timezone

        ConfigurationAlerteSismique.objects.create(institution=mairie, actif=True, rayon_km=100, magnitude_min=3.5)
        evenement = {**self.EVENEMENT, "date": timezone.now()}
        commande = "core.management.commands.verifier_alertes_sismiques"
        with mock.patch(f"{commande}._recuperer_evenements_france", return_value=[evenement]), \
             mock.patch(f"{commande}._recuperer_evenements_emsc", return_value=[]):
            call_command("verifier_alertes_sismiques")

        assert SeismeDiffuse.objects.filter(institution=mairie, event_id="fr-1").exists()
        _, (appli,) = _recu(admin_avec_telephone)
        assert appli.titre == "Séisme M4.8 près de Saint-Etienne (France hexagonale)" and appli.urgent

    def test_une_reponse_vide_d_emsc_n_est_pas_une_panne(self):
        from core.management.commands import verifier_alertes_sismiques as commande

        vide = mock.Mock(status_code=204, content=b"")
        with mock.patch.object(commande.requests, "get", return_value=vide):
            assert commande._recuperer_evenements_emsc(3.0, "2026-11-24T00:00:00") == []


@pytest.mark.django_db
class TestAlertesRadioEtPcs:
    def test_un_sos_radio_previent_les_administrateurs_en_urgence(self, admin_avec_telephone):
        from core.views import _signaler_sos_mesh

        requete = RequestFactory().post("/")
        requete.user = admin_avec_telephone
        _signaler_sos_mesh(requete, "MESHCORE", "SOS blessé au col", "SOS", expediteur_identifiant="abc")

        _, (appli,) = _recu(admin_avec_telephone)
        assert appli.urgent and "SOS" in appli.titre and "blessé au col" in appli.corps

    def test_l_annuaire_pcs_en_mode_application(self, mairie, create_user):
        from core.alertes_pcs import _REGISTRE_ENVOI
        from core.models import Crisis, InterlocuteurAlertePCS, ModeAlertePCS, NotificationAlertePCS

        elu = create_user(username="elu-pcs@test.fr", email="elu-pcs@test.fr", type="AUT_LOCALE")
        notifications_application.enregistrer_appareil(elu, "installation-elu")
        crise = Crisis.objects.create(name="Crue du Furan", location=Point(4.39, 45.43, srid=4326))
        interlocuteur = InterlocuteurAlertePCS.objects.create(nom="Élu d'astreinte", utilisateur=elu,
                                                              mode_alerte=ModeAlertePCS.MATRIX)
        notification = NotificationAlertePCS.objects.create(
            crise=crise, interlocuteur=interlocuteur, nom_snapshot="Élu d'astreinte", categorie_snapshot="PREFECTURE",
            canal_tente=ModeAlertePCS.MATRIX, token_confirmation="jeton-de-test-pcs")

        _REGISTRE_ENVOI[ModeAlertePCS.MATRIX](interlocuteur, crise, notification, "Le PCS est activé.", None)

        _, (appli,) = _recu(elu)
        assert appli.titre == "[PCS] Crue du Furan" and "confirmation-pcs/" in appli.corps
        assert ModeAlertePCS.MATRIX.label == "Notification dans l'application"


@pytest.mark.django_db
def test_un_appel_aux_dons_previent_l_equipe_de_l_institution(mairie, create_user):
    from core.notifications_dons import prevenir

    principal = create_user(username="principal-dons@test.fr", email="principal-dons@test.fr", type="AUT_LOCALE")
    ContactInstitution.objects.create(institution=mairie, utilisateur=principal, actif=True, contact_principal=True)

    bilan = prevenir(de=mairie, vers=mairie, titre="Appel aux dons", corps="Couvertures demandées.")

    assert bilan["equipe"] == 1 and "matrix" not in bilan
    assert Notification.objects.filter(utilisateur=principal).count() == 1


@override_settings(CACHES=CACHE_LOCAL)
def test_les_erreurs_serveur_previennent_les_administrateurs_sans_rafale():
    from core import logging_handlers, tasks

    gestionnaire = logging_handlers.MatrixAlertHandler()     # ancien nom : la configuration le cite
    journal = logging.getLogger("core.essai_prevenance")
    journal.addHandler(gestionnaire)
    try:
        with mock.patch.object(tasks.alerter_administrateurs_erreur_task, "apply_async") as envoi:
            for _ in range(3):
                journal.error("La même panne")
            assert envoi.call_count == 1                      # une fois par heure
            for n in range(10):
                journal.error("Panne numéro %s", n)
            assert envoi.call_count == logging_handlers.PLAFOND_PAR_FENETRE
            journal.warning("Simple avertissement")
            logging.getLogger("django.db.backends").addHandler(gestionnaire)
            assert envoi.call_count == logging_handlers.PLAFOND_PAR_FENETRE
    finally:
        journal.removeHandler(gestionnaire)
        logging.getLogger("django.db.backends").removeHandler(gestionnaire)
