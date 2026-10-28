"""Instruction d'une candidature à une association agréée de sécurité civile.

Le circuit tel que l'association le pratique : demande reçue, prise en charge par quelqu'un du
bureau, pièces et qualifications vérifiées, puis acceptée — ou refusée.

Deux principes qui expliquent la forme de ce module :

1. **Accepter fait TOUT d'un geste** : le compte est activé, le rattachement posé, l'accès à la
   démonstration ouvert, la personne ajoutée à l'équipe de l'association et son niveau
   opérationnel fixé à « Intervenant ». Demander au bureau de valider deux fois la même
   personne dans deux écrans différents produit des comptes acceptés mais non rattachés —
   observé en production le 27/10/2026, et c'est ce qui a coûté un utilisateur (voir
   DOCUMENTATION.md § 5.11, « deux réponses en base »).

2. **Rien n'est accordé par un lien.** Une invitation pose une candidature, elle n'ouvre aucun
   droit : quelqu'un qui devinerait un jeton obtiendrait une demande de plus à examiner, pas un
   accès. C'est le bureau qui décide, toujours.
"""
import logging

from django.db import transaction
from django.utils import timezone

from .audit import audit_log
from .models import (
    CandidatureAssociation, ContactInstitution, InvitationAssociation, UserRole,
)

logger = logging.getLogger(__name__)


def peut_instruire(utilisateur, institution):
    """Qui instruit les candidatures d'une association : son bureau, et les administrateurs.

    Être membre ne suffit pas — recruter est un acte de gouvernance. Et un administrateur de la
    plateforme le peut parce qu'il doit pouvoir débloquer une association dont le bureau a
    perdu ses accès, pas parce que c'est son rôle habituel."""
    if not getattr(utilisateur, "is_authenticated", False):
        return False
    if utilisateur.type == UserRole.ADMINISTRATOR:
        return True
    return ContactInstitution.objects.filter(
        institution=institution, utilisateur=utilisateur, membre_bureau=True, actif=True,
    ).exists()


def candidature_depuis_invitation(jeton, utilisateur, message=None):
    """Pose une candidature à partir d'un lien d'invitation. Rend (candidature, créée).

    Rend (None, False) si le jeton ne correspond à rien d'utilisable : expiré, désactivé, ou
    association retirée du service. Volontairement muet sur la raison côté appelant — un
    message qui distinguerait « jeton inconnu » de « jeton expiré » aiderait à en deviner."""
    invitation = InvitationAssociation.objects.filter(jeton=jeton).select_related(
        "institution").first()
    if invitation is None or not invitation.utilisable:
        return None, False
    return demander_a_rejoindre(
        invitation.institution, utilisateur, message=message, invitation=invitation)


def demander_a_rejoindre(institution, utilisateur, message=None, invitation=None):
    """Pose une candidature. Rend (candidature, créée).

    Idempotent par construction : une personne qui redemande alors que son dossier est en cours
    retrouve le même, elle n'en ouvre pas un second. Deux dossiers ouverts se feraient
    instruire deux fois, et accepter deux fois (voir la contrainte uq_candidature_en_cours).

    Un dossier déjà ACCEPTÉ est rendu tel quel : la personne est déjà membre. Un dossier REFUSÉ
    n'empêche pas d'en déposer un nouveau — un refus n'est pas une interdiction à vie."""
    en_cours = CandidatureAssociation.objects.filter(
        institution=institution, utilisateur=utilisateur,
    ).exclude(etape=CandidatureAssociation.Etape.REFUSE).first()
    if en_cours is not None:
        return en_cours, False

    candidature = CandidatureAssociation.objects.create(
        institution=institution, utilisateur=utilisateur,
        message_candidat=message or None, invitation=invitation,
        environment=getattr(institution, "environment", "PROD"),
    )
    return candidature, True


def prendre_en_charge(candidature, par, request=None):
    """Un membre du bureau se déclare responsable du dossier.

    Le nom est enregistré, et pas seulement l'étape : une candidature dont personne ne se sent
    responsable est une candidature qui dort."""
    _avancer(candidature, CandidatureAssociation.Etape.PRISE_EN_CHARGE, par, request)
    if candidature.pris_en_charge_par_id is None:
        candidature.pris_en_charge_par = par
    candidature.date_prise_en_charge = timezone.now()
    candidature.save(update_fields=["etape", "pris_en_charge_par", "date_prise_en_charge",
                                    "modifie_le"])
    return candidature


