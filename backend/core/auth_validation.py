import json
import re
import urllib.parse
import urllib.request
from typing import Tuple


class InstitutionEmailValidator:
    """Valide les emails des comptes institutionnels publics et collectivités locales."""

    @staticmethod
    def _fetch_json(url: str):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

    @staticmethod
    def _resolve_commune_code(commune_name: str, commune_code: str = ""):
        if commune_code:
            return commune_code

        if not commune_name:
            return ""

        search_url = f"https://geo.api.gouv.fr/communes?nom={urllib.parse.quote(commune_name)}&fields=code,nom"
        data = InstitutionEmailValidator._fetch_json(search_url)
        if isinstance(data, list) and data:
            return str(data[0].get("code", ""))
        return ""

    @staticmethod
    def _check_open_data_institution(institution_type: str, commune_code: str):
        if not commune_code:
            return None

        normalized_type = (institution_type or "").strip().lower()
        endpoint_map = {
            "commune": f"https://geo.api.gouv.fr/communes/{commune_code}",
            "mairie": f"https://etablissements-publics.api.gouv.fr/v3/communes/{commune_code}/mairies",
            "prefecture": f"https://etablissements-publics.api.gouv.fr/v3/communes/{commune_code}/prefectures",
            "préfecture": f"https://etablissements-publics.api.gouv.fr/v3/communes/{commune_code}/prefectures",
            "police": f"https://etablissements-publics.api.gouv.fr/v3/communes/{commune_code}/polices",
            "gendarmerie": f"https://etablissements-publics.api.gouv.fr/v3/communes/{commune_code}/gendarmeries",
            "samu": f"https://etablissements-publics.api.gouv.fr/v3/communes/{commune_code}/samu",
            "collectivite": f"https://geo.api.gouv.fr/communes/{commune_code}",
            "collectivités": f"https://geo.api.gouv.fr/communes/{commune_code}",
            "cc": f"https://geo.api.gouv.fr/communes/{commune_code}",
            "intercommunalite": f"https://geo.api.gouv.fr/communes/{commune_code}",
            "intercommunalité": f"https://geo.api.gouv.fr/communes/{commune_code}",
            "ministere": f"https://etablissements-publics.api.gouv.fr/v3/communes/{commune_code}/prefectures",
            "ministère": f"https://etablissements-publics.api.gouv.fr/v3/communes/{commune_code}/prefectures",
            "sdis": f"https://etablissements-publics.api.gouv.fr/v3/communes/{commune_code}/sdis",
        }

        url = endpoint_map.get(normalized_type)
        if not url:
            return None

        return InstitutionEmailValidator._fetch_json(url)

    @staticmethod
    def requires_open_data_validation(institution_type: str) -> bool:
        normalized_type = (institution_type or "").strip().lower()
        return normalized_type in {
            "commune",
            "mairie",
            "intercommunalite",
            "intercommunalité",
            "prefecture",
            "préfecture",
            "sdis",
            "samu",
            "police",
            "gendarmerie",
            "collectivite",
            "collectivités",
            "cc",
            "ministere",
            "ministère",
        }

    @staticmethod
    def requires_limited_access(institution_type: str) -> bool:
        normalized_type = (institution_type or "").strip().lower()
        return normalized_type in {
            "aasc",
            "dfci",
            "ccff",
            "association",
            "entreprise",
            "autre",
            "autres",
            "ong",
            "collectif",
        }

    @staticmethod
    def validate_email_domain(email: str) -> Tuple[bool, str]:
        if not email:
            return False, "Une adresse email est requise"

        email = email.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            return False, "L'adresse email n'est pas au bon format"

        domain = email.split("@", 1)[1]
        allowed_patterns = [
            r"^mairie(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
            r"^.*\.mairie(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
            r"^.*(?:prefecture|gendarmerie|police|samu|collectivite|collectivités|communaute|communes?|commune|intercommunalite|metropole|departement|region)(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
            r"^prefecture(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
            r"^police(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
            r"^gendarmerie(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
            r"^samu(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
            r"^ministere(?:[.-][a-z0-9-]+)*(?:\.gouv\.fr)?$",
            r"^.*\.gouv\.fr$",
            r"^cc(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
            r"^.*-cc(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
            r"^.*communaut(?:e|es)(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
            r"^.*collectivite(?:s)?(?:[.-][a-z0-9-]+)*(?:\.fr)?$",
        ]

        for pattern in allowed_patterns:
            if re.fullmatch(pattern, domain):
                return True, "Adresse email valide"

        return False, (
            "L'adresse email doit correspondre à un domaine institutionnel public valide "
            "(mairie, préfecture, gendarmerie, police, SAMU, ministère, communauté de communes, collectivité locale, etc.)."
        )

    SPECIFIC_TYPE_DOMAIN_TOKENS = {
        "mairie": "mairie",
        "prefecture": "prefecture",
        "préfecture": "prefecture",
        "police": "police",
        "gendarmerie": "gendarmerie",
        "samu": "samu",
        "sdis": "sdis",
        "ministere": "ministere",
        "ministère": "ministere",
    }

    @staticmethod
    def validate_institution_account(
        email: str,
        institution_name: str = "",
        institution_type: str = "",
        commune_name: str = "",
        commune_code: str = "",
    ):
        """Valide un compte institutionnel à partir de l'email, du type d'institution et de la commune."""
        email_valid, email_message = InstitutionEmailValidator.validate_email_domain(email)
        if not email_valid:
            return False, email_message, {"email": email_message}

        normalized_type = (institution_type or "").strip().lower()
        normalized_commune = (commune_name or "").strip().lower()
        normalized_name = (institution_name or "").strip().lower()
        resolved_code = InstitutionEmailValidator._resolve_commune_code(commune_name, commune_code)

        details = {
            "institution": {
                "name": institution_name or "",
                "type": institution_type or "",
            },
            "commune": {
                "name": commune_name or "",
                "code": resolved_code or commune_code or "",
            },
        }

        domain = email.split("@", 1)[1]
        selected_token = InstitutionEmailValidator.SPECIFIC_TYPE_DOMAIN_TOKENS.get(normalized_type)
        if selected_token:
            domain_tokens = {
                token for token in set(InstitutionEmailValidator.SPECIFIC_TYPE_DOMAIN_TOKENS.values())
                if token in domain
            }
            if domain_tokens and selected_token not in domain_tokens:
                return False, (
                    "Le type d'institution sélectionné est incompatible avec le domaine de l'adresse email."
                ), details

        if InstitutionEmailValidator.requires_open_data_validation(normalized_type):
            if normalized_commune and resolved_code:
                open_data_result = InstitutionEmailValidator._check_open_data_institution(normalized_type, resolved_code)
                if open_data_result is not None:
                    if isinstance(open_data_result, dict):
                        features = open_data_result.get("features") or []
                        if features:
                            details["validation_mode"] = "opendata"
                            return True, "Validation institutionnelle valide", details
                    elif isinstance(open_data_result, list):
                        if open_data_result:
                            details["validation_mode"] = "opendata"
                            return True, "Validation institutionnelle valide", details

            if normalized_type in {"mairie", "commune", "collectivite", "collectivité", "communauté de communes", "cc", "intercommunalite", "intercommunalité"}:
                if "mairie" not in normalized_name and "collectiv" not in normalized_name and "communaute" not in normalized_name and "commune" not in normalized_name and "cc" not in normalized_name and "intercommunal" not in normalized_name:
                    return False, "Le nom de l'institution est incompatible avec le type sélectionné.", details

            if normalized_type == "mairie" and "mairie" not in normalized_name and "mairie" not in email:
                return False, "Le domaine email ne correspond pas au type mairie sélectionné.", details

            if normalized_type in {"prefecture", "préfecture"} and "prefecture" not in email and "prefecture" not in normalized_name:
                return False, "Le domaine email ne correspond pas au type préfecture sélectionné.", details

            if normalized_type in {"police", "gendarmerie", "samu", "ministere", "ministère", "sdis"}:
                expected_token = normalized_type.replace("é", "e")
                if expected_token not in email and expected_token not in normalized_name:
                    return False, f"Le domaine email ne correspond pas au type {institution_type} sélectionné.", details

            return True, "Validation institutionnelle valide", details

        if InstitutionEmailValidator.requires_limited_access(normalized_type):
            details["validation_mode"] = "limited"
            return True, "Compte institutionnel enregistré avec accès limité", details

        if normalized_commune and "mairie" in email and normalized_commune not in email and normalized_commune not in normalized_name:
            return False, "La commune ne correspond pas au domaine email fourni.", details

        details["validation_mode"] = "limited"
        return True, "Compte institutionnel enregistré avec accès limité", details
