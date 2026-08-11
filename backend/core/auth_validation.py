import json
import re
import urllib.parse
import urllib.request
from typing import Tuple


class InstitutionEmailValidator:
    """Valide les emails des comptes institutionnels publics et collectivités locales."""

    ANNUAIRE_SEARCH_URL = "https://api-lannuaire.service-public.gouv.fr/api/records/1.0/search/"

    @staticmethod
    def _fetch_json(url: str):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return None

    @staticmethod
    def _maybe_parse_json(value):
        """L'API annuaire renvoie ses champs complexes (site_internet, pivot, adresse...) comme des
        chaînes contenant du JSON sérialisé, pas comme des objets natifs. On les déserialise ici."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("[") or stripped.startswith("{"):
                try:
                    return json.loads(stripped)
                except (ValueError, TypeError):
                    return value
        return value

    @staticmethod
    def _normalize_text(value: str) -> str:
        # Volontairement PAS de suppression des accents : "Loire" et "Loiré" (une commune réelle
        # de Maine-et-Loire) sont deux noms différents, les confondre ferait échouer le repli vers
        # le niveau département/région pour "Loire" en le faisant matcher à tort sur "Loiré".
        return (value or "").strip().lower()

    @staticmethod
    def _best_geo_match(entries, name):
        """geo.api.gouv.fr classe ses résultats par score de pertinence textuelle, pas par exactitude :
        une recherche 'Loire' classe 'Loiret' (commune) devant la commune 'Loiré', et aucune des deux
        n'est ce qui est demandé. On n'accepte qu'un nom strictement identique (accents ignorés) ;
        sans correspondance exacte à ce niveau, on renvoie None pour laisser l'appelant retomber sur
        le niveau administratif suivant (commune → département → région) plutôt que de deviner."""
        if not entries:
            return None
        normalized_name = InstitutionEmailValidator._normalize_text(name)
        for entry in entries:
            if InstitutionEmailValidator._normalize_text(entry.get("nom", "")) == normalized_name:
                return entry
        return None

    @staticmethod
    def _departement_code_from_postal(code_postal: str):
        if not code_postal or len(code_postal) < 2:
            return None
        if code_postal.startswith(("97", "98")):
            return code_postal[:3]
        if code_postal.startswith("20"):
            return None  # Corse : le code postal seul ne distingue pas 2A/2B
        return code_postal[:2]

    @staticmethod
    def _resolve_zone_code(commune_name: str, commune_code: str = ""):
        """Résout un nom de zone géographique — commune, puis à défaut département, puis région —
        en code + nom officiels (geo.api.gouv.fr). Contrairement à _resolve_commune_code (qui ne
        gère que les communes, utilisé par la validation opendata existante), cette méthode couvre
        aussi les collectivités de niveau département/région (ex: un Conseil départemental)."""
        if commune_code:
            return {"level": "commune", "code": commune_code, "nom": commune_name or ""}

        if not commune_name:
            return None

        commune_data = InstitutionEmailValidator._fetch_json(
            f"https://geo.api.gouv.fr/communes?nom={urllib.parse.quote(commune_name)}&fields=code,nom"
        )
        match = InstitutionEmailValidator._best_geo_match(commune_data if isinstance(commune_data, list) else None, commune_name)
        if match:
            return {"level": "commune", "code": str(match.get("code", "")), "nom": match.get("nom", commune_name)}

        departement_data = InstitutionEmailValidator._fetch_json(
            f"https://geo.api.gouv.fr/departements?nom={urllib.parse.quote(commune_name)}&fields=code,nom"
        )
        match = InstitutionEmailValidator._best_geo_match(departement_data if isinstance(departement_data, list) else None, commune_name)
        if match:
            return {"level": "departement", "code": str(match.get("code", "")), "nom": match.get("nom", commune_name)}

        region_data = InstitutionEmailValidator._fetch_json(
            f"https://geo.api.gouv.fr/regions?nom={urllib.parse.quote(commune_name)}&fields=code,nom"
        )
        match = InstitutionEmailValidator._best_geo_match(region_data if isinstance(region_data, list) else None, commune_name)
        if match:
            return {"level": "region", "code": str(match.get("code", "")), "nom": match.get("nom", commune_name)}

        return None

    @staticmethod
    def _search_annuaire(institution_name: str, zone=None):
        """Interroge l'API Annuaire de l'administration (api-lannuaire.service-public.gouv.fr).

        rows=20 (et non 5) : la recherche plein texte de cette API classe par pertinence, pas par
        exactitude — pour un nom courant ("Conseil départemental de la Loire"), le bon enregistrement
        peut n'apparaître qu'en position 6-15. Le filtre refine.code_insee_commune n'existe que pour
        les services communaux (mairies...) : on ne l'applique donc qu'au niveau "commune", jamais
        pour un département/région (l'appliquer à tort renverrait zéro résultat)."""
        if not institution_name:
            return None

        params = {"dataset": "api-lannuaire-administration", "q": institution_name, "rows": "20"}
        if zone and zone.get("level") == "commune" and zone.get("code"):
            params["refine.code_insee_commune"] = zone["code"]

        url = f"{InstitutionEmailValidator.ANNUAIRE_SEARCH_URL}?{urllib.parse.urlencode(params)}"
        data = InstitutionEmailValidator._fetch_json(url)
        if not isinstance(data, dict):
            return None
        return data.get("records")

    @staticmethod
    def _extract_domain_candidates(record: dict):
        """Retourne les domaines email plausibles d'un enregistrement annuaire (email officiel, puis site web)."""
        fields = (record or {}).get("fields", record) or {}
        candidates = []

        email = InstitutionEmailValidator._maybe_parse_json(fields.get("adresse_courriel"))
        if isinstance(email, list):
            email = email[0] if email else None
        if isinstance(email, dict):
            email = email.get("valeur")
        if isinstance(email, str) and "@" in email:
            candidates.append(email.strip().lower().split("@", 1)[1])

        site = InstitutionEmailValidator._maybe_parse_json(fields.get("site_internet"))
        if isinstance(site, dict):
            site = [site]
        if isinstance(site, list):
            for entry in site:
                url = entry.get("valeur") if isinstance(entry, dict) else entry
                if not url:
                    continue
                try:
                    hostname = urllib.parse.urlparse(url).hostname
                except ValueError:
                    hostname = None
                if hostname:
                    candidates.append(hostname.lower().removeprefix("www."))

        return candidates

    @staticmethod
    def _record_departement_code(fields: dict):
        """Département déduit de l'adresse de l'enregistrement (best-effort, pour départager
        plusieurs correspondances de domaine ambiguës — jamais utilisé comme filtre bloquant)."""
        adresse = InstitutionEmailValidator._maybe_parse_json(fields.get("adresse"))
        if isinstance(adresse, dict):
            adresse = [adresse]
        if not isinstance(adresse, list):
            return None
        for entry in adresse:
            if isinstance(entry, dict):
                code = InstitutionEmailValidator._departement_code_from_postal(entry.get("code_postal"))
                if code:
                    return code
        return None

    @staticmethod
    def _match_annuaire_domain(domain: str, institution_name: str, commune_name: str = "", commune_code: str = ""):
        """Confirme (ou non) qu'un domaine email correspond à une institution connue de l'annuaire officiel,
        à n'importe quel échelon administratif (commune, département, région).

        Vérifie d'abord le cache local (InstitutionDomaine, alimenté par une précédente confirmation
        de l'annuaire) avant d'appeler l'API réelle, pour éviter de la resolliciter à chaque inscription
        sur un domaine déjà connu. Lecture seule : aucune écriture n'a lieu ici."""
        if domain:
            from .models import InstitutionDomaine

            cached = InstitutionDomaine.objects.filter(
                domaine__iexact=domain, valide=True
            ).select_related("institution", "institution__type").first()

            if cached:
                return {
                    "matched": True,
                    "domain": cached.domaine,
                    "nom": cached.institution.nom,
                    "type_service_local": cached.institution.type.code if cached.institution.type else None,
                }

        if not institution_name:
            return {"matched": False}

        zone = InstitutionEmailValidator._resolve_zone_code(commune_name, commune_code)
        records = InstitutionEmailValidator._search_annuaire(institution_name, zone)
        if not records:
            return {"matched": False}

        zone_departement = zone["code"] if zone and zone.get("level") == "departement" else None

        matches = []
        for record in records:
            fields = record.get("fields", record) if isinstance(record, dict) else {}
            for candidate in InstitutionEmailValidator._extract_domain_candidates(record):
                if domain == candidate or domain.endswith(f".{candidate}"):
                    pivot = InstitutionEmailValidator._maybe_parse_json(fields.get("pivot"))
                    if isinstance(pivot, list):
                        pivot = pivot[0] if pivot else None
                    type_service_local = pivot.get("type_service_local") if isinstance(pivot, dict) else None
                    matches.append({
                        "matched": True,
                        "domain": candidate,
                        "nom": fields.get("nom") or institution_name,
                        "type_service_local": type_service_local,
                        "_departement": InstitutionEmailValidator._record_departement_code(fields),
                    })
                    break  # un domaine correspondant suffit pour cet enregistrement

        if not matches:
            return {"matched": False}

        # Si plusieurs enregistrements distincts correspondent au domaine (rare), on préfère celui
        # dont le département déclaré correspond à la zone demandée, sans jamais rejeter les autres.
        if len(matches) > 1 and zone_departement:
            preferred = [m for m in matches if m.get("_departement") == zone_departement]
            if preferred:
                matches = preferred

        result = matches[0]
        result.pop("_departement", None)
        return result

    @staticmethod
    def _resolve_commune_code(commune_name: str, commune_code: str = ""):
        if commune_code:
            return commune_code

        if not commune_name:
            return ""

        search_url = f"https://geo.api.gouv.fr/communes?nom={urllib.parse.quote(commune_name)}&fields=code,nom"
        data = InstitutionEmailValidator._fetch_json(search_url)
        match = InstitutionEmailValidator._best_geo_match(data if isinstance(data, list) else None, commune_name)
        return str(match.get("code", "")) if match else ""

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
        email = (email or "").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            message = "L'adresse email n'est pas au bon format"
            return False, message, {"email": message}

        domain = email.split("@", 1)[1]
        resolved_code = InstitutionEmailValidator._resolve_commune_code(commune_name, commune_code)

        # Voie de confiance prioritaire : une correspondance confirmée par l'annuaire officiel
        # de l'administration l'emporte sur les heuristiques regex ci-dessous (qui ne couvrent pas
        # tous les domaines institutionnels réels, ex: sdis33.fr). Aucune écriture en base ici :
        # cette fonction doit rester pure (aussi utilisée pour une simple pré-vérification).
        annuaire_match = InstitutionEmailValidator._match_annuaire_domain(domain, institution_name, commune_name, commune_code)
        if annuaire_match.get("matched"):
            return True, "Validation institutionnelle confirmée via l'annuaire de l'administration", {
                "institution": {"name": institution_name or "", "type": institution_type or ""},
                "commune": {"name": commune_name or "", "code": resolved_code or commune_code or ""},
                "annuaire": annuaire_match,
                "validation_mode": "annuaire",
            }

        email_valid, email_message = InstitutionEmailValidator.validate_email_domain(email)
        if not email_valid:
            return False, email_message, {"email": email_message}

        normalized_type = (institution_type or "").strip().lower()
        normalized_commune = (commune_name or "").strip().lower()
        normalized_name = (institution_name or "").strip().lower()

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
