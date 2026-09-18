"""Peuple `EvenementSynchronisation` à chaque écriture locale pertinente — actif UNIQUEMENT
quand `settings.INSTANCE_SATELLITE_LOCALE` est vrai (voir core/apps.py:CoreConfig.ready, qui
connecte les signaux ci-dessous inconditionnellement ; chaque fonction vérifie le réglage
elle-même et ne fait rien sinon). Le central ne doit JAMAIS peupler cette file — il ne se
synchronise pas "vers lui-même".

Voir le cadrage Chantier B (sous-chantier "synchronisation local -> central", décisions du
2026-09-18) pour le détail des choix ci-dessous :

- **Périmètre v1** (`MODELES_SYNCHRONISABLES`) : le travail des acteurs institutionnels sur
  place pendant une coupure — Dossier + son fil (commentaires/historique), DeclarationSecurite,
  Mission, MessageMeshLog. PAS Request/Offer/Information (citoyens, alimentés via internet, pas
  via le LAN privé d'un satellite) — ajoutables plus tard sans redesign : juste une entrée dans
  `CHAMPS_PAR_MODELE` + le bon groupe (APPEND_ONLY/MUTABLE) + l'enregistrement du signal dans
  `CoreConfig.ready`.
- **Deux régimes** :
    - APPEND_ONLY : jamais réédités après création dans un sens qui compte pour la sync (un
      commentaire ne se modifie pas, une déclaration de sécurité non plus, le passage
      EN_ATTENTE -> ENVOYE d'un MessageMeshLog n'est jamais une divergence collaborative entre
      deux humains) — un simple upsert par id suffit côté central, jamais de conflit possible.
      On ne suit donc que les CREATIONS.
    - MUTABLE (Dossier, Mission) : vraiment modifiables des deux côtés pendant une même
      coupure (ex: un régulateur central change le statut d'un dossier pendant que l'équipe
      terrain le change aussi en local) — on capture `version_de_base` (la valeur de
      `modifie_le` juste AVANT la première écriture locale hors-ligne non encore synchronisée)
      pour que le central puisse détecter la divergence plutôt que d'écraser silencieusement.
"""
import logging
import uuid

from django.contrib.gis.geos import GEOSGeometry

logger = logging.getLogger(__name__)

# Champs extraits du modèle métier vers le payload JSON de synchronisation — liste explicite
# par modèle, jamais `__all__`/un sérialiseur DRF réutilisé (author/id sont read_only sur les
# sérialiseurs d'admin existants ; certains champs calculés n'ont de toute façon aucun sens à
# renvoyer tels quels). Les FK sont représentées par leur `<champ>_id` (uuid en str).
CHAMPS_PAR_MODELE = {
    "Dossier": [
        "numero", "crise_id", "competence_id", "equipe_id", "mission_id", "demande_id",
        "information_id", "titre", "description", "statut", "priorite", "ordre",
        "important", "date_signalement_important",
    ],
    "DossierCommentaire": ["dossier_id", "auteur_id", "commentaire", "date_creation"],
    "DossierHistorique": ["dossier_id", "auteur_id", "evenement", "commentaire", "date_creation"],
    "DeclarationSecurite": [
        "crise_id", "type_declarant", "situation", "nom_referent", "prenom_referent",
        "contact_referent", "nombre_adultes", "nombre_enfants", "ages_enfants",
        "commune_code", "epci_code", "departement_code", "region_code", "centre_accueil_id",
        "regime_alimentaire_specifique", "commentaire", "declare_par_id",
    ],
    "Mission": ["titre", "description", "crise_id", "statut", "date_cloture", "modele_origine_id"],
    "MessageMeshLog": [
        "compagnon_id", "direction", "contact_pubkey_hex", "expediteur_id", "equipe_id",
        "contenu", "statut", "erreur", "date_envoi",
    ],
}

