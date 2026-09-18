"""Synchronisation local -> central (cadrage "Chantier B", décisions du 2026-09-18) :
core/sync_outbox.py (peuplement de la file, actif seulement si
settings.INSTANCE_SATELLITE_LOCALE) et SatelliteViewSet.synchroniser (application côté
central, upsert pour les modèles append-only, détection de conflit pour les modèles mutables
Dossier/Mission via `modifie_le`)."""
import pytest
from django.apps import apps as django_apps
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from core.management.commands.synchroniser_entrant import appliquer_objet_mutable
from core.models import (
    ContactInstitution, ConflitSynchronisation, Crisis, Dossier, DossierCommentaire,
    EtatEvenementSynchronisation, EvenementSynchronisation, Institution, InstitutionType,
    Notification, Satellite, StatutEnrolementSatellite,
)


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code="MAIRIE", defaults={"libelle": "Mairie"})
    return Institution.objects.create(nom="Mairie Sync", type=itype, commune_code="38185")


@pytest.fixture
def satellite(create_user, institution):
    compte = create_user(
        username="satellite-sync@service.fr", email="satellite-sync@service.fr",
        type="UTIL_SIMPLE", institution=institution,
    )
    return Satellite.objects.create(
        institution=institution, nom="Sat Sync", profil="FULL",
        statut_enrolement=StatutEnrolementSatellite.APPROUVE, compte_service=compte,
    )


@pytest.fixture
def satellite_client(satellite):
    client = APIClient()
    client.force_authenticate(user=satellite.compte_service)
    return client


@pytest.fixture
def crisis(db):
    return Crisis.objects.create(
        name="Crise Sync", type="INONDATION", location=Point(5.72, 45.18, srid=4326),
        zone_communes=["38185"],
    )


@pytest.fixture
def dossier(crisis):
    return Dossier.objects.create(
        numero="DOS-SYNC-1", crise=crisis, titre="Test sync", description="...",
    )


class TestOutboxDesactiveParDefaut:
    def test_creation_dossier_ne_peuple_pas_la_file_sans_le_reglage(self, crisis):
        Dossier.objects.create(numero="DOS-OFF-1", crise=crisis, titre="x", description="x")
        assert EvenementSynchronisation.objects.count() == 0


class TestOutboxPeuplement:
    @pytest.fixture(autouse=True)
    def _instance_satellite_locale(self, settings):
        settings.INSTANCE_SATELLITE_LOCALE = True

    def test_creation_dossier_cree_un_evenement_creation_sans_version_de_base(self, crisis):
        d = Dossier.objects.create(numero="DOS-ON-1", crise=crisis, titre="x", description="x")
        evenements = EvenementSynchronisation.objects.filter(modele="Dossier", objet_id=d.id)
        assert evenements.count() == 1
        ev = evenements.first()
        assert ev.action == "CREATION"
        assert ev.version_de_base is None
        assert ev.payload["titre"] == "x"

    def test_modification_dossier_capture_la_version_de_base(self, dossier):
        ancienne_version = dossier.modifie_le
        EvenementSynchronisation.objects.filter(modele="Dossier", objet_id=dossier.id).delete()

        dossier.statut = Dossier.Statut.EN_COURS
        dossier.save()

        ev = EvenementSynchronisation.objects.get(modele="Dossier", objet_id=dossier.id)
        assert ev.action == "MODIFICATION"
        assert ev.version_de_base == ancienne_version
        assert ev.payload["statut"] == "EN_COURS"

    def test_modifications_successives_se_coalescent_en_un_seul_evenement(self, dossier):
        ancienne_version = dossier.modifie_le
        EvenementSynchronisation.objects.filter(modele="Dossier", objet_id=dossier.id).delete()

        dossier.statut = Dossier.Statut.EN_COURS
        dossier.save()
        dossier.refresh_from_db()
        dossier.statut = Dossier.Statut.RESOLU
        dossier.save()

        evenements = EvenementSynchronisation.objects.filter(modele="Dossier", objet_id=dossier.id)
        assert evenements.count() == 1
        ev = evenements.first()
        # La version de base reste celle d'AVANT la première écriture hors-ligne, pas celle
        # (déjà obsolète pour le central) posée par l'écriture intermédiaire.
        assert ev.version_de_base == ancienne_version
        assert ev.payload["statut"] == "RESOLU"

    def test_creation_commentaire_cree_un_evenement_append_only(self, dossier):
        commentaire = DossierCommentaire.objects.create(dossier=dossier, commentaire="hors ligne")
        ev = EvenementSynchronisation.objects.get(modele="DossierCommentaire", objet_id=commentaire.id)
        assert ev.action == "CREATION"
        assert ev.version_de_base is None
        assert ev.payload["commentaire"] == "hors ligne"

    def test_modification_dun_append_only_ne_cree_pas_de_second_evenement(self, dossier):
        commentaire = DossierCommentaire.objects.create(dossier=dossier, commentaire="v1")
        assert EvenementSynchronisation.objects.filter(modele="DossierCommentaire").count() == 1
        commentaire.commentaire = "v2"
        commentaire.save()
        assert EvenementSynchronisation.objects.filter(modele="DossierCommentaire").count() == 1


