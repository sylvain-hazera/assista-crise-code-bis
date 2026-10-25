"""Email d'activation envoyé à l'inscription d'un compte "Autorité locale" (register() ->
send_institution_account_email). Un échec avant send_mail_logged (ex: build_magic_link) ne
laissait auparavant aucune trace — juste un print() perdu dans les logs du conteneur, jamais
visible depuis l'app — repéré en direct (compte créé, personne n'a jamais reçu son lien
d'activation, aucun admin ne pouvait le savoir). Corrigé en journalisant aussi cet échec dans
la main courante (AuditLog, action ENVOI_EMAIL, succes=False)."""
from unittest.mock import patch

import pytest
from django.core import mail
from django.urls import reverse
from rest_framework import status

from core.crypto_fields import blind_index
from core.models import AuditLog, User


@pytest.mark.django_db
class TestActivationEmailAutoriteLocale:

    @patch("core.auth_validation.InstitutionEmailValidator._search_annuaire", return_value=None)
    def test_register_envoie_l_email_d_activation(self, mock_search, api_client, user_data):
        payload = {
            **user_data,
            "email": "contact@collectivite-register-test.fr",
            "username": "contact@collectivite-register-test.fr",
            "type": "AUT_LOCALE",
            "institution_name": "Mairie Register Test",
            "commune_name": "Grenoble",
            "commune_code": "38185",
        }
        response = api_client.post(reverse("user-register"), payload, format="json")

        assert response.status_code == status.HTTP_201_CREATED, response.data
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["contact@collectivite-register-test.fr"]
        assert "activation" in mail.outbox[0].body.lower()

        user = User.objects.get(email_bidx=blind_index("contact@collectivite-register-test.fr"))
        log = AuditLog.objects.filter(
            action__code="ENVOI_EMAIL", commentaire__icontains=user.email,
        ).first()
        assert log is not None
        assert log.succes is True

    @patch("core.auth_validation.InstitutionEmailValidator._search_annuaire", return_value=None)
    def test_echec_envoi_active_le_compte_quand_meme_et_journalise_l_echec(self, mock_search, api_client, user_data):
        payload = {
            **user_data,
            "email": "contact@collectivite-echec-mail-test.fr",
            "username": "contact@collectivite-echec-mail-test.fr",
            "type": "AUT_LOCALE",
            "institution_name": "Mairie Échec Mail Test",
            "commune_name": "Grenoble",
            "commune_code": "38185",
        }
        with patch("core.views.send_institution_account_email", side_effect=RuntimeError("SMTP down")):
            response = api_client.post(reverse("user-register"), payload, format="json")

        # Le compte est créé malgré l'échec d'envoi (comportement inchangé) : seule la
        # traçabilité de l'échec est ajoutée par ce correctif.
        assert response.status_code == status.HTTP_201_CREATED
        user = User.objects.get(email_bidx=blind_index("contact@collectivite-echec-mail-test.fr"))

        log = AuditLog.objects.filter(
            action__code="ENVOI_EMAIL", commentaire__icontains=user.email,
        ).first()
        assert log is not None
        assert log.succes is False
        assert "SMTP down" in log.commentaire


@pytest.mark.django_db
class TestInscriptionPubliqueEnvoieLeLien:
    """Le formulaire public poste sur /api/register/ (RegisterView), PAS sur
    /api/users/register/ : ce chemin-là ne envoyait aucun email, donc tout compte créé depuis le
    site l'était muet, sans lien d'activation (constaté le 25/10/2026). Les tests existants ne
    couvraient que l'autre URL, d'où un bug invisible."""

    @patch("core.auth_validation.InstitutionEmailValidator._search_annuaire", return_value=None)
    def test_le_chemin_reellement_appele_envoie_l_email(self, mock_search, api_client, user_data):
        payload = {
            **user_data,
            "email": "maire@collectivite-public-test.fr",
            "username": "maire@collectivite-public-test.fr",
            "type": "AUT_LOCALE",
            "institution_name": "Mairie Public Test",
            "commune_name": "Grenoble",
            "commune_code": "38185",
        }

        reponse = api_client.post(reverse("auth_register"), payload, format="json")

        assert reponse.status_code == status.HTTP_201_CREATED, reponse.data
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ["maire@collectivite-public-test.fr"]
        assert "activation" in mail.outbox[0].body.lower()


@pytest.mark.django_db
class TestRenvoiDuLienActivation:

    def _compte(self, create_user, enabled=False, **kwargs):
        # create_user force enabled=True après création : on repose l'état voulu ensuite.
        compte = create_user(**{"type": "AUT_LOCALE", **kwargs})
        compte.enabled = enabled
        compte.save(update_fields=["enabled"])
        return compte

    def _client_institutionnel(self, create_user):
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=create_user(
            username="cadre-renvoi@test.fr", email="cadre-renvoi@test.fr", type="AUT_LOCALE"))
        return client

    def test_renvoi_a_un_compte_non_active(self, create_user):
        cible = self._compte(create_user, username="muet@mairie-test.fr", email="muet@mairie-test.fr")
        client = self._client_institutionnel(create_user)
        mail.outbox.clear()

        reponse = client.post(reverse("user-renvoyer-activation", args=[cible.id]))

        assert reponse.status_code == status.HTTP_200_OK, reponse.data
        assert [m.to for m in mail.outbox] == [["muet@mairie-test.fr"]]
        assert "activation" in mail.outbox[0].body.lower()
        assert AuditLog.objects.filter(
            objet_id=cible.id, commentaire__icontains="renvoyé").exists()

    def test_refus_si_le_compte_est_deja_active(self, create_user):
        cible = self._compte(create_user, enabled=True, username="actif@mairie-test.fr",
                             email="actif@mairie-test.fr")
        client = self._client_institutionnel(create_user)
        mail.outbox.clear()

        reponse = client.post(reverse("user-renvoyer-activation", args=[cible.id]))

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert mail.outbox == []

    def test_refus_pour_un_type_valide_par_un_administrateur(self, create_user):
        cible = self._compte(create_user, username="secours@test.fr",
                             email="secours@test.fr", type="SECOURS")
        client = self._client_institutionnel(create_user)
        mail.outbox.clear()

        reponse = client.post(reverse("user-renvoyer-activation", args=[cible.id]))

        assert reponse.status_code == status.HTTP_400_BAD_REQUEST
        assert mail.outbox == []