APPEND_ONLY = {"DossierCommentaire", "DossierHistorique", "DeclarationSecurite", "MessageMeshLog"}
MUTABLE = {"Dossier", "Mission"}
MODELES_SYNCHRONISABLES = APPEND_ONLY | MUTABLE

# Champs auteur possibles, par ordre de préférence — best-effort : tous les modèles
# synchronisables n'ont pas d'auteur direct (Mission n'en a pas).
CHAMPS_AUTEUR_POSSIBLES = ("auteur", "declare_par", "expediteur")


def _valeur_serialisable(valeur):
    if hasattr(valeur, "isoformat"):
        return valeur.isoformat()
    if isinstance(valeur, uuid.UUID):
        return str(valeur)
    return valeur


def construire_payload(instance, nom_modele):
    return {
        champ: _valeur_serialisable(getattr(instance, champ))
        for champ in CHAMPS_PAR_MODELE[nom_modele]
    }


def _auteur_local(instance):
    for champ in CHAMPS_AUTEUR_POSSIBLES:
        utilisateur = getattr(instance, champ, None)
        if utilisateur is not None:
            nom = f"{utilisateur.first_name} {utilisateur.last_name}".strip()
            return utilisateur.email, nom
    return "", ""


def capturer_version_avant_ecriture(sender, instance, **kwargs):
    """pre_save, modèles MUTABLE uniquement : mémorise `modifie_le` tel qu'il est EN BASE avant
    cette écriture (auto_now l'aura déjà remplacé par la valeur courante au moment du post_save
    correspondant, donc c'est ici ou jamais qu'on peut la lire)."""
    from django.conf import settings
    if not settings.INSTANCE_SATELLITE_LOCALE or instance.pk is None:
        return
    if getattr(instance, "_synchronisation_entrante", False):
        return  # voir enregistrer_evenement pour le sens de ce marqueur.
    instance._version_de_base_avant_ecriture = (
        sender.objects.filter(pk=instance.pk).values_list("modifie_le", flat=True).first()
    )


def enregistrer_evenement(sender, instance, created, **kwargs):
    """post_save, tous les modèles synchronisables — voir la docstring du module pour la
    logique par régime."""
    from django.conf import settings
    if not settings.INSTANCE_SATELLITE_LOCALE:
        return
    if getattr(instance, "_synchronisation_entrante", False):
        # Cette écriture vient d'appliquer un pull central -> local (voir la commande de
        # gestion synchroniser_entrant) — CE N'EST PAS une écriture humaine locale à
        # repropager : la traiter comme telle boucherait indéfiniment (le central renverrait
        # sa propre donnée comme si elle venait de diverger localement).
        return

    nom_modele = sender.__name__
    if nom_modele not in MODELES_SYNCHRONISABLES:
        return
    if nom_modele in APPEND_ONLY and not created:
        return

    from .models import ActionSynchronisation, EtatEvenementSynchronisation, EvenementSynchronisation

    version_de_base = None
    if nom_modele in MUTABLE:
        evenements_en_cours = EvenementSynchronisation.objects.filter(
            modele=nom_modele, objet_id=instance.pk, etat=EtatEvenementSynchronisation.EN_ATTENTE,
        ).order_by("cree_le")
        evenement_le_plus_ancien = evenements_en_cours.first()
        version_de_base = (
            evenement_le_plus_ancien.version_de_base if evenement_le_plus_ancien is not None
            else getattr(instance, "_version_de_base_avant_ecriture", None)
        )
        # `payload` est toujours un instantané complet (pas un diff) : un événement encore
        # EN_ATTENTE pour ce même objet devient intégralement redondant dès qu'un nouveau est
        # créé — le supprimer évite qu'un lot de plusieurs écritures locales successives sur le
        # même objet ne se compare, au moment de l'application centrale, contre une
        # version_de_base déjà périmée par l'application de l'événement précédent DU MÊME LOT.
        evenements_en_cours.delete()

    auteur_email, auteur_nom = _auteur_local(instance)

    EvenementSynchronisation.objects.create(
        modele=nom_modele,
        objet_id=instance.pk,
        action=ActionSynchronisation.CREATION if created else ActionSynchronisation.MODIFICATION,
        payload=construire_payload(instance, nom_modele),
        version_de_base=version_de_base,
        auteur_local_email=auteur_email,
        auteur_local_nom=auteur_nom,
        environment=instance.environment,
    )


