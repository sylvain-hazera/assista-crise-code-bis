"""Choisir par où part un courriel : Brevo d'une institution, un de ses connecteurs SMTP, ou le
SMTP de la plateforme (22/11/2026).

Demande de Sylvain : « une proposition de choix de routage de sortie pour les mails :
connecteurs Brevo (et l'adresse utilisée), connecteurs SMTP (lequel si plusieurs, et l'adresse
utilisée) ». Utilisé par la campagne d'invitation des collectivités (le reste de la plateforme
garde le routage automatique de core/envoi_institution.py).

Un connecteur se désigne par une clé : `brevo:<institution>`, `smtp:<connecteur>`, `plateforme`.
**Pas de repli silencieux** : le choix est explicite, un échec est rendu (et noté sur le
connecteur), jamais rattrapé par un autre canal que la personne n'a pas choisi.
"""
import logging

from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

logger = logging.getLogger(__name__)


def _ligne(cle, type_, libelle, adresse, institution=None, succes=None, echec=None, motif=""):
    return {"cle": cle, "type": type_, "libelle": libelle, "adresse": adresse,
            "institution": institution.nom if institution else "", "dernier_succes": succes,
            "dernier_echec": echec, "dernier_echec_motif": motif}


def connecteurs_pour(institutions) -> list:
    """Les connecteurs utilisables pour envoyer au nom de ces institutions, le défaut en tête :
    Brevo s'il est prêt, puis les SMTP de l'institution, puis celui de la plateforme."""
    from .models import ConnecteurSMTP

    lignes = []
    for inst in [i for i in institutions if i is not None]:
        config = getattr(inst, "configuration_envoi", None)
        if config is not None and config.email_configure:
            lignes.append(_ligne(f"brevo:{inst.id}", "brevo", f"Brevo — {inst.nom}", config.brevo_expediteur_email, inst,
                                 config.dernier_envoi_email_le, None, config.derniere_erreur_email or ""))
        for c in ConnecteurSMTP.objects.filter(institution=inst, actif=True):
            lignes.append(_ligne(f"smtp:{c.id}", "smtp", f"SMTP — {c.nom} ({inst.nom})", c.expediteur_email, inst,
                                 c.dernier_succes, c.dernier_echec, c.dernier_echec_motif))
    lignes.append(_ligne("plateforme", "plateforme", "SMTP de la plateforme", settings.DEFAULT_FROM_EMAIL))
    return lignes


class EchecEnvoi(Exception):
    pass


def _smtp(connecteur, sujet, corps, destinataire, reply_to=None):
    connexion = get_connection(
        backend=settings.EMAIL_BACKEND, host=connecteur.hote, port=connecteur.port,
        username=connecteur.identifiant or None, password=connecteur.mot_de_passe or None,
        use_tls=connecteur.chiffrement == connecteur.Chiffrement.STARTTLS,
        use_ssl=connecteur.chiffrement == connecteur.Chiffrement.SSL, timeout=30, fail_silently=False)
    expediteur = (f"{connecteur.expediteur_nom} <{connecteur.expediteur_email}>"
                  if connecteur.expediteur_nom else connecteur.expediteur_email)
    EmailMessage(sujet, corps, expediteur, [destinataire], reply_to=[reply_to] if reply_to else None,
                 connection=connexion).send(fail_silently=False)


def envoyer(cle, sujet, corps, destinataire, reply_to=None, institutions_permises=None) -> str:
    """Envoie par le connecteur désigné. Rend un identifiant ou un libellé ; lève `EchecEnvoi`.
    `institutions_permises` : le connecteur doit appartenir à l'une d'elles (sauf la plateforme)."""
    from .envoi_brevo import EchecBrevo, envoyer_email_brevo
    from .models import ConnecteurSMTP, Institution

    permises = {str(i.id) for i in institutions_permises or [] if i is not None}
    if cle == "plateforme":
        try:
            EmailMessage(sujet, corps, settings.DEFAULT_FROM_EMAIL, [destinataire],
                         reply_to=[reply_to] if reply_to else None).send(fail_silently=False)
        except Exception as exc:  # noqa: BLE001
            raise EchecEnvoi(str(exc)[:300]) from exc
        return "plateforme"

    type_, _, ident = cle.partition(":")
    if type_ == "brevo":
        inst = Institution.objects.filter(pk=ident).select_related("configuration_envoi").first()
        config = getattr(inst, "configuration_envoi", None) if inst else None
        if inst is None or (permises and str(inst.id) not in permises) or config is None or not config.email_configure:
            raise EchecEnvoi("Connecteur Brevo indisponible.")
        try:
            identifiant = envoyer_email_brevo(
                cle_api=config.brevo_cle_api, expediteur_email=config.brevo_expediteur_email,
                expediteur_nom=config.brevo_expediteur_nom or inst.nom_affichage or inst.nom,
                sujet=sujet, message=corps, destinataires=[destinataire], reply_to=reply_to)
        except EchecBrevo as echec:
            from .envoi_institution import _noter_echec_email
            _noter_echec_email(config, echec.detail)
            raise EchecEnvoi(echec.detail) from echec
        from .envoi_institution import _noter_succes_email
        _noter_succes_email(config)
        return identifiant or "brevo"

    if type_ == "smtp":
        connecteur = ConnecteurSMTP.objects.filter(pk=ident, actif=True).first()
        if connecteur is None or (permises and str(connecteur.institution_id) not in permises):
            raise EchecEnvoi("Connecteur SMTP indisponible.")
        try:
            _smtp(connecteur, sujet, corps, destinataire, reply_to)
        except Exception as exc:  # noqa: BLE001
            connecteur.dernier_echec, connecteur.dernier_echec_motif = timezone.now(), str(exc)[:300]
            connecteur.save(update_fields=["dernier_echec", "dernier_echec_motif"])
            raise EchecEnvoi(str(exc)[:300]) from exc
        connecteur.dernier_succes = timezone.now()
        connecteur.save(update_fields=["dernier_succes"])
        return f"smtp:{connecteur.nom}"

    raise EchecEnvoi("Connecteur inconnu.")


def libelle(cle, institutions) -> str:
    return next((l["libelle"] + " — " + (l["adresse"] or "") for l in connecteurs_pour(institutions) if l["cle"] == cle), cle)
