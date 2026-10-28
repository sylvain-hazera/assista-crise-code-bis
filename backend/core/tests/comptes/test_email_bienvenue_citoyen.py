"""Email de bienvenue d'un compte citoyen, et mention de la candidature à une réserve.

Ajouté le 28/10/2026. Jusque-là, `envoyer_email_creation_compte` finissait par un `return
False` pour les bénévoles et citoyens : le compte était actif immédiatement, donc aucun lien
d'activation n'était nécessaire — mais la personne n'avait **aucune trace écrite** de son
inscription. En crise, c'est l'email qu'on retrouve dans sa boîte trois jours plus tard quand
on ne se souvient plus de l'adresse utilisée.

Le second point est un ordre d'exécution, pas un texte : `RegisterView.perform_create` posait
`reserve_institution` **après** l'envoi, si bien qu'un email censé mentionner la candidature
partait muet sur le seul point qui intéressait la personne.
"""
import pytest
from django.core import mail

from core.crypto_fields import blind_index
from core.models import Institution, InstitutionType, InstitutionWebDomaine, User
from rest_framework.test import APIClient

URL = "/api/register/"
DOMAINE = "reserve-test.exemple.fr"


def _payload(email, **extra):
    return {
        "username": email, "email": email, "password": "MotDePasse!2026",
        "first_name": "Jon", "last_name": "Jin", "type": "UTIL_SIMPLE", **extra,
    }


@pytest.fixture
def reserve(db, settings):
    """Une institution en marque blanche dont la réserve est ouverte aux candidatures.

    Le branding est résolu depuis le Host HTTP (jamais d'un paramètre client, qui serait
    falsifiable) : il faut donc que Django accepte ce host dans le test."""
    settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + [DOMAINE]
    itype = InstitutionType.objects.create(code="AASC_BIENVENUE", libelle="Association agréée")
    institution = Institution.objects.create(
        nom="Reserve Resilience Test", type=itype, reserve_active=True,
        nom_affichage="Réserve Résilience",
    )
    InstitutionWebDomaine.objects.create(institution=institution, hostname=DOMAINE)
    return institution


@pytest.mark.django_db
class TestEmailDeBienvenue:
    def test_un_citoyen_recoit_un_accuse(self):
        reponse = APIClient().post(URL, _payload("citoyen-bienvenue@exemple.fr"), format="json")

        assert reponse.status_code == 201, reponse.data
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["citoyen-bienvenue@exemple.fr"]

    def test_l_accuse_dit_que_le_compte_est_deja_utilisable(self):
        """Ne pas laisser croire qu'il faut attendre une validation : c'est précisément ce
        qu'un email de création laisse supposer par défaut."""
        APIClient().post(URL, _payload("deja-utilisable@exemple.fr"), format="json")

        corps = mail.outbox[0].body
        assert "immédiatement utilisable" in corps
        assert "aucune validation" in corps.lower()

    def test_l_accuse_porte_un_lien_de_reconnexion(self):
        APIClient().post(URL, _payload("lien-retour@exemple.fr"), format="json")

        assert "connexion-magique" in mail.outbox[0].body

    def test_l_email_ne_bloque_jamais_la_creation(self, monkeypatch):
        """Le compte est créé et utilisable ; l'email n'est qu'un accusé. Un relais SMTP en
        panne ne doit pas empêcher quelqu'un de s'inscrire pendant une crise."""
        from core import views

        def exploser(*args, **kwargs):
            raise RuntimeError("relais SMTP injoignable")

        monkeypatch.setattr(views, "send_branded_mail", exploser)

        reponse = APIClient().post(URL, _payload("smtp-casse@exemple.fr"), format="json")

        assert reponse.status_code == 201
        assert User.objects.filter(
            email_bidx=blind_index("smtp-casse@exemple.fr")).exists()


@pytest.mark.django_db
class TestMentionDeLaCandidature:
    def test_la_candidature_est_annoncee_dans_le_meme_email(self, reserve):
        """Du point de vue de la personne, s'inscrire et demander à rejoindre sont un seul
        geste : deux messages pour un geste donnent l'impression d'une erreur."""
        reponse = APIClient().post(
            URL, _payload("candidat@exemple.fr", souhaite_rejoindre_reserve=True),
            format="json", HTTP_HOST=DOMAINE)

        assert reponse.status_code == 201, reponse.data
        bienvenue = [m for m in mail.outbox if m.to == ["candidat@exemple.fr"]]
        assert len(bienvenue) == 1
        corps = bienvenue[0].body
        assert "Réserve Résilience" in corps
        assert "transmise à son responsable" in corps

    def test_l_ordre_compte_la_candidature_est_posee_avant_l_envoi(self, reserve):
        """Le défaut corrigé : `reserve_institution` était posée APRÈS l'envoi, donc l'email
        partait muet sur le seul point qui intéressait la personne."""
        APIClient().post(
            URL, _payload("ordre@exemple.fr", souhaite_rejoindre_reserve=True),
            format="json", HTTP_HOST=DOMAINE)

        user = User.objects.get(email_bidx=blind_index("ordre@exemple.fr"))
        assert user.reserve_institution_id == reserve.id
        corps = [m for m in mail.outbox if m.to == ["ordre@exemple.fr"]][0].body
        assert "rejoindre la réserve" in corps

    def test_sans_candidature_aucune_mention(self, reserve):
        APIClient().post(
            URL, _payload("sans-candidature@exemple.fr"), format="json", HTTP_HOST=DOMAINE)

        corps = mail.outbox[0].body
        assert "rejoindre la réserve" not in corps

    def test_une_case_cochee_sur_un_site_sans_reserve_ne_ment_pas(self):
        """Cocher la case sur le site généraliste ne rattache à rien (aucune institution n'est
        résolue) : l'email ne doit surtout pas annoncer une candidature inexistante."""
        APIClient().post(
            URL, _payload("faux-candidat@exemple.fr", souhaite_rejoindre_reserve=True),
            format="json")

        user = User.objects.get(email_bidx=blind_index("faux-candidat@exemple.fr"))
        assert user.reserve_institution_id is None
        corps = [m for m in mail.outbox if m.to == ["faux-candidat@exemple.fr"]][0].body
        assert "rejoindre la réserve" not in corps