# --- Pull central -> local pour Crisis/Request/Offer/Information (SatelliteViewSet.donnees) ---
#
# PAS des sérialiseurs DRF admin réutilisés tels quels (RequestSerializer/OfferSerializer/
# InformationSerializer masquent `location` selon la zone/le rôle du VIEWER, `photo` est
# write_only) : un satellite qui pull les données de SA PROPRE institution fait autorité
# localement pour sa crise, ce n'est pas un viewer externe à qui appliquer ce masquage — un
# sérialiseur de sync dédié (liste de champs explicite) est plus sûr, voir la note du cadrage
# Chantier B sur ce sujet. Un champ géométrique (PointField/PolygonField/MultiPolygonField) se
# sérialise/désérialise uniformément via GeoJSON (GEOSGeometry expose `.geojson` et accepte une
# chaîne GeoJSON en entrée) — pas besoin de traiter chaque type de géométrie séparément.
# `photo` (ImageField) volontairement exclu : aucun transfert de fichier binaire par ce canal
# JSON, déjà le cas aujourd'hui (write_only sur les sérialiseurs existants, donc jamais
# renvoyé) — gap connu, pas nouveau, pas traité ici. Ces modèles ne sont PAS dans
# MODELES_SYNCHRONISABLES (pas de sens local -> central, alimentés par les citoyens via
# internet) : ce pull est un simple upsert côté satellite, jamais de conflit à détecter.
#
# Trois régimes de FK, pas un seul, parce qu'un UUID de catalogue (RequestType/OfferType/
# InformationType/MaterielCatalogue/Competence) n'a PAS le même sens des deux côtés : ces tables
# de "vocabulaire partagé" (voir leur docstring, ex. MaterielCatalogue) sont peuplées
# indépendamment sur chaque déploiement (migrations de données avec uuid4() auto, jamais un id
# fixe) — l'uuid central d'un RequestType "Aide urgente" n'a AUCUNE raison de coïncider avec
# l'uuid local du même nom. Trois stratégies :
#   - "partagee" : la cible existe (ou existera) avec le MÊME uuid des deux côtés (Crisis,
#     Mission — déjà synchronisées par ailleurs — et User, jamais synchronisé pour l'instant).
#     Référencée par id ; si absente localement, mise à None plutôt qu'un échec bloquant (voir
#     _resoudre_fk_partagee) — jamais de crash pour un simple auteur pas encore connu localement.
#   - "catalogue" : résolue par CLÉ NATURELLE (le nom métier, unique des deux côtés), get_or_create
#     localement si absente — cohérent avec la philosophie déjà en place de ces tables
#     ("n'importe quel centre peut ajouter une entrée, immédiatement réutilisable", voir
#     MaterielCatalogue.__doc__). Jamais nullable ici (request_type/offer_type/information_type
#     sont des champs requis) : DOIT toujours résoudre, jamais échouer silencieusement.
CHAMPS_PULL_CRISIS = (
    "name", "type", "description", "location", "radius", "zone", "zone_departements",
    "zone_communes", "zone_secteurs", "start_date", "end_date",
)
FK_PARTAGEES_CRISIS = ("author", "validator")
CHAMPS_GEO_CRISIS = ("location", "zone", "zone_secteurs")

_CHAMPS_HEBERGEMENT = (
    "hebergement_duree", "type_loyer", "loyer_montant_min", "loyer_montant_max", "type_logement",
    "niveau_logement", "acces_etage", "nombre_pieces", "nombre_chambres", "capacite_adultes",
    "capacite_enfants", "animaux_acceptes", "jardin", "pmr_compatible",
)

