"""Réinscription avec une adresse déjà connue.

Défaut vu en production le 28/10/2026 sur app.reserve-resilience.org : quatre tentatives
d'inscription refusées de suite. Le serveur répondait 400 avec
`{"username": ["A user with that username already exists."]}` — en anglais, et en nommant un
champ que la personne n'a jamais rempli, le formulaire ne demandant qu'une adresse. La page,
de son côté, affichait la phrase fabriquée par Angular au lieu du corps de la réponse (voir
`shared/utils/message-erreur.ts`), si bien que rien de tout cela n'arrivait à l'écran.

Le message doit donc être **en français**, porté par la clé `email`, et **dire quoi faire** —
y compris pour le cas devenu fréquent depuis les invitations : un compte créé par invitation
et jamais activé, que se réinscrire ne débloque pas.
"""
import pytest
from rest_framework.test import APIClient

from core.models import User

URL = "/api/register/"


def _payload(email, **extra):
    return {
        "username": email, "email": email, "password": "MotDePasse!2026",
        "first_name": "Jean", "last_name": "Dupont", "type": "UTIL_SIMPLE",
        **extra,
    }


@pytest.mark.django_db
class TestInscriptionAvecAdresseDejaConnue:
    def test_une_premiere_inscription_passe(self):
        reponse = APIClient().post(URL, _payload("nouveau@exemple.fr"), format="json")

        assert reponse.status_code == 201, reponse.data

    def test_la_seconde_est_refusee_en_francais_sur_la_cle_email(self, create_user):
        create_user(username="deja@exemple.fr", email="deja@exemple.fr", type="UTIL_SIMPLE")

        reponse = APIClient().post(URL, _payload("deja@exemple.fr"), format="json")

        assert reponse.status_code == 400
        # Sur `email` : c'est le champ que la personne a rempli. Lui parler de `username` la
        # laissait chercher un champ qui n'existe pas dans le formulaire.
        assert "email" in reponse.data
        message = str(reponse.data["email"])
        assert "existe déjà" in message
        assert "username" not in message.lower()

    def test_le_message_dit_quoi_faire(self, create_user):
        create_user(username="quoi-faire@exemple.fr", email="quoi-faire@exemple.fr",
                    type="UTIL_SIMPLE")

        reponse = APIClient().post(URL, _payload("quoi-faire@exemple.fr"), format="json")

        message = str(reponse.data["email"])
        assert "mot de passe oublié" in message
        # Le cas devenu fréquent depuis les invitations : réinscrire ne débloque pas un compte
        # invité, il faut suivre le lien d'activation reçu.
        assert "activation" in message

    def test_un_compte_invite_non_active_donne_le_meme_refus(self, create_user):
        """Une invitation crée un compte inactif. La personne qui tente de s'inscrire ensuite
        doit être renvoyée vers son lien d'activation, pas laissée devant un refus opaque."""
        invite = create_user(username="invite@exemple.fr", email="invite@exemple.fr",
                             type="AUT_LOCALE")
        invite.is_active = False
        invite.enabled = False
        invite.save(update_fields=["is_active", "enabled"])

        reponse = APIClient().post(URL, _payload("invite@exemple.fr"), format="json")

        assert reponse.status_code == 400
        assert "activation" in str(reponse.data["email"])
        # Rien n'a été créé en double.
        assert User.objects.filter(email_bidx=invite.email_bidx).count() == 1

    def test_la_casse_de_l_adresse_ne_contourne_pas_le_refus(self, create_user):
        """L'index aveugle est calculé sur l'adresse normalisée : « Deja@ » et « deja@ » sont
        le même compte, sans quoi on fabriquerait des doublons à la première majuscule."""
        create_user(username="casse@exemple.fr", email="casse@exemple.fr", type="UTIL_SIMPLE")

        reponse = APIClient().post(URL, _payload("Casse@Exemple.fr"), format="json")

        assert reponse.status_code == 400
        assert "email" in reponse.data
