"""Formulaires de connexion PAR SESSION : l'administration Django et le pont OIDC (messagerie
Matrix, Grafana). Le reste du site se connecte par l'API (`core/connexion.py`).

Ces deux formulaires étaient un contournement tout prêt : un second facteur posé sur la seule
API aurait laissé entrer par ici avec le mot de passe seul. Ils appliquent les mêmes règles —
frein par compte, code exigé AVANT que le mot de passe soit regardé, refus après le délai
d'activation.

Tout tient sur une page (adresse, code, mot de passe) : ce sont des pages de service, vues par
peu de monde, pas le parcours en trois écrans du site.
"""
from django import forms
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from . import connexion, second_facteur
from . import frein_connexion as frein


class _FreinEtCode(forms.Form):
    code = forms.CharField(
        required=False, max_length=20, label="Code de sécurité",
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code", "inputmode": "numeric"}),
    )

    def _refus(self):
        return ValidationError(
            self.error_messages["invalid_login"], code="invalid_login",
            params={"username": self.username_field.verbose_name},
        )

    def clean(self):
        email = self.cleaned_data.get("username") or ""
        utilisateur = connexion.trouver_utilisateur(email)
        compteur = frein.cle(frein.ETAPE_MOT_DE_PASSE, email, utilisateur, voie="formulaire")
        reste = frein.attente(compteur)
        if reste:
            raise ValidationError(f"Trop d'essais. Réessayez dans {max(1, round(reste / 60))} min.",
                                  code="trop_d_essais")

        if utilisateur is not None and second_facteur.second_facteur_actif(utilisateur):
            # Le code d'abord : sans lui, le mot de passe n'est pas examiné.
            if not second_facteur.verifier_code(utilisateur, self.cleaned_data.get("code") or ""):
                frein.echec(compteur)
                raise self._refus()

        try:
            donnees = super().clean()
        except ValidationError:
            frein.echec(compteur)
            raise
        frein.reussite(compteur)

        if second_facteur.etat(self.get_user())["bloquant"]:
            raise ValidationError(
                "Ce compte doit d'abord activer son code de sécurité : connectez-vous au site, "
                "qui vous guidera.", code="second_facteur_a_activer")
        return donnees


class FormulaireConnexion(_FreinEtCode, AuthenticationForm):
    """Pont OIDC (`/accounts/login/`)."""


class FormulaireConnexionAdmin(_FreinEtCode, AdminAuthenticationForm):
    """Administration Django (`/django-admin/login/`)."""