CHAMPS_PULL_REQUEST = (
    "title", "description", "location", "commune_code", "epci_code", "departement_code",
    "region_code", "zone_recherche_communes", "zone_recherche_rayon_km", "nombre_places_assises",
    "first_name_request", "last_name_request", "email_request", "phone_request", "created_at",
    "expires_at", "status", "actif",
) + _CHAMPS_HEBERGEMENT
FK_PARTAGEES_REQUEST = ("crisis", "author")
FK_CATALOGUE_REQUEST = {"request_type": ("RequestType", "type")}
CHAMPS_GEO_REQUEST = ("location",)

CHAMPS_PULL_OFFER = (
    "title", "description", "location", "commune_code", "epci_code", "departement_code",
    "region_code", "first_name_offer", "last_name_offer", "email_offer", "phone_offer",
    "created_at", "expires_at", "status", "actif", "organisation_nom", "groupe_id",
    "numero_adeli_rpps", "transport_type", "materiel_type", "cuve_contenu",
    "transport_animaux_precision", "quantite", "unite", "soutien_type", "diplome_secourisme",
    "ancien_sapeur_pompier", "materiel_livraison", "confirmation_reglementaire",
    "immatriculation", "nombre_places_assises", "renouvelable", "presence_physique",
    "accompagne", "nombre_accompagnants",
) + _CHAMPS_HEBERGEMENT
FK_PARTAGEES_OFFER = ("crisis", "author", "mission")
FK_CATALOGUE_OFFER = {"offer_type": ("OfferType", "type"), "materiel_catalogue": ("MaterielCatalogue", "nom")}
M2M_CATALOGUE_OFFER = {"competences": ("Competence", "nom")}
CHAMPS_GEO_OFFER = ("location",)

CHAMPS_PULL_INFORMATION = (
    "title", "first_name_information", "last_name_information", "email_information",
    "phone_information", "location", "commune_code", "azimuth", "created_at", "expires_at",
    "status", "actif",
)
FK_PARTAGEES_INFORMATION = ("crisis", "author")
FK_CATALOGUE_INFORMATION = {"information_type": ("InformationType", "type")}
CHAMPS_GEO_INFORMATION = ("location",)

# Nom de modèle -> spec complète — table unique utilisée par SatelliteViewSet.donnees
# (construction) ET synchroniser_entrant (application), pour ne jamais faire diverger les deux
# sens. `fk_catalogue`/`m2m_catalogue` : {champ: (nom_modele_catalogue, champ_cle_naturelle)}.
MODELES_PULL_SEUL = {
    "Crisis": {
        "champs": CHAMPS_PULL_CRISIS, "fk_partagees": FK_PARTAGEES_CRISIS,
        "fk_catalogue": {}, "m2m_catalogue": {}, "geo": CHAMPS_GEO_CRISIS,
    },
    "Request": {
        "champs": CHAMPS_PULL_REQUEST, "fk_partagees": FK_PARTAGEES_REQUEST,
        "fk_catalogue": FK_CATALOGUE_REQUEST, "m2m_catalogue": {}, "geo": CHAMPS_GEO_REQUEST,
    },
    "Offer": {
        "champs": CHAMPS_PULL_OFFER, "fk_partagees": FK_PARTAGEES_OFFER,
        "fk_catalogue": FK_CATALOGUE_OFFER, "m2m_catalogue": M2M_CATALOGUE_OFFER, "geo": CHAMPS_GEO_OFFER,
    },
    "Information": {
        "champs": CHAMPS_PULL_INFORMATION, "fk_partagees": FK_PARTAGEES_INFORMATION,
        "fk_catalogue": FK_CATALOGUE_INFORMATION, "m2m_catalogue": {}, "geo": CHAMPS_GEO_INFORMATION,
    },
}


