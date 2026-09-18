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
    instance._version_de_base_avant_ecriture = (
        sender.objects.filter(pk=instance.pk).values_list("modifie_le", flat=True).first()
    )


def enregistrer_evenement(sender, instance, created, **kwargs):
    """post_save, tous les modèles synchronisables — voir la docstring du module pour la
    logique par régime."""
    from django.conf import settings
    if not settings.INSTANCE_SATELLITE_LOCALE:
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
