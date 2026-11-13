"""Suivi des crédits Brevo : jauge, alerte, et SMS par la même clé.

Demande de Sylvain du 12/11/2026 : « la même clé api permettrait l'option sms aussi. Et
regarde si l'API permet de suivre les consos de crédits brevo. Si oui il faut les remonter
dans le dashboard de l'institution avec un warning quand on s'approche de la limite. Il faut
aussi définir l'administrateur de brevo pour notifier ce dernier. »

Contrat vérifié contre l'API réelle le 12/11/2026, sans rien envoyer : `GET /v3/account` rend
`plan: [{credits, creditsType, endDate}]` — le RESTANT, pas le quota — et
`POST /v3/transactionalSMS/send` accepte la clé `xkeysib-` des emails.

Ce que ces tests tiennent :

1. **Une seule clé.** Brevo sert emails et SMS avec la même : la redemander ferait saisir deux
   fois le même secret, et une régénération n'en mettrait qu'un à jour.
2. **L'alerte ne part JAMAIS par Brevo.** Prévenir que le compte est à sec en utilisant ce
   compte, c'est scier la branche.
3. **Une alerte par niveau**, pas une par envoi — sinon l'administrateur apprend à les ignorer.
4. **Inconnu n'est pas zéro** : un plan sans plafond lisible ne déclenche pas d'alerte.
"""
import pytest
from django.core import mail

from core.credits_brevo import NIVEAU_BAS, NIVEAU_EPUISE, NIVEAU_OK, etat, niveau, relever
from core.envoi_brevo import expediteur_sms, numero_international
from core.models import (
    ConfigurationEnvoiInstitution, ContactInstitution, Institution, InstitutionType,
    Notification, UserRole,
)


@pytest.fixture
def config(db):
    itype, _ = InstitutionType.objects.get_or_create(
        code="aasc", defaults={"libelle": "Association"})
    institution = Institution.objects.create(
        nom="Association Crédits", nom_affichage="Réserve Crédits", type=itype)
    return ConfigurationEnvoiInstitution.objects.create(
        institution=institution, brevo_actif=True, brevo_cle_api="xkeysib-essai",
        brevo_expediteur_email="hello@essai.invalide", brevo_admin_email="tresorier@essai.invalide",
        environment="PROD")


class TestUneSeuleCle:
    def test_le_champ_sms_vide_reprend_la_cle_des_emails(self, config):
        """Brevo sert les deux avec la même clé : la saisir deux fois, c'est oublier d'en
        mettre une à jour le jour où elle est régénérée."""
        config.fournisseur_sms = "BREVO"
        config.save()

        assert config.cle_sms_effective == "xkeysib-essai"
        assert config.sms_configure is True

    def test_un_autre_fournisseur_exige_sa_propre_cle(self, config):
        config.fournisseur_sms = "MOBIMEL"
        config.save()

        assert config.cle_sms_effective == ""
        assert config.sms_configure is False

    def test_brevo_figure_parmi_les_fournisseurs_implementes(self):
        from core.envoi_sms import fournisseurs_disponibles

        brevo = next(f for f in fournisseurs_disponibles() if f["code"] == "BREVO")
        assert brevo["implemente"] is True


class TestLeFormatExigeParBrevo:
    def test_le_nom_d_expediteur_est_ramene_a_onze_caracteres(self):
        """« Réserve Résilience - Casques Jaunes » ne passe pas : Brevo refuserait l'envoi au
        moment où l'on en a besoin."""
        assert expediteur_sms("Réserve Résilience - Casques Jaunes") == "ReserveResi"
        assert len(expediteur_sms("Réserve Résilience - Casques Jaunes")) <= 11

    def test_un_nom_vide_ne_produit_pas_un_expediteur_vide(self):
        assert expediteur_sms("") == "Alerte"

    @pytest.mark.parametrize("saisi,attendu", [
        ("06 12 34 56 78", "33612345678"),
        ("+33 6 12 34 56 78", "33612345678"),
        ("0033612345678", "33612345678"),
        ("06.12.34.56.78", "33612345678"),
    ])
    def test_les_numeros_sont_mis_au_format_international(self, saisi, attendu):
        assert numero_international(saisi) == attendu

    @pytest.mark.parametrize("saisi,attendu", [
        # La Réunion et Mayotte partagent le +262 ; la règle naïve « 0 -> 33 » envoyait ces
        # SMS vers un numéro métropolitain qui n'était pas le bon. Le projet a un satellite à
        # La Réunion : l'erreur serait passée inaperçue jusqu'au jour où il aurait fallu
        # joindre quelqu'un.
        ("0692 12 34 56", "262692123456"),   # Réunion, mobile
        ("0262 12 34 56", "262262123456"),   # Réunion, fixe
        ("0639 12 34 56", "262639123456"),   # Mayotte, mobile
        ("0690 12 34 56", "590690123456"),   # Guadeloupe, mobile
        ("0696 12 34 56", "596696123456"),   # Martinique, mobile
        ("0694 12 34 56", "594694123456"),   # Guyane, mobile
    ])
    def test_l_outre_mer_n_est_pas_en_33(self, saisi, attendu):
        assert numero_international(saisi) == attendu

    def test_un_numero_deja_international_n_est_pas_retouche(self):
        assert numero_international("+262 692 12 34 56") == "262692123456"

    @pytest.mark.parametrize("saisi", ["", "pas un numéro", "12"])
    def test_un_numero_inexploitable_rend_none(self, saisi):
        """Envoyer à un numéro deviné serait pire que ne pas envoyer."""
        assert numero_international(saisi) is None


