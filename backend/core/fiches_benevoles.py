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


#: Type d'offre sous lequel un bénévole d'association est publié comme ressource. Le libellé
#: existe déjà dans le catalogue (`OfferType.type`) et sert aux offres citoyennes de bénévolat :
#: on le réutilise plutôt que d'en créer un second, sinon les écrans qui excluent « Bénévolat »
#: (tableau de bord, reporting) devraient connaître les deux.
TYPE_OFFRE_BENEVOLE = "Bénévolat"


def ressource_du_benevole(fiche, institution):
    """Crée ou met à jour l'offre qui représente ce bénévole comme RESSOURCE.

    Décision du 11/11/2026. Le moteur de disponibilité du projet — celui que lit
    `/admin/teams` pour constituer une équipe — est `DisponibiliteOffre`, et il est clé sur
    `Offer`. Pour qu'un bénévole y entre, il lui faut donc une offre. C'est aussi ce qui le
    rend trouvable comme ressource par les régulateurs de son association.

    **L'offre est `INTERNE`**, rattachée à l'institution : `Offer` est servi en `AllowAny` et
    alimente la carte publique. Sans ce cloisonnement, importer un fichier d'adhérents
    publierait l'annuaire de l'association (voir `VisibiliteOffre`).

    Idempotent, et retrouvée par `(author, institution, type)` et non par son titre : un
    libellé d'affichage n'a aucune raison d'être stable, et s'en servir de clé créerait une
    seconde ressource au premier changement de nom.

    Renvoie `(offre, creee)`.
    """
    from .models import Offer, OfferType, Status, VisibiliteOffre

    type_offre, _ = OfferType.objects.get_or_create(type=TYPE_OFFRE_BENEVOLE)
    utilisateur = fiche.utilisateur

    offre = Offer.objects.filter(
        author=utilisateur, institution=institution, offer_type=type_offre,
        environment=fiche.environment,
    ).first()
    creee = offre is None
    if creee:
        offre = Offer(
            author=utilisateur, institution=institution, offer_type=type_offre,
            environment=fiche.environment,
            visibilite=VisibiliteOffre.INTERNE,
            # DISPONIBLE : c'est l'état qui rend la ressource proposable, et il n'y a rien à
            # valider — l'adhésion a déjà eu lieu. Une offre citoyenne, elle, arrive en
            # NON_TRAITEE parce que personne ne l'a encore regardée.
            status=Status.AVAILABLE,
        )

    # Identité recopiée depuis le compte : les trois champs sont chiffrés au repos sur `Offer`
    # (`EncryptedTextField` / `EncryptedEmailField`), donc on ne dégrade rien.
    offre.title = _titre_ressource(utilisateur)
    offre.first_name_offer = utilisateur.first_name or ""
    offre.last_name_offer = utilisateur.last_name or ""
    offre.email_offer = utilisateur.email or ""
    offre.visibilite = VisibiliteOffre.INTERNE
    offre.institution = institution

    # Position et secteur viennent de la FICHE, déjà géocodée : la ressource se cherche par
    # territoire comme n'importe quelle offre, sans second géocodage.
    offre.location = fiche.location
    offre.commune_code = fiche.commune_code
    offre.epci_code = fiche.epci_code
    offre.departement_code = fiche.departement_code
    offre.region_code = fiche.region_code
    offre.save()
    return offre, creee


def _titre_ressource(utilisateur):
    """« Bénévole — Prénom N. ».

    Le nom de famille est ABRÉGÉ : `Offer.title` n'est pas chiffré (c'est un champ de
    recherche et de tri), et il s'affiche dans des listes. Y écrire l'état civil complet
    reviendrait à sortir en clair ce que `first_name_offer` / `last_name_offer` chiffrent juste
    à côté — le titre doit suffire à reconnaître quelqu'un dans une liste, pas à le constituer
    en fichier.
    """
    prenom = (utilisateur.first_name or "").strip()
    nom = (utilisateur.last_name or "").strip()
    initiale = f"{nom[0].upper()}." if nom else ""
    identite = " ".join(part for part in (prenom, initiale) if part)
    return f"Bénévole — {identite}" if identite else "Bénévole"
