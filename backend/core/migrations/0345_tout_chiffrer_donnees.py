"""Chiffre en base tout ce qui est saisi ou personnel (18/11/2026, « tout doit être chiffré en
base, corrige cela ») : textes libres, titres et motifs, noms et identifiant des comptes, journaux
d'état de la main courante et de la synchronisation, et les jetons des liens envoyés par
courriel (chiffrés, retrouvés par leur empreinte).

Données seulement : le schéma a changé en 0344. Même patron que 0302 : la lecture rend le clair
(brut si la ligne ne l'était pas encore, déchiffré sinon) et l'écriture rechiffre ; la migration
est donc réexécutable, et réversible. Par paquets de 500 lignes.
"""
import json

from django.db import connection, migrations

#: Modèle -> champs chiffrés par cette migration.
CHAMPS = {
    "Crisis": ('description',),
    "ImplicationInstitution": ('commentaire',),
    "FormulaireTerrain": ('description', 'titre'),
    "OfferMessage": ('contenu',),
    "Institution": ('description', 'adresse', 'telephone', 'email', 'email_reply_to'),
    "ModeleMessage": ('sujet', 'corps'),
    "InstitutionCompetence": ('commentaire',),
    "AffectationCompetence": ('commentaire',),
    "Dossier": ('description', 'titre'),
    "Mission": ('description', 'titre'),
    "DossierCommentaire": ('commentaire',),
    "DossierHistorique": ('commentaire',),
    "Document": ('commentaire', 'metadata_privees'),
    "NotificationAlertePCS": ('message_envoye', 'detail_erreur'),
    "Zone": ('description',),
    "HabitationCommentaire": ('commentaire',),
    "HabitationHistorique": ('commentaire',),
    "PieceIdentiteReserve": ('motif_refus',),
    "Team": ('description',),
    "TeamDelegation": ('commentaire',),
    "Notification": ('message', 'titre', 'details'),
    "DemandeMobilisation": ('motif', 'lieu_texte'),
    "RecherchePersonneCommentaire": ('commentaire',),
    "RecherchePersonneHistorique": ('commentaire',),
    "RecherchePersonne": ('ville',),
    "RecherchePersonnePhoto": ('commentaire',),
    "SecteurRecherche": ('nom',),
    "AffectationRoleOperationnel": ('commentaire', 'responsabilite'),
    "DisponibiliteOperationnelle": ('commentaire',),
    "DelegationCompetence": ('commentaire',),
    "PointOperationnel": ('adresse', 'commentaire', 'description'),
    "Plan": ('description',),
    "PlanMissionModele": ('description',),
    "DossierPCS": ('modalites_activation', 'lieu_pcc', 'lieu_pcc_repli'),
    "RevisionPCS": ('objet',),
    "FonctionPCS": ('consignes',),
    "MoyenAlertePCS": ('consignes', 'description'),
    "ExercicePCS": ('deroulement', 'enseignements', 'actions', 'theme'),
    "MaterielPoint": ('commentaire',),
    "ContributionMateriel": ('commentaire',),
    "RegistrePresence": ('commentaire',),
    "SuiviMaterielEvenement": ('commentaire', 'lieu_reparation'),
    "RisqueCommunal": ('etat_des_lieux', 'enjeux'),
    "SuiviSiteSensible": ('commentaire',),
    "HabilitationRegistreVulnerables": ('motif_retrait', 'fonction'),
    "AuditLog": ('commentaire', 'user_agent', 'ancien_etat', 'nouvel_etat', 'recherche'),
    "QualificationMembre": ('commentaire', 'motif_refus', 'organisme', 'justificatif_nom'),
    "CandidatureAssociation": ('message_candidat', 'commentaire_bureau', 'motif_refus'),
    "RelaisMeshCore": ('commentaire',),
    "RattachementNoeudRadio": ('note', 'libelle'),
    "DemandeAccesRadio": ('motif', 'commentaire_decision'),
    "CreneauEquipe": ('commentaire', 'role'),
    "PieceJointePCS": ('titre', 'nom_fichier'),
    "AlertePopulation": ('titre', 'bilan', 'terrain'),
    "SolutionRelogement": ('motif_fin', 'prise_en_charge_par'),
    "SiteSensible": ('telephone',),
    "PersonneVulnerable": ('demandeur_consentement',),
    "ContactInstitution": ('fonction',),
    "FicheBenevole": ('ville',),
    "InvitationAssociation": ('libelle',),
    "EvenementSynchronisation": ('auteur_local_email', 'auteur_local_nom', 'payload'),
    "CampagneDisponibilite": ('intitule',),
    "AffectationRotation": ('motif',),
    "MouvementStock": ('motif',),
    "PersonneFoyer": ('taille_haut', 'taille_bas', 'pointure'),
    "BesoinFoyer": ('designation', 'taille'),
    "BesoinDon": ('precision', 'message'),
    "DemandeTransfertStock": ('message', 'reponse'),
    "Habitation": ('parcelle_cadastrale',),
    "EngagementPersonnel": ('hebergement',),
    "PointageTerrain": ('motif_refus',),
    "SessionRelaisNavigateur": ('user_agent', 'motif_fermeture'),
    "CibleCampagne": ('erreur',),
    "AlerteMeshSOS": ('expediteur_identifiant',),
    "ConflitSynchronisation": ('payload_local', 'etat_central_au_conflit'),
    "AppareilStock": ('commentaire',),
    "AppelAuxDons": ('description', 'livraison_horaires', 'titre'),
    "BienSinistre": ('description', 'designation'),
    "BrouillonEnvoi": ('erreur',),
    "CommandeStock": ('commentaire',),
    "ConfigurationEnvoiInstitution": ('brevo_admin_email', 'brevo_expediteur_email', 'derniere_erreur_email', 'derniere_erreur_sms'),
    "ControleAppareilStock": ('commentaire',),
    "EnvoiDon": ('commentaire', 'transporteur'),
    "FactureStock": ('commentaire',),
    "Information": ('title',),
    "Offer": ('title', 'transport_animaux_precision'),
    "PretMateriel": ('conditions',),
    "Request": ('title',),
    "User": ('username', 'first_name', 'last_name', 'pending_institution_name', 'pending_commune_name'),
}