class TestLesSeuils:
    def test_inconnu_n_est_pas_zero(self):
        """Un plan sans plafond lisible ne doit pas déclencher une alerte pour rien."""
        assert niveau(None, 1000) == NIVEAU_OK

    def test_au_dessus_du_seuil_rien_ne_se_passe(self):
        assert niveau(5000, 1000) == NIVEAU_OK

    def test_sous_le_seuil_on_previent(self):
        assert niveau(800, 1000) == NIVEAU_BAS

    def test_a_zero_c_est_epuise(self):
        assert niveau(0, 1000) == NIVEAU_EPUISE


class TestLeReleveEtLAlerte:
    def test_le_releve_enregistre_les_credits_et_la_reference(self, config, monkeypatch):
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 19995, "sms": 0, "fin_periode": "2026-12-12"})

        assert relever(config, force=True) is True

        config.refresh_from_db()
        assert config.brevo_credits_email == 19995
        # La référence sert la jauge : l'API ne rend que le restant, jamais le quota souscrit.
        assert config.brevo_credits_email_reference == 19995
        assert etat(config)["email"]["part"] == 100

    def test_la_jauge_suit_la_consommation(self, config, monkeypatch):
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 1000, "sms": 0, "fin_periode": "2026-12-12"})
        relever(config, force=True)
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 250, "sms": 0, "fin_periode": "2026-12-12"})
        relever(config, force=True)

        config.refresh_from_db()
        assert config.brevo_credits_email_reference == 1000
        assert etat(config)["email"]["part"] == 25

    def test_sous_le_seuil_l_administrateur_brevo_est_prevenu(self, config, monkeypatch):
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 400, "sms": 0, "fin_periode": "2026-12-12"})

        relever(config, force=True)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["tresorier@essai.invalide"]
        assert "bientôt épuisés" in mail.outbox[0].subject
        assert "Réserve Crédits" in mail.outbox[0].subject

    def test_l_alerte_ne_part_pas_par_brevo(self, config, monkeypatch):
        """Prévenir que le compte Brevo est à sec en utilisant le compte Brevo, c'est scier
        la branche : le message qui compte le plus serait le premier à ne pas partir."""
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 0, "sms": 0, "fin_periode": "2026-12-12"})
        appels = []
        monkeypatch.setattr("core.envoi_brevo.envoyer_email_brevo",
                            lambda **kw: appels.append(kw))

        relever(config, force=True)

        assert appels == []
        assert len(mail.outbox) == 1

    def test_une_seule_alerte_par_niveau(self, config, monkeypatch):
        """Sous le seuil, chaque envoi retrouverait le compte bas : sans mémoire, on
        enverrait cent messages et l'alerte deviendrait du bruit."""
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 400, "sms": 0, "fin_periode": "2026-12-12"})
        relever(config, force=True)
        relever(config, force=True)
        relever(config, force=True)

        assert len(mail.outbox) == 1

    def test_l_epuisement_reprevient_apres_une_alerte_basse(self, config, monkeypatch):
        """Passer de « bientôt » à « plus rien » est une nouvelle information."""
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 400, "sms": 0, "fin_periode": "2026-12-12"})
        relever(config, force=True)
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 0, "sms": 0, "fin_periode": "2026-12-12"})
        relever(config, force=True)

        assert len(mail.outbox) == 2
        assert "épuisés" in mail.outbox[1].subject

    def test_le_rechargement_remet_le_compteur_d_alerte_a_zero(self, config, monkeypatch):
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 400, "sms": 0, "fin_periode": "2026-12-12"})
        relever(config, force=True)
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 20000, "sms": 0, "fin_periode": "2027-01-12"})
        relever(config, force=True)

        config.refresh_from_db()
        assert config.brevo_alerte_niveau == ""

    def test_le_bureau_voit_l_alerte_dans_l_application(self, config, monkeypatch,
                                                        create_user):
        """L'administrateur du compte n'est pas toujours celui qui envoie, et c'est celui qui
        envoie qui tombera sur le problème."""
        membre = create_user(username="bureau-credits@test.fr",
                             email="bureau-credits@test.fr", type=UserRole.ORGANIZED_RESCUE)
        ContactInstitution.objects.create(institution=config.institution, utilisateur=membre,
                                          membre_bureau=True, actif=True)
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 100, "sms": 0, "fin_periode": "2026-12-12"})

        relever(config, force=True)

        notification = Notification.objects.get(utilisateur=membre)
        libelles = {d["libelle"]: d["valeur"] for d in notification.details}
        assert libelles["Emails restants"] == "100"
        assert libelles["Institution"] == "Réserve Crédits"

    def test_les_sms_ne_comptent_que_si_l_institution_s_en_sert(self, config, monkeypatch):
        """Un compte sans crédits SMS qui n'envoie pas de SMS n'a rien d'alarmant."""
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: {"email": 20000, "sms": 0, "fin_periode": "2026-12-12"})

        relever(config, force=True)

        assert mail.outbox == []

    def test_le_releve_est_espace(self, config, monkeypatch):
        """Un appel à Brevo par email envoyé doublerait le trafic vers leur API pour une
        information qui change lentement."""
        appels = []
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo",
                            lambda cle: appels.append(cle) or {"email": 9000, "sms": 0,
                                                               "fin_periode": "2026-12-12"})
        relever(config, force=True)
        assert relever(config) is False
        assert len(appels) == 1

    def test_un_echec_de_releve_ne_casse_rien(self, config, monkeypatch):
        from core.envoi_brevo import EchecBrevo

        def tombe(cle):
            raise EchecBrevo("Brevo injoignable")
        monkeypatch.setattr("core.envoi_brevo.lire_credits_brevo", tombe)

        assert relever(config, force=True) is False
        config.refresh_from_db()
        assert config.brevo_credits_releves_le is None
