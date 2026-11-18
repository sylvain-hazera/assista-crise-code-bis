"""Chiffrement applicatif des colonnes contenant des données personnelles.

Périmètre, clés et index aveugles : DOCUMENTATION.md, § 10.1.
"""
import hashlib
import hmac
import json
import logging

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import FieldError, ImproperlyConfigured
from django.core.validators import EmailValidator
from django.db import models
from django.db.models.lookups import Exact, In

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


def empreinte_jeton(valeur: str) -> str:
    """HMAC EXACT d'un jeton (lien de modification, de confirmation…), sans normalisation :
    contrairement à `blind_index`, la casse compte, un jeton n'est pas une adresse."""
    if not settings.FIELD_BLIND_INDEX_KEY:
        raise ImproperlyConfigured("FIELD_BLIND_INDEX_KEY n'est pas configurée.")
    return hmac.new(settings.FIELD_BLIND_INDEX_KEY.encode(), (valeur or "").encode(), hashlib.sha256).hexdigest()


class RequeteSurChampChiffre(FieldError):
    """Un filtre, une recherche ou un tri SQL sur une colonne chiffrée : Fernet n'étant pas
    déterministe, la base ne compare que des textes chiffrés, et la requête rendrait un
    résultat faux SANS erreur. Chercher par l'index aveugle (`*_bidx`), ou filtrer en Python
    après déchiffrement (décision du 06/10/2026)."""


def _signaler(message):
    """Sous pytest : une erreur, pour que la suite trouve chaque requête fautive. En service :
    une trace dans le journal, la requête continue — mieux vaut un résultat incomplet qu'une
    page en erreur au milieu d'une crise."""
    import sys
    if "pytest" in sys.modules:
        raise RequeteSurChampChiffre(message)
    logging.getLogger("core.crypto_fields").error(message)


class _ExactSurChiffre(Exact):
    """Seule comparaison possible : à la valeur vide (« champ non rempli »)."""

    def __init__(self, lhs, rhs):
        if rhs not in ("", None):
            _signaler(f"Comparaison à une valeur sur la colonne chiffrée {getattr(lhs, 'target', lhs)}.")
        super().__init__(lhs, rhs)


class _InSurChiffre(In):
    def __init__(self, lhs, rhs):
        try:
            vide = all(v in ("", None) for v in rhs)
        except TypeError:          # une sous-requête
            vide = False
        if not vide:
            _signaler(f"Recherche « parmi » sur la colonne chiffrée {getattr(lhs, 'target', lhs)}.")
        super().__init__(lhs, rhs)


class EncryptedTextField(models.TextField):
    """Texte chiffré Fernet dans une colonne TEXT ; la validation du texte en clair reste
    faite par le serializer."""

    def get_lookup(self, lookup_name):
        if lookup_name == "isnull":
            return super().get_lookup(lookup_name)
        if lookup_name == "exact":
            return _ExactSurChiffre
        if lookup_name == "in":
            return _InSurChiffre
        _signaler(f"Recherche « {lookup_name} » impossible sur la colonne chiffrée {self.model.__name__}.{self.name}.")
        return super().get_lookup(lookup_name)

    def get_transform(self, lookup_name):
        _signaler(f"Transformation « {lookup_name} » impossible sur la colonne chiffrée {self.model.__name__}.{self.name}.")
        return super().get_transform(lookup_name)

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
