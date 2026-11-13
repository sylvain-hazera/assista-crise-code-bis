"""Mise en conformité des pièces déposées : détruire ce qu'il ne faut plus garder.

Demande de Sylvain du 13/11/2026 : « pour le permis, la destruction du fichier une fois
validé, et une destruction à 30 jours s'il n'est pas validé ».

**Ce module est la contrepartie exécutée de `core/conservation_pieces.py`.** La table y annonce
une politique ; ici elle s'applique. Les deux doivent rester d'accord : un tableau qui promet
une destruction qui n'a pas lieu est pire que pas de tableau, parce qu'il endort la vigilance
de celui qui dépose.

Trois moments, et un seul principe — **la trace survit, le fichier non** :

1. **À la validation**, pour les pièces du régime « vérifier puis détruire » (permis, pièce
   d'identité, justificatif de domicile) : le fichier est supprimé, la ligne reste avec qui a
   vérifié, quand, et jusqu'à quand la pièce était valable. C'est cette trace, et non la
   photocopie, qui prouve que le contrôle a eu lieu.
2. **Au refus**, pour les mêmes pièces : il n'y a plus rien à prouver, et le membre va en
   redéposer une autre. Garder la copie refusée n'aurait aucun usage.
3. **À 30 jours sans décision**, pour toutes les pièces : un dépôt que personne n'a relu ne
   doit pas devenir un stock de permis de conduire conservés sans raison. La personne et son
   encadrement sont prévenus une semaine avant — détruire en silence ferait redéposer dans le
   vide, alors que le manquement vient de l'encadrement qui n'a pas regardé.

Ce que la destruction ne touche jamais : le statut, la date de validation, le nom de celui qui
a validé, les dates d'obtention et d'expiration. Autrement dit, tout ce qui sert à savoir si la
personne peut partir en intervention.
"""
import logging

from django.utils import timezone

from .conservation_pieces import (
    JOURS_AVANT_PURGE_NON_VALIDEE, JOURS_AVANT_RAPPEL_PURGE, detruire_apres_validation, piece,
)

logger = logging.getLogger(__name__)


def categorie_de(qualification_membre):
    """La catégorie de conservation du titre, prise sur l'entrée du catalogue."""
    return getattr(qualification_membre.qualification, "categorie_piece", None) or ""


def regle_de(qualification_membre):
    """La ligne de la table applicable à ce titre : régime, durée, base légale, pourquoi."""
    return piece(categorie_de(qualification_membre))


def supprimer_fichier(objet, champ, champ_nom=None, champ_horodatage="piece_detruite_le"):
    """Supprime le fichier chiffré et horodate la destruction. Idempotent.

    Le nom d'origine est effacé avec le fichier : « permis-recto-2019.jpg » en dit déjà
    beaucoup, et le garder laisserait croire que la pièce est encore là.

    Renvoie True si quelque chose a été détruit."""
    fichier = getattr(objet, champ, None)
    if not fichier:
        return False
    champs = [champ]
    try:
        fichier.delete(save=False)
    except Exception:
        # Le stockage peut avoir perdu le fichier (restauration partielle, purge manuelle).
        # On continue : l'objectif est qu'il n'y en ait plus, et c'est atteint.
        logger.warning("Fichier déjà absent lors de la destruction de %s.%s", objet, champ)
        setattr(objet, champ, None)
    if champ_nom and getattr(objet, champ_nom, ""):
        setattr(objet, champ_nom, "")
        champs.append(champ_nom)
    if champ_horodatage and hasattr(objet, champ_horodatage):
        setattr(objet, champ_horodatage, timezone.now())
        champs.append(champ_horodatage)
    objet.save(update_fields=champs)
    return True


def appliquer_apres_decision(qualification_membre, request=None):
    """Détruit le justificatif si la catégorie l'exige, après validation OU refus.

    Appelé par les actions `verifier` et `refuser`. Renvoie True si le fichier a été détruit,
    ce qui permet à la vue de le dire à l'écran — une destruction silencieuse laisserait
    croire à un bug la prochaine fois qu'on cherche la pièce."""
    if not detruire_apres_validation(categorie_de(qualification_membre)):
        return False
    detruit = supprimer_fichier(
        qualification_membre, "justificatif", champ_nom="justificatif_nom",
    )
    if detruit:
        _journaliser(
            request, qualification_membre,
            f"Justificatif de « {qualification_membre.qualification} » détruit après "
            f"décision : cette pièce se vérifie et ne se conserve pas.",
        )
    return detruit


def _journaliser(request, objet, commentaire):
    from .audit import audit_log

    audit_log(
        request=request, action_code="SUPPRESSION",
        objet_type=objet.__class__.__name__, objet_id=objet.id, commentaire=commentaire,
    )


# ── Purge des dépôts restés sans décision ───────────────────────────────────────────────────

