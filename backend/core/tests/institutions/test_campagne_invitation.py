"""Campagne « Rejoindre votre collectivité » préparée dans la fenêtre de rédaction, et choix du
connecteur d'envoi : Brevo, SMTP de l'institution, SMTP de la plateforme (22/11/2026)."""
from unittest import mock

import pytest
from django.core import mail
from django.urls import reverse

from core.models import (
    BrouillonEnvoi, CampagneInvitation, ConfigurationEnvoiInstitution, ConnecteurSMTP, ContactInstitution,
    InvitationCollectivite, ReferentCollectivite, User,
)
from core.tests.institutions.test_invitation_collectivite import _client, monde  # noqa: F401


def _preparer(monde, *institutions):
    return _client(monde["cadre"]).post(reverse("delegationgestion-preparer-invitation", args=[monde["d"].id]),
                                        {"institutions": [str(i.id) for i in institutions]}, format="json")


def _campagne(monde, connecteur="plateforme", **extra):
    corps = extra.pop("corps", "[SALUTATION]\nRejoindre [COLLECTIVITE] : [LIEN]")
    donnees = {"institutions": [str(monde["mairie"].id), str(monde["muette"].id)], "sujet": "Votre espace [COLLECTIVITE]",
               "corps": corps, "connecteur": connecteur, **extra}
    from core import tasks
    with mock.patch("core.tasks.PAUSE_CAMPAGNE_S", 0), \
         mock.patch("core.tasks.envoyer_campagne_invitation_task.delay",
                    side_effect=lambda *a: tasks.envoyer_campagne_invitation_task.run(*a)), \
         mock.patch("django.db.transaction.on_commit", lambda f: f()):
        return _client(monde["cadre"]).post(reverse("delegationgestion-campagne-invitation", args=[monde["d"].id]),
                                            donnees, format="json")


@pytest.mark.django_db
def test_la_fenetre_dit_ou_ira_chaque_courriel_et_propose_les_connecteurs(monde):
    ReferentCollectivite.objects.create(institution=monde["mairie"], nom="Julie Martin", email="j.martin@commune.exemple",
                                        environment=monde["mairie"].environment)
    r = _preparer(monde, monde["mairie"], monde["muette"], monde["ailleurs"])
    assert r.status_code == 200, r.data
    assert r.data["resume"] == {"vers_referent": 1, "vers_officielle": 0, "sans_adresse": ["Mairie - Sans adresse"],
                                "deja_membres": 0}
    assert "[LIEN]" in r.data["corps"] and "[COLLECTIVITE]" in r.data["sujet"]
    assert [c["cle"] for c in r.data["connecteurs"]] == ["plateforme"]


@pytest.mark.django_db
def test_les_connecteurs_de_l_association_avec_leur_adresse(monde):
    aasc = monde["d"].aasc
    ConfigurationEnvoiInstitution.objects.create(institution=aasc, brevo_actif=True, brevo_cle_api="cle-essai",
                                                 brevo_expediteur_email="contact@reserve.exemple", environment="PROD")
    smtp = ConnecteurSMTP.objects.create(institution=aasc, nom="Messagerie", hote="smtp.exemple", port=587,
                                         expediteur_email="envoi@reserve.exemple", environment="PROD")
    connecteurs = _preparer(monde, monde["mairie"]).data["connecteurs"]
    assert [(c["cle"], c["adresse"]) for c in connecteurs][:2] == [
        (f"brevo:{aasc.id}", "contact@reserve.exemple"), (f"smtp:{smtp.id}", "envoi@reserve.exemple")]
    assert connecteurs[-1]["cle"] == "plateforme"


@pytest.mark.django_db
def test_apercu_rendu_lien_masque_rien_n_est_cree(monde):
    r = _campagne(monde, apercu=str(monde["mairie"].id))
    assert r.status_code == 200, r.data
    assert r.data["sujet"] == "Votre espace Mairie - Rive-de-Gier"
    assert r.data["corps"].startswith("Bonjour,") and "[lien personnel d'invitation]" in r.data["corps"]
    assert "rejoindre-collectivite" not in r.data["corps"]
    assert not InvitationCollectivite.objects.exists() and not CampagneInvitation.objects.exists()


@pytest.mark.django_db
def test_un_texte_sans_lien_est_refuse(monde):
    r = _campagne(monde, corps="Bonjour, venez nous rejoindre.")
    assert r.status_code == 400 and "[LIEN]" in r.data["error"]


@pytest.mark.django_db
def test_campagne_par_le_smtp_de_la_plateforme_sans_brouillon(monde):
    r = _campagne(monde)
    assert r.status_code == 202, r.data
    c = CampagneInvitation.objects.get()
    assert (c.statut, c.prevues, c.envoyees, c.sans_adresse, c.echecs) == ("TERMINEE", 2, 1, 1, 0)
    (courriel,) = mail.outbox
    assert courriel.to == ["mairie@ville.exemple"] and courriel.subject == "Votre espace Mairie - Rive-de-Gier"
    assert "/rejoindre-collectivite/" in courriel.body
    assert not BrouillonEnvoi.objects.exists()