#: Modèle -> jetons, chiffrés ET dotés de leur empreinte.
JETONS = {
    "Request": ('deletion_token', 'edition_token'),
    "Information": ('deletion_token', 'edition_token'),
    "Offer": ('deletion_token', 'reponse_token'),
    "NotificationAlertePCS": ('token_confirmation',),
    "EngagementRessource": ('token_confirmation',),
    "DemandeMobilisation": ('jeton_verification',),
    "AffectationPointBenevole": ('token_confirmation',),
    "InvitationAssociation": ('jeton',),
    "JetonEnrolementSatellite": ('jeton',),
    "DemandeRapport": ('jeton',),
}

PAQUET = 500


def _tous_les_champs(nom):
    return tuple(CHAMPS.get(nom, ())) + tuple(JETONS.get(nom, ()))


def chiffrer(apps, schema_editor):
    from core.crypto_fields import empreinte_jeton

    for nom in dict.fromkeys(list(CHAMPS) + list(JETONS)):
        Modele = apps.get_model("core", nom)
        champs = _tous_les_champs(nom)
        empreintes = [f"{j}_empreinte" for j in JETONS.get(nom, ())]
        lot = []
        for objet in Modele._base_manager.only("pk", *champs).order_by("pk").iterator(chunk_size=PAQUET):
            for jeton in JETONS.get(nom, ()):
                valeur = getattr(objet, jeton)
                setattr(objet, f"{jeton}_empreinte", empreinte_jeton(valeur) if valeur else None)
            lot.append(objet)
            if len(lot) >= PAQUET:
                Modele._base_manager.bulk_update(lot, list(champs) + empreintes)
                lot = []
        if lot:
            Modele._base_manager.bulk_update(lot, list(champs) + empreintes)


def dechiffrer(apps, schema_editor):
    """SQL direct : repasser par l'ORM rechiffrerait ce qu'on vient de déchiffrer."""
    for nom in dict.fromkeys(list(CHAMPS) + list(JETONS)):
        Modele = apps.get_model("core", nom)
        table = Modele._meta.db_table
        champs = _tous_les_champs(nom)
        colonnes = [Modele._meta.get_field(c) for c in champs]
        with connection.cursor() as curseur:
            for objet in Modele._base_manager.only("pk", *champs).order_by("pk").iterator(chunk_size=PAQUET):
                valeurs = []
                for champ in colonnes:
                    v = getattr(objet, champ.attname)
                    if type(champ).__name__ == "EncryptedJSONField" and v is not None and not isinstance(v, str):
                        v = json.dumps(v)
                    valeurs.append(v)
                affectations = ", ".join(f'"{c.column}" = %s' for c in colonnes)
                curseur.execute(f'UPDATE "{table}" SET {affectations} WHERE "{Modele._meta.pk.column}" = %s',
                                valeurs + [objet.pk])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0344_tout_chiffrer_schema"),
    ]

    operations = [
        migrations.RunPython(chiffrer, dechiffrer),
    ]