def a_purger(maintenant=None):
    """Les justificatifs déposés il y a plus de 30 jours que personne n'a instruits."""
    from .models import QualificationMembre, StatutQualification

    maintenant = maintenant or timezone.now()
    limite = maintenant - timezone.timedelta(days=JOURS_AVANT_PURGE_NON_VALIDEE)
    return QualificationMembre.objects.filter(
        statut=StatutQualification.DECLAREE,
        justificatif__isnull=False, justificatif_depose_le__lt=limite,
    ).exclude(justificatif="").select_related("qualification", "utilisateur")


def a_rappeler(maintenant=None):
    """Ceux qui seront purgés dans une semaine : on prévient avant, pas après.

    Fenêtre d'un jour et non « plus vieux que 23 jours » : la commande tourne chaque nuit, et
    la seconde formulation renverrait le même rappel tous les soirs pendant une semaine. Un
    rappel quotidien n'est plus un rappel, c'est du bruit qu'on apprend à ignorer."""
    from .models import QualificationMembre, StatutQualification

    maintenant = maintenant or timezone.now()
    age = timezone.timedelta(days=JOURS_AVANT_PURGE_NON_VALIDEE - JOURS_AVANT_RAPPEL_PURGE)
    return QualificationMembre.objects.filter(
        statut=StatutQualification.DECLAREE,
        justificatif__isnull=False,
        justificatif_depose_le__lte=maintenant - age,
        justificatif_depose_le__gt=maintenant - age - timezone.timedelta(days=1),
    ).exclude(justificatif="").select_related("qualification", "utilisateur")


def purger(maintenant=None, appliquer=True):
    """Détruit les justificatifs restés sans décision au-delà du délai.

    La LIGNE est conservée, pas le fichier : le titre reste déclaré, et le membre voit qu'il
    doit redéposer. Supprimer la ligne entière lui ferait perdre la date d'obtention et
    l'organisme qu'il avait saisis — une double peine pour une négligence qui n'est pas la
    sienne.

    `appliquer=False` rend la liste sans rien détruire : c'est le mode par défaut de la
    commande, parce qu'une purge ne se lance pas à l'aveugle."""
    purgees = []
    for ligne in a_purger(maintenant):
        if appliquer:
            supprimer_fichier(ligne, "justificatif", champ_nom="justificatif_nom")
            _prevenir_destruction(ligne)
            _journaliser(
                None, ligne,
                f"Justificatif de « {ligne.qualification} » détruit faute de décision sous "
                f"{JOURS_AVANT_PURGE_NON_VALIDEE} jours.",
            )
        purgees.append(ligne)
    return purgees


def rappeler(maintenant=None, appliquer=True):
    """Prévient que la destruction approche. Renvoie les lignes concernées."""
    lignes = list(a_rappeler(maintenant))
    if appliquer:
        for ligne in lignes:
            _prevenir_echeance(ligne)
    return lignes


def _institution_de(utilisateur):
    from .models import ContactInstitution

    contact = (ContactInstitution.objects.filter(utilisateur=utilisateur, actif=True)
               .select_related("institution").first())
    return contact.institution if contact else None


def _prevenir_echeance(ligne):
    from .branding import send_branded_mail

    if not ligne.utilisateur.email:
        return
    # `request=None` : la purge tourne en tâche planifiée. `send_branded_mail` le supporte —
    # le message part par l'API de l'institution si elle en a une, sinon par le SMTP de la
    # plateforme, et reste journalisé dans les deux cas.
    send_branded_mail(
        None, _institution_de(ligne.utilisateur),
        subject=f"Votre pièce « {ligne.qualification} » n'a pas encore été relue",
        message=(
            "Bonjour,\n\n"
            f"Vous avez déposé un justificatif pour « {ligne.qualification} » et personne ne "
            f"l'a encore relu. Nous ne conservons pas indéfiniment un document que nous "
            f"n'avons pas instruit : il sera détruit dans {JOURS_AVANT_RAPPEL_PURGE} jours.\n\n"
            "Votre titre, lui, reste enregistré : seul le fichier disparaît, et vous pourrez "
            "en redéposer un.\n\n"
            "Nous avons également relancé votre encadrement.\n\n"
            "{signature}"
        ),
        recipient_list=[ligne.utilisateur.email],
    )


def _prevenir_destruction(ligne):
    from .branding import send_branded_mail

    if not ligne.utilisateur.email:
        return
    send_branded_mail(
        None, _institution_de(ligne.utilisateur),
        subject=f"Votre pièce « {ligne.qualification} » a été détruite",
        message=(
            "Bonjour,\n\n"
            f"Le justificatif que vous aviez déposé pour « {ligne.qualification} » vient "
            f"d'être détruit : il est resté {JOURS_AVANT_PURGE_NON_VALIDEE} jours sans être "
            "relu, et nous ne gardons pas un document que nous n'avons pas instruit.\n\n"
            "Ce n'est pas un refus, et votre titre reste enregistré avec ses dates. Vous "
            "pouvez redéposer une pièce depuis « Ma fiche bénévole », onglet « Mes "
            "justificatifs ».\n\n"
            "{signature}"
        ),
        recipient_list=[ligne.utilisateur.email],
    )