@pytest.mark.django_db
class TestEndpointSynchroniser:
    def _url(self, satellite):
        return reverse('satellite-synchroniser', args=[satellite.id])

    def test_permission_refusee_pour_un_autre_compte(self, satellite, create_user, dossier):
        autre = create_user(username="intrus@x.fr", email="intrus@x.fr", type="UTIL_SIMPLE")
        client = APIClient()
        client.force_authenticate(user=autre)
        response = client.post(self._url(satellite), {"evenements": []}, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_evenement_append_only_cree_puis_idempotent(self, satellite_client, satellite, dossier):
        commentaire_id = "11111111-1111-1111-1111-111111111111"
        evenement = {
            "id": "evt-1", "modele": "DossierCommentaire", "objet_id": commentaire_id,
            "action": "CREATION",
            "payload": {"dossier_id": str(dossier.id), "auteur_id": None, "commentaire": "vu depuis le terrain"},
            "version_de_base": None,
        }
        response = satellite_client.post(self._url(satellite), {"evenements": [evenement]}, format='json')
        assert response.status_code == status.HTTP_200_OK
        assert response.data["resultats"][0]["resultat"] == "applique"
        assert DossierCommentaire.objects.filter(id=commentaire_id, commentaire="vu depuis le terrain").exists()

        # Repoussé une seconde fois (le satellite n'a pas encore reçu l'accusé de réception) :
        # jamais recréé/écrasé, jamais une erreur non plus.
        response2 = satellite_client.post(self._url(satellite), {"evenements": [evenement]}, format='json')
        assert response2.data["resultats"][0]["resultat"] == "deja_applique"

    def test_evenement_mutable_applique_sans_conflit(self, satellite_client, satellite, dossier):
        version_de_base = dossier.modifie_le.isoformat()
        evenement = {
            "id": "evt-2", "modele": "Dossier", "objet_id": str(dossier.id), "action": "MODIFICATION",
            "payload": {"statut": "EN_COURS"}, "version_de_base": version_de_base,
        }
        response = satellite_client.post(self._url(satellite), {"evenements": [evenement]}, format='json')
        assert response.data["resultats"][0]["resultat"] == "applique"
        dossier.refresh_from_db()
        assert dossier.statut == "EN_COURS"

    def test_evenement_mutable_en_conflit_si_version_centrale_a_change(self, satellite_client, satellite, dossier, institution, create_user):
        contact_user = create_user(username="contact-sync@x.fr", email="contact-sync@x.fr", type="UTIL_SIMPLE")
        ContactInstitution.objects.create(institution=institution, utilisateur=contact_user, actif=True, fonction="Maire")

        version_de_base_perimee = dossier.modifie_le.isoformat()
        # Le central modifie le dossier après que le satellite a capturé sa version de base.
        dossier.statut = "AFFECTE"
        dossier.save()

        evenement = {
            "id": "evt-3", "modele": "Dossier", "objet_id": str(dossier.id), "action": "MODIFICATION",
            "payload": {"statut": "RESOLU"}, "version_de_base": version_de_base_perimee,
        }
        response = satellite_client.post(self._url(satellite), {"evenements": [evenement]}, format='json')
        assert response.data["resultats"][0]["resultat"] == "conflit"

        dossier.refresh_from_db()
        assert dossier.statut == "AFFECTE"  # pas écrasé silencieusement
        assert ConflitSynchronisation.objects.filter(satellite=satellite, objet_id=dossier.id).exists()
        assert Notification.objects.filter(utilisateur=contact_user).exists()

    def test_evenement_mutable_cree_directement_si_absent_du_central(self, satellite_client, satellite, crisis):
        nouveau_id = "22222222-2222-2222-2222-222222222222"
        evenement = {
            "id": "evt-4", "modele": "Dossier", "objet_id": nouveau_id, "action": "CREATION",
            "payload": {
                "numero": "DOS-CREE-LOCAL", "crise_id": str(crisis.id), "titre": "Créé hors ligne",
                "description": "...", "statut": "NOUVEAU",
            },
            "version_de_base": None,
        }
        response = satellite_client.post(self._url(satellite), {"evenements": [evenement]}, format='json')
        assert response.data["resultats"][0]["resultat"] == "applique"
        assert Dossier.objects.filter(id=nouveau_id, numero="DOS-CREE-LOCAL").exists()

    def test_evenement_incomplet_renvoie_une_erreur_sans_bloquer_les_suivants(self, satellite_client, satellite, dossier):
        version_de_base = dossier.modifie_le.isoformat()
        evenements = [
            {"id": "evt-bad", "modele": "Dossier"},  # objet_id/payload manquants
            {
                "id": "evt-ok", "modele": "Dossier", "objet_id": str(dossier.id), "action": "MODIFICATION",
                "payload": {"statut": "EN_COURS"}, "version_de_base": version_de_base,
            },
        ]
        response = satellite_client.post(self._url(satellite), {"evenements": evenements}, format='json')
        resultats = {r["id"]: r["resultat"] for r in response.data["resultats"]}
        assert resultats["evt-bad"] == "erreur"
        assert resultats["evt-ok"] == "applique"


@pytest.mark.django_db
class TestResolutionConflit:
    def _url(self, satellite):
        return reverse('satellite-synchroniser', args=[satellite.id])

    def _provoquer_conflit(self, satellite_client, satellite, dossier):
        version_de_base_perimee = dossier.modifie_le.isoformat()
        dossier.statut = "AFFECTE"
        dossier.save()
        evenement = {
            "id": "evt-conflit", "modele": "Dossier", "objet_id": str(dossier.id), "action": "MODIFICATION",
            "payload": {"statut": "RESOLU"}, "version_de_base": version_de_base_perimee,
        }
        satellite_client.post(self._url(satellite), {"evenements": [evenement]}, format='json')
        return ConflitSynchronisation.objects.get(satellite=satellite, objet_id=dossier.id)

    def _acteur_institutionnel(self, create_user, institution, email):
        acteur = create_user(username=email, email=email, type="AUT_LOCALE", institution=institution)
        ContactInstitution.objects.create(institution=institution, utilisateur=acteur, actif=True, fonction="Maire")
        return acteur

    def test_garde_local_applique_le_payload_local(self, satellite_client, satellite, dossier, create_user, institution):
        conflit = self._provoquer_conflit(satellite_client, satellite, dossier)
        acteur = self._acteur_institutionnel(create_user, institution, "regulateur-sync@x.fr")
        client = APIClient()
        client.force_authenticate(user=acteur)

        response = client.post(
            reverse('conflitsynchronisation-resoudre', args=[conflit.id]), {"choix": "GARDE_LOCAL"}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.statut == "RESOLU"
        conflit.refresh_from_db()
        assert conflit.statut == "RESOLU_GARDE_LOCAL"
        assert conflit.resolu_par == acteur

    def test_garde_central_ne_touche_pas_lobjet(self, satellite_client, satellite, dossier, create_user, institution):
        conflit = self._provoquer_conflit(satellite_client, satellite, dossier)
        acteur = self._acteur_institutionnel(create_user, institution, "regulateur-sync-2@x.fr")
        client = APIClient()
        client.force_authenticate(user=acteur)

        response = client.post(
            reverse('conflitsynchronisation-resoudre', args=[conflit.id]), {"choix": "GARDE_CENTRAL"}, format='json',
        )
        assert response.status_code == status.HTTP_200_OK
        dossier.refresh_from_db()
        assert dossier.statut == "AFFECTE"

    def test_resolution_deja_faite_est_refusee(self, satellite_client, satellite, dossier, create_user, institution):
        conflit = self._provoquer_conflit(satellite_client, satellite, dossier)
        acteur = self._acteur_institutionnel(create_user, institution, "regulateur-sync-3@x.fr")
        client = APIClient()
        client.force_authenticate(user=acteur)
        url = reverse('conflitsynchronisation-resoudre', args=[conflit.id])
        client.post(url, {"choix": "GARDE_CENTRAL"}, format='json')
        response = client.post(url, {"choix": "GARDE_LOCAL"}, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
class TestCommandeSynchroniserSortant:
    @pytest.fixture(autouse=True)
    def _config_satellite(self, settings):
        settings.SATELLITE_CENTRAL_URL = "https://central.example"
        settings.SATELLITE_ID = "sat-1"
        settings.SATELLITE_EMAIL = "sat@example.com"
        settings.SATELLITE_PASSWORD = "secret"

    def _evenement_en_attente(self, dossier):
        return EvenementSynchronisation.objects.create(
            modele="Dossier", objet_id=dossier.id, action="MODIFICATION",
            payload={"statut": "EN_COURS"}, version_de_base=None,
        )

    def test_sans_configuration_ne_fait_aucun_appel_reseau(self, settings, monkeypatch, dossier):
        settings.SATELLITE_CENTRAL_URL = ""
        appele = []
        monkeypatch.setattr("core.management.commands.synchroniser_sortant.requests.post", lambda *a, **k: appele.append(1))
        call_command("synchroniser_sortant")
        assert appele == []

    def test_sans_evenement_en_attente_ne_fait_aucun_appel_reseau(self, monkeypatch):
        appele = []
        monkeypatch.setattr("core.management.commands.synchroniser_sortant.requests.post", lambda *a, **k: appele.append(1))
        call_command("synchroniser_sortant")
        assert appele == []

    def test_evenements_appliques_conflit_et_erreur_sont_marques_correctement(self, monkeypatch, dossier):
        ev_ok = self._evenement_en_attente(dossier)
        ev_conflit = self._evenement_en_attente(dossier)
        ev_erreur = self._evenement_en_attente(dossier)

        class FakeReponse:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self._data

        appels = []

        def fake_post(url, **kwargs):
            appels.append(url)
            if url.endswith("/api/token/"):
                return FakeReponse({"access": "jeton-test"})
            return FakeReponse({"resultats": [
                {"id": str(ev_ok.id), "resultat": "applique"},
                {"id": str(ev_conflit.id), "resultat": "conflit", "detail": "version centrale différente"},
                {"id": str(ev_erreur.id), "resultat": "erreur", "detail": "boom"},
            ]})

        monkeypatch.setattr("core.management.commands.synchroniser_sortant.requests.post", fake_post)
        call_command("synchroniser_sortant")

        ev_ok.refresh_from_db()
        ev_conflit.refresh_from_db()
        ev_erreur.refresh_from_db()
        assert ev_ok.etat == "SYNCHRONISE"
        assert ev_ok.synchronise_le is not None
        assert ev_conflit.etat == "CONFLIT"
        assert ev_erreur.etat == "EN_ATTENTE" and ev_erreur.erreur == "boom"

    def test_echec_reseau_laisse_tout_en_attente(self, monkeypatch, dossier):
        import requests
        ev = self._evenement_en_attente(dossier)

        def fake_post(url, **kwargs):
            raise requests.ConnectionError("central injoignable")

        monkeypatch.setattr("core.management.commands.synchroniser_sortant.requests.post", fake_post)
        call_command("synchroniser_sortant")

        ev.refresh_from_db()
        assert ev.etat == "EN_ATTENTE"


@pytest.mark.django_db
class TestDonneesIncluDossierEtMission:
    def test_dossiers_et_missions_presents_avec_modifie_le(self, satellite_client, satellite, dossier):
        response = satellite_client.get(reverse('satellite-donnees', args=[satellite.id]))
        assert response.status_code == status.HTTP_200_OK
        dossiers = {d["id"]: d for d in response.data["dossiers"]}
        assert str(dossier.id) in dossiers
        item = dossiers[str(dossier.id)]
        assert item["modifie_le"] == dossier.modifie_le.isoformat()
        assert item["environment"] == dossier.environment
        assert "missions" in response.data


@pytest.mark.django_db
class TestAppliquerObjetMutable:
    def test_met_a_jour_avec_le_modifie_le_central_pas_maintenant(self, dossier):
        modifie_le_central = "2020-01-01T00:00:00+00:00"
        resultat = appliquer_objet_mutable(django_apps.get_model, "Dossier", {
            "id": str(dossier.id), "modifie_le": modifie_le_central, "statut": "EN_COURS",
        })
        assert resultat == "applique"
        dossier.refresh_from_db()
        assert dossier.statut == "EN_COURS"
        assert dossier.modifie_le.isoformat() == modifie_le_central

    def test_ne_declenche_pas_loutbox_meme_avec_le_reglage_actif(self, dossier, settings):
        settings.INSTANCE_SATELLITE_LOCALE = True
        EvenementSynchronisation.objects.all().delete()
        appliquer_objet_mutable(django_apps.get_model, "Dossier", {
            "id": str(dossier.id), "modifie_le": "2020-01-01T00:00:00+00:00", "statut": "RESOLU",
        })
        assert EvenementSynchronisation.objects.count() == 0

    def test_ignore_si_ecriture_locale_en_attente(self, dossier):
        EvenementSynchronisation.objects.create(
            modele="Dossier", objet_id=dossier.id, action="MODIFICATION",
            payload={"statut": "AFFECTE"}, etat=EtatEvenementSynchronisation.EN_ATTENTE,
        )
        resultat = appliquer_objet_mutable(django_apps.get_model, "Dossier", {
            "id": str(dossier.id), "modifie_le": "2020-01-01T00:00:00+00:00", "statut": "RESOLU",
        })
        assert resultat == "ignore_local_en_attente"
        dossier.refresh_from_db()
        assert dossier.statut != "RESOLU"

    def test_efface_un_conflit_deja_tranche_localement(self, dossier):
        EvenementSynchronisation.objects.create(
            modele="Dossier", objet_id=dossier.id, action="MODIFICATION",
            payload={"statut": "AFFECTE"}, etat=EtatEvenementSynchronisation.CONFLIT,
        )
        appliquer_objet_mutable(django_apps.get_model, "Dossier", {
            "id": str(dossier.id), "modifie_le": "2020-01-01T00:00:00+00:00", "statut": "RESOLU",
        })
        assert not EvenementSynchronisation.objects.filter(
            modele="Dossier", objet_id=dossier.id, etat=EtatEvenementSynchronisation.CONFLIT,
        ).exists()

    def test_cree_un_dossier_absent_localement(self, crisis):
        nouveau_id = "33333333-3333-3333-3333-333333333333"
        resultat = appliquer_objet_mutable(django_apps.get_model, "Dossier", {
            "id": nouveau_id, "modifie_le": "2020-01-01T00:00:00+00:00",
            "numero": "DOS-ENTRANT-1", "crise_id": str(crisis.id), "titre": "Reçu du central",
            "description": "...", "statut": "NOUVEAU", "environment": "PROD",
        })
        assert resultat == "applique"
        cree = Dossier.objects.get(id=nouveau_id)
        assert cree.numero == "DOS-ENTRANT-1"
        assert cree.modifie_le.isoformat() == "2020-01-01T00:00:00+00:00"


@pytest.mark.django_db
class TestCommandeSynchroniserEntrant:
    @pytest.fixture(autouse=True)
    def _config_satellite(self, settings):
        settings.SATELLITE_CENTRAL_URL = "https://central.example"
        settings.SATELLITE_ID = "sat-1"
        settings.SATELLITE_EMAIL = "sat@example.com"
        settings.SATELLITE_PASSWORD = "secret"

    def test_sans_configuration_ne_fait_aucun_appel_reseau(self, settings, monkeypatch):
        settings.SATELLITE_CENTRAL_URL = ""
        appele = []
        monkeypatch.setattr("core.management.commands.synchroniser_entrant.requests.post", lambda *a, **k: appele.append(1))
        call_command("synchroniser_entrant")
        assert appele == []

    def test_applique_les_dossiers_renvoyes_par_donnees(self, monkeypatch, dossier):
        class FakeReponse:
            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                pass

            def json(self):
                return self._data

        def fake_post(url, **kwargs):
            return FakeReponse({"access": "jeton-test"})

        def fake_get(url, **kwargs):
            return FakeReponse({
                "dossiers": [{"id": str(dossier.id), "modifie_le": "2020-01-01T00:00:00+00:00", "statut": "RESOLU"}],
                "missions": [],
            })

        monkeypatch.setattr("core.management.commands.synchroniser_entrant.requests.post", fake_post)
        monkeypatch.setattr("core.management.commands.synchroniser_entrant.requests.get", fake_get)
        call_command("synchroniser_entrant")

        dossier.refresh_from_db()
        assert dossier.statut == "RESOLU"
