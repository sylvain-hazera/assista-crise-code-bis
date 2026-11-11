"""Routage de l'envoi d'email : API de l'institution si elle en a une, SMTP sinon.

Demande du 11/11/2026 : pour Réserve Résilience, les mails partent de leur compte Brevo, au nom
de Réserve Résilience, et « Assista-Crise ne doit plus apparaître nulle part ».

Ce que ces tests verrouillent :

1. **Aucune clé API n'est lisible par l'API.** Ni en entier, ni en fragment. Le projet a déjà
   constaté cinq endpoints qui livraient des secrets mesh en clair à tout compte connecté, d'où
   `EstComptePont` ; on ne refait pas l'erreur sur une clé qui permet d'envoyer des emails au
   nom d'une association.
2. **La clé est chiffrée au repos**, vérifié en SQL brut et non par l'ORM — seule façon de
   constater ce qu'un `pg_dump` contiendrait.
3. **Le repli SMTP conserve le texte de l'institution** (arbitrage du 11/11/2026). Si l'API
   échoue, le message part quand même par le SMTP Assista-Crise, mais signé par l'institution.
   Seule l'adresse `From` retombe sur Assista-Crise.
4. **Le repli n'est jamais silencieux** : l'échec de l'API est journalisé en main courante avec
   le message du fournisseur, et horodaté sur la configuration. Une clé révoquée se verrait
   sinon seulement quand quelqu'un signale n'avoir rien reçu.
5. **Un envoi par l'API reste journalisé.** Il ne traverse pas `send_mail_logged` : sans
   journalisation explicite, confier une institution à Brevo ferait DISPARAÎTRE ses emails de la
   main courante — exactement le trou que `send_mail_logged` avait été écrit pour fermer.
"""
from unittest.mock import patch

import pytest
from django.core import mail
from django.db import connection
from rest_framework.test import APIClient

from core.branding import send_branded_mail
from core.envoi_brevo import EchecBrevo
from core.models import (
    AuditLog, ConfigurationEnvoiInstitution, ContactInstitution, Institution, InstitutionType,
)

CLE = "xkeysib-essai-0123456789abcdef"


@pytest.fixture
def institution(db):
    itype, _ = InstitutionType.objects.get_or_create(code='AASC_ENVOI',
                                                     defaults={'libelle': 'Association'})
    return Institution.objects.create(
        nom="Association Envoi Test", type=itype,
        nom_affichage="Reserve Essai", email_reply_to="contact@essai.invalide")


@pytest.fixture
def config(institution):
    return ConfigurationEnvoiInstitution.objects.create(
        institution=institution, brevo_actif=True, brevo_cle_api=CLE,
        brevo_expediteur_email="ne-pas-repondre@essai.invalide",
        brevo_expediteur_nom="Reserve Essai")


@pytest.fixture
def requete(rf, create_user):
    requete = rf.post('/api/x/')
    requete.user = create_user(username='envoi@test.fr', email='envoi@test.fr')
    return requete


@pytest.mark.django_db
class TestEnvoiParLApiDeLInstitution:

    def test_un_mail_part_par_brevo_au_nom_de_l_institution(self, requete, institution, config):
        with patch('core.envoi_institution.envoyer_email_brevo', return_value="<id@brevo>") as envoi:
            send_branded_mail(requete, institution, "Sujet", "Corps\n\n{signature}",
                              ["dest@essai.invalide"])

        assert envoi.call_count == 1
        appel = envoi.call_args.kwargs
        assert appel['cle_api'] == CLE
        assert appel['expediteur_email'] == "ne-pas-repondre@essai.invalide"
        assert appel['expediteur_nom'] == "Reserve Essai"
        assert appel['reply_to'] == "contact@essai.invalide"
        # La signature est celle de l'institution, et Assista-Crise n'apparaît nulle part.
        assert "Reserve Essai" in appel['message']
        assert "Assista-Crise" not in appel['message']
        # Et RIEN n'est parti par le SMTP.
        assert len(mail.outbox) == 0

    def test_l_envoi_par_l_api_est_journalise_en_main_courante(self, requete, institution,
                                                               config):
        """Il ne traverse pas send_mail_logged : sans cette trace, les emails d'une institution
        disparaîtraient de la main courante en passant à Brevo."""
        with patch('core.envoi_institution.envoyer_email_brevo', return_value="<id@brevo>"):
            send_branded_mail(requete, institution, "Sujet traçé", "Corps\n\n{signature}",
                              ["dest@essai.invalide"])

        ligne = AuditLog.objects.filter(action__code="ENVOI_EMAIL").first()
        assert ligne is not None
        assert ligne.succes is True
        assert "Association Envoi Test" in ligne.commentaire

    def test_sans_configuration_le_mail_part_par_le_smtp(self, requete, institution):
        send_branded_mail(requete, institution, "Sujet", "Corps\n\n{signature}",
                          ["dest@essai.invalide"])
        assert len(mail.outbox) == 1
        assert "Reserve Essai" in mail.outbox[0].body

    def test_une_configuration_inactive_n_est_pas_utilisee(self, requete, institution, config):
        """`brevo_actif` est un interrupteur : couper l'envoi sans effacer la clé doit marcher,
        sinon la seule façon de suspendre est de perdre la clé."""
        config.brevo_actif = False
        config.save(update_fields=['brevo_actif'])

        with patch('core.envoi_institution.envoyer_email_brevo') as envoi:
            send_branded_mail(requete, institution, "Sujet", "Corps\n\n{signature}",
                              ["dest@essai.invalide"])
        assert envoi.call_count == 0
        assert len(mail.outbox) == 1