@pytest.mark.django_db
def test_campagne_par_le_smtp_de_l_association(monde):
    smtp = ConnecteurSMTP.objects.create(institution=monde["d"].aasc, nom="Messagerie", hote="smtp.exemple", port=587,
                                         expediteur_email="envoi@reserve.exemple", expediteur_nom="Réserve",
                                         mot_de_passe="pas-un-vrai-mot-de-passe", environment="PROD")
    r = _campagne(monde, connecteur=f"smtp:{smtp.id}")
    assert r.status_code == 202, r.data
    (courriel,) = mail.outbox
    assert courriel.from_email == "Réserve <envoi@reserve.exemple>"
    smtp.refresh_from_db()
    assert smtp.dernier_succes is not None


@pytest.mark.django_db
def test_campagne_par_brevo_et_un_echec_n_arrete_pas_les_autres(monde):
    from core.envoi_brevo import EchecBrevo
    from core.models import Institution, InstitutionType
    aasc = monde["d"].aasc
    ConfigurationEnvoiInstitution.objects.create(institution=aasc, brevo_actif=True, brevo_cle_api="cle-essai",
                                                 brevo_expediteur_email="contact@reserve.exemple", environment="PROD")
    autre = Institution.objects.create(nom="Mairie - Autre", type=InstitutionType.objects.get(code="mairie"),
                                       commune_code="42207", email="autre@ville.exemple")
    appels = []

    def faux_brevo(**kw):
        appels.append(kw["destinataires"])
        if kw["destinataires"] == ["mairie@ville.exemple"]:
            raise EchecBrevo("adresse refusée")
        return "id-1"
    with mock.patch("core.envoi_brevo.envoyer_email_brevo", side_effect=faux_brevo):
        r = _campagne(monde, connecteur=f"brevo:{aasc.id}",
                      institutions=[str(monde["mairie"].id), str(autre.id)])
    assert r.status_code == 202, r.data
    c = CampagneInvitation.objects.get()
    assert (c.envoyees, c.echecs) == (1, 1) and c.erreurs[0]["collectivite"] == "Mairie - Rive-de-Gier"
    assert appels == [["mairie@ville.exemple"], ["autre@ville.exemple"]] and mail.outbox == []


@pytest.mark.django_db
def test_connecteur_d_une_autre_institution_refuse(monde):
    from core.models import Institution, InstitutionType
    etrangere = Institution.objects.create(nom="Autre asso", type=InstitutionType.objects.get_or_create(code="aasc")[0])
    smtp = ConnecteurSMTP.objects.create(institution=etrangere, nom="X", hote="h", expediteur_email="x@y.exemple",
                                         environment="PROD")
    assert _campagne(monde, connecteur=f"smtp:{smtp.id}").status_code == 400


@pytest.mark.django_db
def test_connecteurs_smtp_secrets_jamais_relus_et_reserves_au_bureau(monde):
    aasc = monde["d"].aasc
    bureau = User.objects.create_user(username="bureau-smtp@test.fr", email="bureau-smtp@test.fr", password="x", type="SECOURS")
    ContactInstitution.objects.create(institution=aasc, utilisateur=bureau, actif=True, membre_bureau=True)
    c = _client(bureau)
    r = c.post(reverse("connecteursmtp-list"), {"institution": str(aasc.id), "nom": "Messagerie", "hote": "smtp.exemple",
                                                "port": 587, "chiffrement": "STARTTLS", "identifiant": "compte",
                                                "mot_de_passe": "pas-un-vrai-mot-de-passe",
                                                "expediteur_email": "envoi@reserve.exemple"}, format="json")
    assert r.status_code == 201, r.data
    assert "mot_de_passe" not in r.data and r.data["mot_de_passe_renseigne"] is True
    ident = r.data["id"]
    # Laissé vide : inchangé.
    c.patch(reverse("connecteursmtp-detail", args=[ident]), {"mot_de_passe": "", "nom": "Messagerie 2"}, format="json")
    assert ConnecteurSMTP.objects.get(pk=ident).mot_de_passe == "pas-un-vrai-mot-de-passe"
    from django.db import connection
    with connection.cursor() as curseur:
        curseur.execute("select mot_de_passe from core_connecteursmtp where id = %s", [ident])
        assert "pas-un-vrai" not in curseur.fetchone()[0]
    # Un simple cadre (pas du bureau) ne voit ni ne crée rien.
    assert _client(monde["cadre"]).get(reverse("connecteursmtp-list")).data == []
    r = _client(monde["cadre"]).post(reverse("connecteursmtp-list"), {"institution": str(aasc.id), "nom": "Y", "hote": "h",
                                                                      "expediteur_email": "y@z.exemple"}, format="json")
    assert r.status_code == 403
    # Essai : à son propre compte.
    r = c.post(reverse("connecteursmtp-essai", args=[ident]))
    assert r.status_code == 200 and mail.outbox[-1].to == ["bureau-smtp@test.fr"]


@pytest.mark.django_db
def test_un_inconnu_ne_prepare_ni_ne_lance(monde):
    inconnu = User.objects.create_user(username="inconnu-camp@test.fr", email="inconnu-camp@test.fr", password="x", type="SECOURS")
    r = _client(inconnu).post(reverse("delegationgestion-preparer-invitation", args=[monde["d"].id]),
                              {"institutions": [str(monde["mairie"].id)]}, format="json")
    assert r.status_code in (403, 404)