def _valeur_pull(valeur):
    if isinstance(valeur, GEOSGeometry):
        return valeur.geojson
    if hasattr(valeur, "isoformat"):
        return valeur.isoformat()
    if isinstance(valeur, uuid.UUID):
        return str(valeur)
    return valeur


def construire_payload_pull(obj, nom_modele):
    spec = MODELES_PULL_SEUL[nom_modele]
    payload = {champ: _valeur_pull(getattr(obj, champ)) for champ in spec["champs"]}

    for champ in spec["fk_partagees"]:
        valeur_id = getattr(obj, f"{champ}_id")
        payload[f"{champ}_id"] = str(valeur_id) if valeur_id else None

    for champ, (_modele_cat, champ_cle) in spec["fk_catalogue"].items():
        cible = getattr(obj, champ)
        payload[f"{champ}_cle"] = getattr(cible, champ_cle) if cible is not None else None

    for champ, (_modele_cat, champ_cle) in spec["m2m_catalogue"].items():
        payload[champ] = list(getattr(obj, champ).values_list(champ_cle, flat=True))

    payload["id"] = str(obj.id)
    payload["environment"] = obj.environment
    return payload


def _resoudre_fk_partagee(ModeleClasse, champ, valeur_id):
    """La cible DEVRAIT exister avec le même id des deux côtés (Crisis/Mission déjà
    synchronisées, User jamais synchronisé à ce jour) — si elle n'existe pas encore
    localement, None plutôt qu'une erreur bloquante : un auteur pas encore connu localement ne
    doit jamais empêcher la demande/offre/signalement elle-même de descendre."""
    if not valeur_id:
        return None
    modele_cible = ModeleClasse._meta.get_field(champ).related_model
    return valeur_id if modele_cible.objects.filter(pk=valeur_id).exists() else None


def _resoudre_fk_catalogue(apps_get_model, nom_modele_cat, champ_cle, valeur_cle):
    if not valeur_cle:
        return None
    ModeleCat = apps_get_model('core', nom_modele_cat)
    objet, _cree = ModeleCat.objects.get_or_create(**{champ_cle: valeur_cle})
    return objet.id


def appliquer_payload_pull(apps_get_model, ModeleClasse, nom_modele, item):
    """Upsert simple (pas de conflit possible, voir la docstring de section ci-dessus) —
    reconstruit les champs géométriques depuis leur GeoJSON, résout/crée les FK de catalogue par
    clé naturelle, pose le M2M de catalogue (Offer.competences) après coup (nécessite que
    l'objet ait déjà un pk)."""
    spec = MODELES_PULL_SEUL[nom_modele]

    champs_directs = {champ: item[champ] for champ in spec["champs"] if champ in item}
    for champ in spec["geo"]:
        if champ in champs_directs:
            champs_directs[champ] = GEOSGeometry(champs_directs[champ]) if champs_directs[champ] else None

    for champ in spec["fk_partagees"]:
        champs_directs[f"{champ}_id"] = _resoudre_fk_partagee(ModeleClasse, champ, item.get(f"{champ}_id"))

    for champ, (nom_modele_cat, champ_cle) in spec["fk_catalogue"].items():
        champs_directs[f"{champ}_id"] = _resoudre_fk_catalogue(
            apps_get_model, nom_modele_cat, champ_cle, item.get(f"{champ}_cle")
        )

    objet, _cree = ModeleClasse.objects.update_or_create(
        id=item["id"], defaults={**champs_directs, "environment": item.get("environment", "PROD")},
    )

    for champ, (nom_modele_cat, champ_cle) in spec["m2m_catalogue"].items():
        ids = [
            _resoudre_fk_catalogue(apps_get_model, nom_modele_cat, champ_cle, valeur_cle)
            for valeur_cle in (item.get(champ) or [])
        ]
        getattr(objet, champ).set([i for i in ids if i])
    return objet
