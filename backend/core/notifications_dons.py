"""Prévenir les bonnes personnes quand un appel aux dons avance (core/appels_dons.py).

Demande de Sylvain du 17/11/2026 : « fais le nécessaire pour les envois de courrier, avec la
personnalisation si nécessaire ; branche aussi les notifications via l'application ou Matrix ».

Quatre canaux, chacun pour ce qu'il sait faire :

- la **notification du site** (`Notification`), pour la personne concernée ;
- l'**application mobile** (`notifications_application.notifier`), si elle l'a sur son téléphone ;
- le **courriel**, par `send_branded_mail` : signature et adresse de l'institution qui écrit ;
- l'**équipe de l'institution destinataire** (ses contacts principaux, à défaut son bureau),
  par l'application et le site — c'était son salon Matrix avant l'arrêt de Matrix (24/11/2026).

On prévient des PERSONNES PRÉCISES (qui a lancé l'appel, qui s'est engagé), jamais tout un
annuaire : un appel qui écrit à cent personnes à chaque engagement, plus personne ne le lit.
Aucun canal ne fait échouer le geste qui l'a déclenché.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

LIEN = "/admin/appels-dons"


def _adresse() -> str:
    return f"{settings.SERVER_URL.rstrip('/')}{LIEN}"


def prevenir(*, de, vers, titre, corps, personnes=(), courriels=(), request=None, crise=None, environment=None) -> dict:
    """`de` : l'institution qui écrit (sa signature) ; `vers` : celle qu'on prévient (son salon).
    `personnes` : les comptes à notifier ; `courriels` : adresses en plus (le contact de l'appel).
    Rend ce qui est parti, canal par canal."""
    from .branding import send_branded_mail, send_branded_mail_env_aware
    from .models import Environment, GenreNotification, Notification
    from .notifications_application import notifier

    environment = environment or Environment.PROD
    personnes = [p for p in {p.pk: p for p in personnes if p is not None}.values()]
    bilan = {"site": 0, "application": 0, "courriels": 0, "equipe": 0}

    for personne in personnes:
        try:
            Notification.objects.create(utilisateur=personne, titre=titre[:200], message=corps, crise=crise, environment=environment)
            bilan["site"] += 1
            if notifier(personne, GenreNotification.INFORMATION, titre[:200], corps, institution=vers, environment=environment):
                bilan["application"] += 1
        except Exception as exc:
            logger.warning("Notification d'appel aux dons non déposée (%s).", type(exc).__name__)

    adresses = sorted({a.strip() for a in [*courriels, *(p.email for p in personnes)] if a and "@" in a})
    if adresses:
        message = f"{corps}\n\nPour suivre cet appel : {_adresse()}\n\n{{signature}}"
        try:
            if request is not None:
                send_branded_mail_env_aware(request, de, titre, message, adresses)
            elif environment == Environment.PROD:
                # Hors requête (rappel planifié) : jamais d'envoi réel depuis la zone de démonstration.
                send_branded_mail(None, de, titre, message, adresses)
            else:
                adresses = []
            bilan["courriels"] = len(adresses)
        except Exception as exc:
            logger.warning("Courriel d'appel aux dons non parti (%s).", type(exc).__name__)

    if vers is not None:
        from .notifications_application import prevenir

        deja = {p.pk for p in personnes}
        for membre in equipe_de(vers):
            if membre.pk not in deja:
                prevenir(membre, titre, corps, lien=LIEN, institution=vers, crise=crise, environment=environment)
                bilan["equipe"] += 1
    return bilan


def equipe_de(institution) -> list:
    """Qui prévenir dans une institution : ses contacts principaux, à défaut son bureau."""
    from .models import ContactInstitution

    contacts = list(ContactInstitution.objects.filter(institution=institution, actif=True, utilisateur__is_active=True)
                    .select_related("utilisateur"))
    choisis = [c for c in contacts if c.contact_principal] or [c for c in contacts if c.membre_bureau]
    return [c.utilisateur for c in choisis]


def contacts_de(appel) -> tuple[list, list]:
    """Qui prévenir chez l'institution qui a lancé l'appel : la personne qui l'a créé, et le
    courriel de contact qu'elle a publié."""
    return [appel.cree_par] if appel.cree_par_id else [], [appel.contact_email] if appel.contact_email else []


def prevenir_le_reseau(appel) -> dict:
    """Prévient les institutions du périmètre qu'un appel est ouvert (décision de Sylvain du
    17/11/2026 : « oui, il faut prévenir les autres institutions »).

    Dans chaque institution, on écrit à ses contacts principaux, à défaut à son bureau — pas à
    tous ses membres. Une institution n'est prévenue qu'UNE fois par
    appel : élargir le périmètre ne réécrit qu'aux nouvelles venues. Celles qu'on ne sait pas
    situer ne reçoivent rien d'un appel à portée limitée : elles le voient dans le réseau, mais
    on n'écrit pas à toute la France pour un appel lancé à cinquante kilomètres."""
    from . import appels_dons
    from .models import ContactInstitution, Institution, StatutAppelDons

    bilan = {"institutions": 0, "personnes": 0}
    if appel.statut != StatutAppelDons.OUVERT:
        return bilan
    deja = set(appel.institutions_prevenues or [])
    membres = ContactInstitution.objects.filter(actif=True).exclude(institution_id=appel.institution_id).select_related("utilisateur")
    par_institution: dict = {}
    for contact in membres:
        par_institution.setdefault(contact.institution_id, []).append(contact)
    lignes = appel.besoins.count()
    urgentes = sum(1 for b in appel.besoins.all() if b.quantite_urgente > b.quantite_recue)
    for institution in Institution.objects.filter(pk__in=[i for i in par_institution if str(i) not in deja]):
        distance = appels_dons.distance_a(appel, institution)
        if appel.portee_km is not None and (distance is None or distance > appel.portee_km):
            continue
        contacts = par_institution[institution.id]
        choisis = [c for c in contacts if c.contact_principal] or [c for c in contacts if c.membre_bureau]
        personnes = [c.utilisateur for c in choisis if c.utilisateur.is_active]
        prevenir(
            de=appel.institution, vers=institution, personnes=personnes, crise=appel.crise, environment=appel.environment,
            titre=f"Appel aux dons de {appel.institution.nom} : « {appel.titre} »",
            corps=f"{appel.institution.nom} lance un appel aux dons {appels_dons.libelle_portee(appel)}"
                  + (f", à {round(distance)} km de vous" if distance is not None else "") + ".\n"
                  + f"{lignes} ligne(s) précise(s), à la pièce et à la taille près" + (f", dont {urgentes} urgente(s)" if urgentes else "") + ".\n"
                  + (f"{appel.description}\n" if appel.description else "")
                  + "Engagez-vous seulement sur ce que vous pouvez fournir : chaque ligne se ferme dès qu'elle est couverte, "
                    "pour que personne ne collecte ce qui est déjà promis.")
        deja.add(str(institution.id))
        bilan["institutions"] += 1
        bilan["personnes"] += len(personnes)
    appel.institutions_prevenues = sorted(deja)
    appel.save(update_fields=["institutions_prevenues"])
    return bilan
