"""Suivi des crédits Brevo d'une institution, et alerte avant qu'ils ne manquent.

Demande de Sylvain du 12/11/2026 : remonter la consommation dans l'écran de l'institution,
avertir à l'approche de la limite, et prévenir l'administrateur du compte Brevo.

**Ce que l'API donne, et ce qu'elle ne donne pas.** `GET /v3/account` rend le nombre de crédits
RESTANTS et la fin de la période — pas le quota souscrit. On garde donc le plus haut niveau vu
sur la période (`*_reference`) pour dessiner une jauge, et l'alerte se règle en nombre de
crédits restants, pas en pourcentage : « il reste 500 emails » se comprend sans calcul, et
c'est le chiffre qui dit si l'on peut encore écrire à tous ses bénévoles.

**L'alerte ne passe JAMAIS par Brevo.** Elle part par le SMTP de la plateforme. Prévenir que le
compte Brevo est à sec en utilisant le compte Brevo, c'est scier la branche : le message qui
compte le plus serait le premier à ne pas partir.

**Une alerte par niveau et par période**, pas une par envoi. Sous le seuil, chaque email
envoyé retrouverait le compte « bas » ; sans mémoire, l'administrateur recevrait cent messages
et apprendrait à les ignorer. On prévient une fois à l'approche (`BAS`), une fois à
l'épuisement (`EPUISE`), et on repart de zéro quand les crédits remontent.

**Le relevé est espacé** (`INTERVALLE_RELEVE`) : un appel à Brevo par email envoyé doublerait
le trafic vers leur API pour une information qui change lentement.
"""
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

#: Délai minimal entre deux relevés automatiques. Le bouton « Actualiser » de l'écran passe
#: outre : quelqu'un qui regarde veut le chiffre du moment.
INTERVALLE_RELEVE = 30 * 60

NIVEAU_OK, NIVEAU_BAS, NIVEAU_EPUISE = "", "BAS", "EPUISE"


def niveau(restant, seuil):
    """Où en est un compteur : épuisé, bas, ou rien à signaler. `None` = inconnu, donc rien."""
    if restant is None:
        return NIVEAU_OK
    if restant <= 0:
        return NIVEAU_EPUISE
    return NIVEAU_BAS if restant <= seuil else NIVEAU_OK


def etat(config):
    """Ce que l'écran affiche : les deux compteurs, leur niveau, et la jauge quand on l'a."""
    def compteur(restant, seuil, reference=None):
        return {
            "restant": restant,
            "seuil": seuil,
            "niveau": niveau(restant, seuil),
            # Part restante sur le plus haut niveau vu : None tant qu'on n'a qu'un relevé.
            "part": (round(100 * restant / reference)
                     if restant is not None and reference else None),
        }

    return {
        "releve_le": config.brevo_credits_releves_le,
        "fin_periode": config.brevo_periode_fin,
        "email": compteur(config.brevo_credits_email, config.brevo_seuil_alerte_email,
                          config.brevo_credits_email_reference),
        "sms": compteur(config.brevo_credits_sms, config.brevo_seuil_alerte_sms),
    }


def relever(config, force=False, request=None):
    """Lit les crédits chez Brevo, les enregistre, et alerte si un seuil est franchi.

    Ne lève jamais : ce relevé accompagne un envoi ou l'ouverture d'un écran, et son échec ne
    doit faire échouer ni l'un ni l'autre. Rend True si un relevé a réellement eu lieu."""
    from .envoi_brevo import EchecBrevo, lire_credits_brevo

    if not config.brevo_cle_api:
        return False
    if not force and config.brevo_credits_releves_le is not None and (
            timezone.now() - config.brevo_credits_releves_le).total_seconds() < INTERVALLE_RELEVE:
        return False

    try:
        credits = lire_credits_brevo(config.brevo_cle_api)
    except EchecBrevo as echec:
        logger.warning("Relevé des crédits Brevo impossible pour « %s » : %s",
                       config.institution.nom, echec.detail)
        return False

    fin = credits.get("fin_periode")
    try:
        from datetime import date
        fin = date.fromisoformat(fin) if fin else None
    except (TypeError, ValueError):
        fin = None

    # Nouvelle période, ou crédits rechargés : la référence repart du niveau observé.
    nouvelle_periode = fin != config.brevo_periode_fin
    email = credits.get("email")
    reference = config.brevo_credits_email_reference
    if email is not None and (nouvelle_periode or reference is None or email > reference):
        reference = email

    config.brevo_credits_email = email
    config.brevo_credits_email_reference = reference
    config.brevo_credits_sms = credits.get("sms")
    config.brevo_periode_fin = fin
    config.brevo_credits_releves_le = timezone.now()
    config.save(update_fields=[
        "brevo_credits_email", "brevo_credits_email_reference", "brevo_credits_sms",
        "brevo_periode_fin", "brevo_credits_releves_le", "date_modification"])

    _alerter_si_besoin(config, request)
    return True