def marquer_verifiee(candidature, par, request=None):
    """Pièces et qualifications vérifiées. Ne vérifie rien lui-même : c'est une déclaration de
    l'instructeur, pas un contrôle automatique — nous ne savons pas ce qu'il a eu sous les yeux."""
    _avancer(candidature, CandidatureAssociation.Etape.VERIFICATION, par, request)
    candidature.save(update_fields=["etape", "modifie_le"])
    return candidature


@transaction.atomic
def accepter(candidature, par, request=None):
    """Accepte la candidature : active le compte ET pose le rattachement, d'un seul geste.

    L'ordre compte. Le compte est activé AVANT le rattachement, parce que
    `grant_institution_and_demo_access` ajoute la personne à l'équipe de l'association et lui
    envoie l'accès à la messagerie : inviter dans une équipe quelqu'un qui ne peut pas encore
    se connecter produit un email vers une porte fermée.

    Transaction : un rattachement à moitié posé est pire qu'une candidature non traitée, parce
    qu'il a l'air d'un succès."""
    from .institution_attachment import (
        _affecter_role, _get_or_create_contact_institution,
        grant_institution_and_demo_access,
    )

    _avancer(candidature, CandidatureAssociation.Etape.ACCEPTE, par, request)
    utilisateur = candidature.utilisateur
    institution = candidature.institution

    champs_compte = []
    if not utilisateur.enabled:
        utilisateur.enabled = True
        champs_compte.append("enabled")
    if not utilisateur.is_active:
        utilisateur.is_active = True
        champs_compte.append("is_active")
    if champs_compte:
        utilisateur.save(update_fields=champs_compte)

    contact, cree = _get_or_create_contact_institution(institution, utilisateur, "Membre")
    if cree:
        contact.date_adhesion = timezone.localdate()
        contact.save(update_fields=["date_adhesion"])

    grant_institution_and_demo_access(utilisateur, institution, request)
    # « Intervenant » : quelqu'un qu'on vient d'accepter n'est pas régulateur de crise. C'est au
    # bureau d'élever ce niveau quand la personne est formée.
    _affecter_role(utilisateur, institution, "INTERVENANT")

    candidature.pris_en_charge_par = candidature.pris_en_charge_par or par
    candidature.date_decision = timezone.now()
    candidature.save(update_fields=["etape", "pris_en_charge_par", "date_decision",
                                    "modifie_le"])

    if request is not None:
        audit_log(
            request=request, action_code="MODIFICATION",
            objet_type="CandidatureAssociation", objet_id=candidature.id,
            commentaire=f"Candidature acceptee : {utilisateur.email} rejoint "
                        f"{institution.nom} comme membre",
        )
    return candidature


def refuser(candidature, par, motif, request=None):
    """Refuse la candidature. Le motif est OBLIGATOIRE : un refus sans raison se represente à
    l'identique six mois plus tard, et personne ne sait pourquoi il avait été écarté."""
    motif = (motif or "").strip()
    if not motif:
        raise ValueError("Un refus doit indiquer son motif.")
    _avancer(candidature, CandidatureAssociation.Etape.REFUSE, par, request)
    candidature.motif_refus = motif
    candidature.pris_en_charge_par = candidature.pris_en_charge_par or par
    candidature.date_decision = timezone.now()
    candidature.save(update_fields=["etape", "motif_refus", "pris_en_charge_par",
                                    "date_decision", "modifie_le"])

    if request is not None:
        audit_log(
            request=request, action_code="MODIFICATION",
            objet_type="CandidatureAssociation", objet_id=candidature.id,
            commentaire=f"Candidature refusee : {candidature.utilisateur.email} pour "
                        f"{candidature.institution.nom}",
        )
    return candidature


def _avancer(candidature, vers, par, request=None):
    """Garde commune aux quatre gestes : qui agit, et le circuit avance-t-il ?

    Les deux refus lèvent `PermissionError` / `ValueError` plutôt que de rendre False : une
    transition refusée est une erreur de l'appelant, pas un cas de figure à ignorer — la rendre
    silencieuse laisserait croire au bureau que son clic a été pris en compte."""
    if not peut_instruire(par, candidature.institution):
        raise PermissionError(
            "Seul un membre du bureau de cette association peut instruire ses candidatures."
        )
    if not candidature.transition_possible(vers):
        raise ValueError(
            f"Passage de « {candidature.get_etape_display()} » à "
            f"« {CandidatureAssociation.Etape(vers).label} » impossible : le circuit avance, "
            f"il ne recule pas, et une décision prise ne se reprend pas."
        )
    candidature.etape = vers