@pytest.mark.django_db
class TestRepliApresEchec:

    def test_le_mail_part_quand_meme_avec_le_texte_de_l_institution(self, requete, institution,
                                                                    config):
        """L'arbitrage : on préfère une fuite de marque sur l'enveloppe à un message qui ne part
        pas. Le corps, lui, parle toujours au nom de l'institution."""
        with patch('core.envoi_institution.envoyer_email_brevo',
                   side_effect=EchecBrevo("api-key not found — clé révoquée")):
            send_branded_mail(requete, institution, "Sujet", "Corps\n\n{signature}",
                              ["dest@essai.invalide"])

        assert len(mail.outbox) == 1
        assert "Reserve Essai" in mail.outbox[0].body
        assert mail.outbox[0].reply_to == ["contact@essai.invalide"]

    def test_l_echec_est_journalise_avec_le_message_du_fournisseur(self, requete, institution,
                                                                   config):
        """Le message de Brevo est remonté INTACT : c'est lui qui dit si la clé est invalide, le
        quota dépassé ou le domaine non vérifié. Le remplacer par « erreur d'envoi » ferait
        perdre la seule information utile."""
        with patch('core.envoi_institution.envoyer_email_brevo',
                   side_effect=EchecBrevo("api-key not found — clé révoquée")):
            send_branded_mail(requete, institution, "Sujet", "Corps\n\n{signature}",
                              ["dest@essai.invalide"])

        echecs = [l for l in AuditLog.objects.filter(action__code="ENVOI_EMAIL")
                  if not l.succes]
        assert echecs, "le repli doit laisser une trace en échec, même si le mail est parti"
        assert "api-key not found" in echecs[0].commentaire

    def test_l_echec_est_horodate_sur_la_configuration(self, requete, institution, config):
        """C'est ce que lira l'écran de configuration : une clé révoquée ne se voit nulle part
        ailleurs tant que personne ne signale l'absence de message."""
        with patch('core.envoi_institution.envoyer_email_brevo',
                   side_effect=EchecBrevo("Insufficient credits")):
            send_branded_mail(requete, institution, "Sujet", "Corps\n\n{signature}",
                              ["dest@essai.invalide"])

        config.refresh_from_db()
        assert "Insufficient credits" in config.derniere_erreur_email

    def test_une_erreur_inattendue_ne_perd_pas_le_message(self, requete, institution, config):
        """Un bug chez nous ne doit pas empêcher le mail de partir : l'exception est attrapée et
        le SMTP prend le relais.

        On compte les mails ADRESSÉS AU DESTINATAIRE et non la taille de `outbox` : ce chemin
        passe par `logger.exception`, qui déclenche aussi l'alerte administrateur configurée
        dans LOGGING. Compter `outbox` ferait échouer le test pour la bonne nouvelle."""
        with patch('core.envoi_institution.envoyer_email_brevo',
                   side_effect=RuntimeError("bug chez nous")):
            send_branded_mail(requete, institution, "Sujet", "Corps\n\n{signature}",
                              ["dest@essai.invalide"])

        pour_destinataire = [m for m in mail.outbox if "dest@essai.invalide" in m.to]
        assert len(pour_destinataire) == 1
        assert "Reserve Essai" in pour_destinataire[0].body

    def test_une_cle_revoquee_n_alerte_PAS_les_administrateurs(self, requete, institution,
                                                               config):
        """Distinction qui compte : une clé révoquée est un problème de configuration CHEZ LE
        PARTENAIRE, pas un bug de la plateforme. L'alerter par le canal des erreurs techniques
        (logger.exception → mail_admins/Matrix) noierait les vraies pannes. D'où `warning` sur
        ce chemin et `exception` sur le précédent."""
        with patch('core.envoi_institution.envoyer_email_brevo',
                   side_effect=EchecBrevo("api-key not found")):
            send_branded_mail(requete, institution, "Sujet", "Corps\n\n{signature}",
                              ["dest@essai.invalide"])

        # Un seul mail : celui du destinataire. Aucune alerte technique.
        assert [m.to for m in mail.outbox] == [["dest@essai.invalide"]]

    def test_un_succes_efface_la_derniere_erreur(self, requete, institution, config):
        """Garder l'erreur après un envoi réussi ferait lire un problème résolu comme un
        problème courant."""
        config.derniere_erreur_email = "api-key not found"
        config.save(update_fields=['derniere_erreur_email'])

        with patch('core.envoi_institution.envoyer_email_brevo', return_value="<id@brevo>"):
            send_branded_mail(requete, institution, "Sujet", "Corps\n\n{signature}",
                              ["dest@essai.invalide"])

        config.refresh_from_db()
        assert config.derniere_erreur_email == ""
        assert config.dernier_envoi_email_le is not None


