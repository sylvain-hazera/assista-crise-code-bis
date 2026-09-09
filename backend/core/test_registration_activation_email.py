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

        user = User.objects.get(email="contact@collectivite-register-test.fr")
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
        user = User.objects.get(email="contact@collectivite-echec-mail-test.fr")

        log = AuditLog.objects.filter(
            action__code="ENVOI_EMAIL", commentaire__icontains=user.email,
        ).first()
        assert log is not None
        assert log.succes is False
        assert "SMTP down" in log.commentaire
