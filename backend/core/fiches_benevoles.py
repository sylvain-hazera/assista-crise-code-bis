"""Fiche d'un bénévole : géocodage de l'adresse et secteur dénormalisé.

Aligné sur ce que font déjà les autres ressources (`Offer`, `Habitation`) : une adresse texte,
un point géocodé par la BAN, puis le secteur (commune, EPCI, département, région) posé **une
fois** plutôt que rejoint à chaque lecture.

**C'est le géocodage qui donne le département d'affectation, pas le code postal.** Un code
postal n'est pas un code commune : la Corse partage `20xxx` entre 2A et 2B, l'outre-mer demande
trois chiffres, et un tableur mange le zéro initial. `commune_code` tranche exactement, par
`commune_secteur_codes`. La dérivation par code postal (`core/departements.py`) n'est plus qu'un
repli quand la BAN ne répond pas ou ne trouve rien — et ce repli est signalé, jamais silencieux.
"""
import logging

logger = logging.getLogger(__name__)


def geolocaliser_fiche(fiche):
    """Géocode l'adresse de la fiche et pose son secteur. Renvoie `(reussi, motif)`.

    Best-effort : ne lève jamais. Une fiche sans position reste exploitable — on sait joindre
    la personne, on ne sait pas la placer sur une carte.
    """
    from django.contrib.gis.geos import Point

    from .geo_lookup import commune_secteur_codes
    from .imports import _geocoder_adresse

    morceaux = [fiche.adresse, fiche.code_postal, fiche.ville]
    adresse_complete = " ".join(m.strip() for m in morceaux if m and m.strip())
    if not adresse_complete:
        return False, "Aucune adresse à géocoder."

    lat, lon, code_commune, nom_commune = _geocoder_adresse(adresse_complete)
    if lat is None or code_commune is None:
        return False, f"La BAN n'a pas reconnu l'adresse « {adresse_complete} »."

    fiche.location = Point(float(lon), float(lat), srid=4326)
    fiche.commune_code = code_commune
    if nom_commune and not fiche.ville:
        fiche.ville = nom_commune

    secteur = commune_secteur_codes(code_commune)
    fiche.epci_code = secteur.get("epci_code")
    fiche.departement_code = secteur.get("departement_code")
    fiche.region_code = secteur.get("region_code")
    return True, ""


def departement_de_la_fiche(fiche):
    """Le département d'affectation, et d'où il vient.

    Renvoie `(code, origine, motif)` — `origine` vaut `"geocodage"`, `"code_postal"` ou None.
    Savoir d'où vient le code n'est pas cosmétique : un département déduit d'un code postal est
    moins sûr qu'un département géocodé, et l'écran doit pouvoir le dire à celui qui relit
    l'import.
    """
    from .departements import departement_depuis_code_postal

    if fiche.departement_code:
        return fiche.departement_code, "geocodage", ""

    code, motif = departement_depuis_code_postal(fiche.code_postal)
    if code:
        return code, "code_postal", (
            "Déduit du code postal faute de géocodage : à vérifier si la personne est près "
            "d'une limite de département."
        )
    return None, None, motif
