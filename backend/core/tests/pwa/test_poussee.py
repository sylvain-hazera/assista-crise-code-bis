"""Notifications poussées vers l'application web : abonnement par appareil, envoi (lot 4)."""
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.db import connection
from rest_framework.test import APIClient

from core import notifications_application as moteur
from core import web_push
from core.models import AppareilMobile, NotificationApplication


def _abonnement(hote="web.push.apple.com"):
    cle = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": f"https://{hote}/QGuQyavXutnMKpersonnel", "keys": {"p256dh": web_push.b64url(cle), "auth": "BTBZMqHH6r4Tts7J_aSIgg"}}


def _client(u):
    c = APIClient()
    c.force_authenticate(user=u)
    return c


@pytest.mark.django_db
def test_l_application_web_donne_son_abonnement_chiffre_en_base(create_user):
    u = create_user(username="pwa1@essai.test", email="pwa1@essai.test", type="UTIL_SIMPLE")
    abonnement = _abonnement()
    r = _client(u).post("/api/mon-appareil/", {"installation": "a" * 32, "plateforme": "WEB", "version": "pwa",
                                               "abonnement_push": abonnement}, format="json")
    assert r.status_code == 200, r.content
    appareil = AppareilMobile.objects.get(installation="a" * 32)
    assert appareil.plateforme == "WEB" and json.loads(appareil.abonnement_push) == abonnement
    with connection.cursor() as curseur:
        curseur.execute("SELECT abonnement_push FROM core_appareilmobile WHERE installation = %s", ["a" * 32])
        (brut,) = curseur.fetchone()
    assert "web.push.apple.com" not in brut and "QGuQ" not in brut          # rien en clair

    # Sans abonnement dans la requête : on garde celui qu'on a ; vide : on l'oublie.
    _client(u).post("/api/mon-appareil/", {"installation": "a" * 32, "plateforme": "WEB"}, format="json")
    assert AppareilMobile.objects.get(installation="a" * 32).abonnement_push
    _client(u).post("/api/mon-appareil/", {"installation": "a" * 32, "plateforme": "WEB", "abonnement_push": ""}, format="json")
    assert AppareilMobile.objects.get(installation="a" * 32).abonnement_push == ""


@pytest.mark.django_db
def test_un_abonnement_vers_un_service_inconnu_est_refuse(create_user):
    u = create_user(username="pwa2@essai.test", email="pwa2@essai.test", type="UTIL_SIMPLE")
    r = _client(u).post("/api/mon-appareil/", {"installation": "b" * 32, "plateforme": "WEB",
                                               "abonnement_push": _abonnement("exemple.fr")}, format="json")
    assert r.status_code == 400
    assert not AppareilMobile.objects.filter(installation="b" * 32).exists()


@pytest.mark.django_db
def test_pousser_n_envoie_que_le_titre_aux_applications_web_abonnees(create_user):
    u = create_user(username="pwa3@essai.test", email="pwa3@essai.test", type="UTIL_SIMPLE")
    moteur.enregistrer_appareil(u, "c" * 32, "WEB", "pwa", abonnement_push=_abonnement())
    moteur.enregistrer_appareil(u, "d" * 32, "WEB", "pwa", abonnement_push=_abonnement("fcm.googleapis.com"))
    moteur.enregistrer_appareil(u, "e" * 32, "ANDROID", "0.10.0")              # Android : il vient chercher
    moteur.enregistrer_appareil(u, "f" * 32, "WEB", "pwa")                     # pas abonné
    notification = moteur.notifier(u, "MOBILISATION", "Renfort demandé à 14 h", "Rendez-vous au gymnase, M. Dupont")
    assert notification is not None

    envois = []

    def envoyer(abonnement, message, urgent=False):
        envois.append((abonnement["endpoint"], message))
        if "fcm" in abonnement["endpoint"]:
            raise web_push.AbonnementExpire(410)
        return 201

    assert moteur.pousser(notification.id, envoyer=envoyer) == 1
    assert len(envois) == 2
    message = envois[0][1]
    assert message["titre"] == "Renfort demandé à 14 h" and message["lien"] == "/terrain/alertes"
    assert "Dupont" not in json.dumps(message)                                # jamais le corps
    # L'abonnement expiré est oublié ; l'autre reste.
    assert AppareilMobile.objects.get(installation="d" * 32).abonnement_push == ""
    assert AppareilMobile.objects.get(installation="c" * 32).abonnement_push


@pytest.mark.django_db
def test_sans_application_web_rien_n_est_programme(create_user, django_capture_on_commit_callbacks):
    u = create_user(username="pwa4@essai.test", email="pwa4@essai.test", type="UTIL_SIMPLE")
    moteur.enregistrer_appareil(u, "g" * 32, "ANDROID", "0.10.0")
    with django_capture_on_commit_callbacks() as rappels:
        moteur.notifier(u, "MOBILISATION", "Essai")
    assert rappels == []
    moteur.enregistrer_appareil(u, "h" * 32, "WEB", "pwa", abonnement_push=_abonnement())
    with django_capture_on_commit_callbacks() as rappels:
        moteur.notifier(u, "MOBILISATION", "Essai")
    assert len(rappels) == 1
    assert NotificationApplication.objects.filter(utilisateur=u).count() == 2


@pytest.mark.django_db
def test_la_cle_publique_n_est_donnee_que_si_le_secret_est_pose(client, tmp_path, monkeypatch):
    monkeypatch.setenv("VAPID_PRIVE_FILE", str(tmp_path / "absent.pem"))
    assert client.get("/api/pwa/cle-push/").status_code == 404
    cle = ec.generate_private_key(ec.SECP256R1())
    (tmp_path / "v.pem").write_bytes(cle.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption()))
    monkeypatch.setenv("VAPID_PRIVE_FILE", str(tmp_path / "v.pem"))
    r = client.get("/api/pwa/cle-push/")
    assert r.status_code == 200 and r.json()["cle"] == web_push.cle_publique_b64url(cle)


@pytest.mark.django_db
def test_les_notifications_de_l_administration_sont_poussees_au_poste_de_pilotage(create_user, django_capture_on_commit_callbacks):
    from core.models import Notification
    u = create_user(username="dos@essai.test", email="dos@essai.test", type="UTIL_SIMPLE")
    with django_capture_on_commit_callbacks() as rappels:
        Notification.objects.create(utilisateur=u, titre="Sans iPad", message="…")
    assert rappels == []                                                         # aucun appareil web
    moteur.enregistrer_appareil(u, "i" * 32, "WEB", "pwa", abonnement_push=_abonnement())
    with django_capture_on_commit_callbacks() as rappels:
        reelle = Notification.objects.create(utilisateur=u, titre="Nouvelle demande d'hébergement",
                                             message="Famille de 4 personnes", lien="/admin/demandes?id=12")
    assert len(rappels) == 1
    formation = Notification.objects.create(utilisateur=u, titre="Exercice", message="…", lien="//ailleurs.fr/x",
                                            environment="DEMO")
    envois = []
    envoyer = lambda abonnement, message, urgent=False: envois.append(message) or 201
    assert moteur.pousser_notification_site(reelle.id, envoyer=envoyer) == 1
    assert moteur.pousser_notification_site(formation.id, envoyer=envoyer) == 1
    assert envois[0] == {"titre": "Nouvelle demande d'hébergement", "lien": "/admin/demandes?id=12", "id": str(reelle.id)}
    assert "Famille" not in json.dumps(envois[0])                               # jamais le message
    assert envois[1]["titre"] == "Formation — Exercice" and envois[1]["lien"] == "/pilotage/alertes"