def _alerter_si_besoin(config, request):
    """Prévient l'administrateur Brevo, une fois par niveau franchi."""
    etat_courant = etat(config)
    niveaux = [etat_courant["email"]["niveau"]]
    # Les SMS ne comptent que si l'institution s'en sert par Brevo : un compte sans crédits
    # SMS qui n'envoie pas de SMS n'a rien d'alarmant.
    if config.fournisseur_sms == "BREVO":
        niveaux.append(etat_courant["sms"]["niveau"])
    pire = NIVEAU_EPUISE if NIVEAU_EPUISE in niveaux else (
        NIVEAU_BAS if NIVEAU_BAS in niveaux else NIVEAU_OK)

    if pire == NIVEAU_OK:
        # Les crédits sont remontés : on oublie l'alerte, pour pouvoir prévenir de nouveau
        # la prochaine fois.
        if config.brevo_alerte_niveau:
            config.brevo_alerte_niveau = ""
            config.save(update_fields=["brevo_alerte_niveau", "date_modification"])
        return
    # Déjà prévenu à ce niveau (ou à un niveau plus grave) : on se tait.
    if config.brevo_alerte_niveau == pire or config.brevo_alerte_niveau == NIVEAU_EPUISE:
        return

    _envoyer_alerte(config, pire, etat_courant, request)
    config.brevo_alerte_niveau = pire
    config.brevo_alerte_envoyee_le = timezone.now()
    config.save(update_fields=["brevo_alerte_niveau", "brevo_alerte_envoyee_le",
                               "date_modification"])


def _envoyer_alerte(config, pire, etat_courant, request):
    """Email à l'administrateur Brevo (par le SMTP de la plateforme) et notification au bureau."""
    from django.core.mail import send_mail

    from .models import ContactInstitution, Notification

    institution = config.institution
    nom = institution.nom_affichage or institution.nom
    email, sms = etat_courant["email"], etat_courant["sms"]

    lignes = []
    if email["niveau"]:
        lignes.append(f"Emails : {email['restant']} crédit(s) restant(s) "
                      f"(seuil d'alerte : {email['seuil']}).")
    if config.fournisseur_sms == "BREVO" and sms["niveau"]:
        lignes.append(f"SMS : {sms['restant']} crédit(s) restant(s) "
                      f"(seuil d'alerte : {sms['seuil']}).")
    fin = (f"La période en cours se termine le "
           f"{config.brevo_periode_fin.strftime('%d/%m/%Y')}."
           if config.brevo_periode_fin else "")

    if pire == NIVEAU_EPUISE:
        titre = f"Crédits Brevo épuisés — {nom}"
        consequence = ("Les messages ne partent plus par votre compte Brevo. Tant que ce "
                       "sera le cas, les emails sont expédiés par l'adresse de secours de la "
                       "plateforme, et les SMS ne partent pas.")
    else:
        titre = f"Crédits Brevo bientôt épuisés — {nom}"
        consequence = ("Vos messages partent encore normalement. Pensez à recharger le "
                       "compte avant un envoi en nombre.")

    corps = (
        "Bonjour,\n\n"
        f"Vous êtes désigné comme administrateur du compte Brevo de {nom}.\n\n"
        + "\n".join(lignes) + "\n"
        + (fin + "\n" if fin else "")
        + f"\n{consequence}\n\n"
        "Vous pouvez recharger ou modifier votre formule depuis votre espace Brevo. Le seuil "
        "d'alerte se règle dans la fiche de votre institution, onglet « Envois ».\n\n"
        "Ce message vous est envoyé une seule fois par niveau d'alerte.\n"
    )

    if config.brevo_admin_email:
        try:
            # SMTP de la plateforme, JAMAIS Brevo : voir la docstring du module.
            send_mail(titre, corps, None, [config.brevo_admin_email], fail_silently=True)
        except Exception:  # noqa: BLE001
            logger.exception("Alerte de crédits Brevo non envoyée pour « %s ».", nom)

    details = [{"libelle": "Institution", "valeur": nom}]
    if email["restant"] is not None:
        details.append({"libelle": "Emails restants", "valeur": str(email["restant"])})
    if config.fournisseur_sms == "BREVO":
        details.append({"libelle": "SMS restants", "valeur": str(sms["restant"] or 0)})
    if config.brevo_periode_fin:
        details.append({"libelle": "Fin de la période",
                        "valeur": config.brevo_periode_fin.strftime("%d/%m/%Y")})
    details.append({"libelle": "Ce que cela change", "valeur": consequence})

    # Le bureau le voit aussi dans l'application : l'administrateur du compte n'est pas
    # toujours celui qui envoie, et c'est celui qui envoie qui tombera sur le problème.
    for contact in ContactInstitution.objects.filter(
            institution=institution, membre_bureau=True, actif=True):
        Notification.objects.create(
            utilisateur_id=contact.utilisateur_id, titre=titre, message=consequence,
            details=details, lien="/admin/institutions", lien_libelle="Ouvrir les institutions",
            environment=config.environment,
        )
