"""Chiffrement applicatif des colonnes contenant des données personnelles.

Périmètre, clés et index aveugles : DOCUMENTATION.md, § 10.1.
"""
import hashlib
import hmac
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.validators import EmailValidator
from django.db import models

_fernet_instance = None


def _fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is None:
        if not settings.FIELD_ENCRYPTION_KEY:
            raise ImproperlyConfigured(
                "FIELD_ENCRYPTION_KEY n'est pas configurée -- aucun champ chiffré ne peut être "
                "lu ni écrit sans elle. Voir ~/.config/assista-crise/secrets/backend.env."
            )
        _fernet_instance = Fernet(settings.FIELD_ENCRYPTION_KEY.encode())
    return _fernet_instance


def blind_index(valeur: str) -> str:
    """HMAC de la valeur normalisée (espaces en bord et casse ignorés) : permet une recherche
    exacte sur une colonne chiffrée, jamais une recherche partielle."""
    if not settings.FIELD_BLIND_INDEX_KEY:
        raise ImproperlyConfigured(
            "FIELD_BLIND_INDEX_KEY n'est pas configurée -- voir "
            "~/.config/assista-crise/secrets/backend.env."
        )
    normalise = (valeur or "").strip().lower()
    return hmac.new(
        settings.FIELD_BLIND_INDEX_KEY.encode(), normalise.encode(), hashlib.sha256
    ).hexdigest()


class EncryptedTextField(models.TextField):
    """Texte chiffré Fernet dans une colonne TEXT ; la validation du texte en clair reste
    faite par le serializer."""

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        return _fernet().encrypt(str(value).encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # ligne antérieure au chiffrement : lisible plutôt qu'une erreur 500
            return value


class EncryptedEmailField(EncryptedTextField):
    """EncryptedTextField avec validation du format email (utile à l'admin Django)."""
    default_validators = [EmailValidator()]


class EncryptedJSONField(EncryptedTextField):
    """Valeur JSON (liste, dict) chiffrée, exposée comme un objet Python natif."""

    def get_prep_value(self, value):
        if value is None:
            return value
        return super().get_prep_value(json.dumps(value))

    def from_db_value(self, value, expression, connection):
        value = super().from_db_value(value, expression, connection)
        if value is None or value == "":
            return value
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            # ligne antérieure au chiffrement, comme dans la classe parente
            return value