@pytest.mark.django_db
class TestLaCleNeFuitePas:

    def test_la_cle_est_chiffree_au_repos(self, config):
        """Vérifié en SQL BRUT et non par l'ORM : seule façon de constater ce qu'un `pg_dump`
        contiendrait."""
        with connection.cursor() as curseur:
            curseur.execute(
                "SELECT brevo_cle_api FROM core_configurationenvoiinstitution WHERE id = %s",
                [str(config.id)],
            )
            stocke = curseur.fetchone()[0]
        assert CLE not in (stocke or ""), "la clé API est en clair en base"
        # Et elle reste déchiffrable par l'ORM, sinon le chiffrement aurait cassé l'envoi.
        config.refresh_from_db()
        assert config.brevo_cle_api == CLE

    def test_l_api_ne_rend_jamais_la_cle(self, institution, config, create_user):
        membre_bureau = create_user(username='bureau-envoi@test.fr',
                                    email='bureau-envoi@test.fr', type='SECOURS',
                                    institution=institution)
        ContactInstitution.objects.create(institution=institution, utilisateur=membre_bureau,
                                          membre_bureau=True, actif=True)
        client = APIClient()
        client.force_authenticate(user=membre_bureau)

        reponse = client.get(f"/api/institutions/{institution.id}/configuration-envoi/")
        assert reponse.status_code == 200
        corps = str(reponse.data)
        # Ni la clé entière, ni un fragment : même quatre caractères réduisent le travail de
        # qui la cherche.
        assert CLE not in corps
        assert "0123456789abcdef" not in corps
        assert reponse.data['brevo_cle_api_renseignee'] is True
        assert 'brevo_cle_api' not in reponse.data

    def test_un_contact_actif_mais_hors_bureau_n_y_accede_pas(self, institution, config,
                                                              create_user):
        """Confier une clé qui permet d'envoyer AU NOM de l'association est un acte de
        gouvernance, du même ordre que d'administrer ses membres."""
        simple = create_user(username='simple-envoi@test.fr', email='simple-envoi@test.fr',
                            type='SECOURS', institution=institution)
        ContactInstitution.objects.create(institution=institution, utilisateur=simple,
                                          membre_bureau=False, actif=True)
        client = APIClient()
        client.force_authenticate(user=simple)

        assert client.get(
            f"/api/institutions/{institution.id}/configuration-envoi/").status_code == 403

    def test_un_compte_d_une_autre_institution_n_y_accede_pas(self, institution, config,
                                                              create_user):
        itype = InstitutionType.objects.get(code='AASC_ENVOI')
        autre = Institution.objects.create(nom="Autre Association", type=itype)
        intrus = create_user(username='intrus-envoi@test.fr', email='intrus-envoi@test.fr',
                             type='SECOURS', institution=autre)
        ContactInstitution.objects.create(institution=autre, utilisateur=intrus,
                                          membre_bureau=True, actif=True)
        client = APIClient()
        client.force_authenticate(user=intrus)

        assert client.get(
            f"/api/institutions/{institution.id}/configuration-envoi/").status_code == 403
