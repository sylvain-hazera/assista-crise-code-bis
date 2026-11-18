"""Clôturer une crise en deux temps, et remettre à chacun son rapport avant qu'il soit trop tard.

**Pourquoi deux temps.** Clôturer une crise ferme la porte : plus rien ne s'y ajoute, et les
données des habitants ont vocation à disparaître ensuite. Or c'est justement après la crise que
les gens montent leur dossier d'assurance. La clôture se **propose** donc d'abord ; elle
n'intervient que `DELAI_JOURS` jours plus tard, le temps que chacun récupère ce qui le concerne.

**Ce que fait la proposition.** Elle écrit à ceux qui ont **bénéficié** d'un dossier (la
personne qui avait fait la demande) et à ceux qui y ont **participé** : la crise sera close à
telle date, et un lien personnel leur permet de recevoir par courriel le rapport de leur
dossier. Aux propriétaires des biens sinistrés dont on a l'adresse, le rapport de leur bien.

**Le lien, pas la pièce jointe d'office.** On n'envoie pas d'emblée un PDF nominatif à une
adresse relevée il y a des semaines : la personne le demande en suivant son lien, et il part à
l'adresse déjà connue, jamais à une autre. Le lien est personnel, à usage limité
(`ENVOIS_MAX_PAR_JOUR`), et meurt avec la clôture.

**Les rapports sont gardés jusqu'à la clôture**, chiffrés (`RapportConserve`, même stockage que
les autres fichiers sensibles : rien en clair sur le disque). On garde la dernière édition de
chacun. À la clôture effective, rapports et liens sont effacés.

**Les crises d'essai** ne se proposent pas à la clôture : elles servent à s'exercer, on n'écrit
pas aux habitants pour un exercice, et aucune tâche ne doit les clore d'elle-même.

La clôture à l'échéance est faite par `manage.py cloturer_crises_proposees`, à planifier.
"""
import datetime
import hashlib
import logging
import secrets

from .crypto_fields import empreinte_jeton
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from . import rapports_pdf
from .models import BienSinistre, DemandeRapport, Dossier, Information, Offer, RapportConserve, Request

logger = logging.getLogger(__name__)

DELAI_JOURS = 7
ENVOIS_MAX_PAR_JOUR = 3


class ClotureImpossible(ValueError):
    """La proposition ou la remise est refusée ; le message est pour la personne."""


def _nommer(utilisateur) -> str:
    if utilisateur is None:
        return ""
    return f"{utilisateur.first_name or ''} {utilisateur.last_name or ''}".strip() or utilisateur.username


# ───────────────────────────── rapports gardés jusqu'à la clôture ─────────────────────────────

def conserver(nature: str, objet_id, pdf: bytes, *, crise=None, institution=None, edite_par=None,
              toutes_les_photos: bool = False, environment=None) -> RapportConserve:
    """Garde le rapport, chiffré, à la place de l'édition précédente du même rapport."""
    environment = environment or (crise.environment if crise is not None else None)
    champs = {"nature": nature, "objet_id": objet_id, "institution": institution, "toutes_les_photos": toutes_les_photos}
    for ancien in RapportConserve.objects.filter(**champs):
        ancien.effacer()
    rapport = RapportConserve(crise=crise, edite_par=edite_par, sha256=hashlib.sha256(pdf).hexdigest(),
                              taille=len(pdf), **champs)
    if environment:
        rapport.environment = environment
    rapport.fichier.save(f"{nature}-{secrets.token_hex(8)}.pdf", ContentFile(pdf), save=True)
    return rapport


def effacer_les_rapports(crise) -> int:
    """À la clôture : plus aucun rapport ni lien de cette crise sur le serveur."""
    nombre = 0
    for rapport in RapportConserve.objects.filter(crise=crise):
        rapport.effacer()
        nombre += 1
    DemandeRapport.objects.filter(crise=crise).delete()
    return nombre


# ─────────────────────────────────── proposition de clôture ───────────────────────────────────

def destinataires(crise) -> dict:
    """`{adresse: [(nature, objet, libellé, rôle)]}` : qui recevra quoi. Une adresse en double
    (demandeur d'un dossier et participant d'un autre) ne reçoit qu'un courriel."""
    par_adresse = {}

    def ajouter(adresse, nature, objet, libelle, role):
        adresse = (adresse or "").strip().lower()
        if "@" not in adresse or adresse.endswith(".local"):      # comptes de service, adresses internes
            return
        lignes = par_adresse.setdefault(adresse, [])
        if not any(n == nature and o.pk == objet.pk for n, o, _l, _r in lignes):
            lignes.append((nature, objet, libelle, role))

    dossiers = (Dossier.objects.filter(crise=crise, environment=crise.environment)
                .select_related("demande").prefetch_related("participants__utilisateur"))
    for dossier in dossiers:
        libelle = f"Dossier {dossier.numero} — {dossier.titre}"
        if dossier.demande is not None:
            ajouter(dossier.demande.email_request, "dossier", dossier, libelle, "BENEFICIAIRE")
        for participant in dossier.participants.all():
            if participant.utilisateur_id and participant.utilisateur.is_active:
                ajouter(participant.utilisateur.email, "dossier", dossier, libelle, "PARTICIPANT")
    for bien in BienSinistre.objects.filter(crise=crise, environment=crise.environment):
        ajouter(bien.proprietaire_email, "bien", bien, f"{bien.get_type_bien_display()} — {bien.designation}", "PROPRIETAIRE")
    return par_adresse


def lien_de(demande) -> str:
    return f"{settings.SERVER_URL.rstrip('/')}/rapport/{demande.jeton}"


def _courriel(crise, lignes, liens) -> str:
    echeance = timezone.localtime(crise.fermeture_prevue_le).strftime("%d/%m/%Y")
    objets = "\n".join(f"- {libelle}\n  {lien}" for (_n, _o, libelle, _r), lien in zip(lignes, liens))
    return (
        "Bonjour,\n\n"
        f"La gestion de la crise « {crise.name} » touche à sa fin : elle sera close le {echeance}.\n\n"
        "Vous avez été concerné par ce qui suit. Pour chacun, vous pouvez recevoir par courriel un rapport en PDF "
        "(ce qui a été demandé, ce qui a été constaté et fait, les photos) : il peut vous servir pour votre assurance.\n\n"
        f"{objets}\n\n"
        "Il suffit d'ouvrir le lien : le rapport est envoyé à cette adresse, et à elle seule. "
        f"Ces liens cessent de fonctionner à la clôture, le {echeance} : passé cette date, le rapport ne sera plus disponible.\n\n"
        "Si vous n'êtes pas concerné, ignorez ce message.\n\n"
        "{signature}"
    )


def proposer(crise, request, institution=None) -> dict:
    """Propose la clôture : fixe l'échéance, prépare un lien par personne et par rapport, écrit."""
    from .branding import send_branded_mail_env_aware

    if crise.end_date is not None:
        raise ClotureImpossible("Cette crise est déjà clôturée.")
    if crise.essai:
        raise ClotureImpossible("Une crise d'essai ne se propose pas à la clôture : on n'écrit pas aux habitants pour un "
                                "exercice, et elle ne doit pas se clore d'elle-même.")
    if crise.fermeture_proposee_le is not None:
        raise ClotureImpossible("La clôture de cette crise est déjà proposée.")

    maintenant = timezone.now()
    crise.fermeture_proposee_le = maintenant
    crise.fermeture_proposee_par = request.user
    crise.fermeture_prevue_le = maintenant + datetime.timedelta(days=DELAI_JOURS)
    crise.save(update_fields=["fermeture_proposee_le", "fermeture_proposee_par", "fermeture_prevue_le"])

    ecrits = echecs = liens_crees = 0
    for adresse, lignes in destinataires(crise).items():
        liens = []
        for nature, objet, _libelle, role in lignes:
            demande = DemandeRapport.objects.create(
                crise=crise, environment=crise.environment, nature=nature, objet_id=objet.pk, email=adresse, role=role,
                jeton=secrets.token_urlsafe(32))
            liens.append(lien_de(demande))
            liens_crees += 1
        try:
            send_branded_mail_env_aware(
                request, institution, f"Clôture de « {crise.name} » : recevez votre rapport", _courriel(crise, lignes, liens),
                [adresse], fail_silently=False)
            ecrits += 1
        except Exception as exc:       # une adresse en échec ne doit pas empêcher d'écrire aux autres
            logger.warning("Proposition de clôture : courriel non parti (%s).", type(exc).__name__)
            echecs += 1
    return {"personnes_prevenues": ecrits, "courriels_en_echec": echecs, "liens": liens_crees,
            "fermeture_prevue_le": crise.fermeture_prevue_le}


def annuler(crise) -> None:
    """Retire la proposition : la crise continue. Les liens déjà envoyés restent valables tant
    qu'elle est ouverte ; une nouvelle proposition en enverra de nouveaux."""
    if crise.end_date is not None:
        raise ClotureImpossible("Cette crise est déjà clôturée.")
    if crise.fermeture_proposee_le is None:
        raise ClotureImpossible("Aucune clôture n'est proposée pour cette crise.")
    crise.fermeture_proposee_le = crise.fermeture_proposee_par = crise.fermeture_prevue_le = None
    crise.save(update_fields=["fermeture_proposee_le", "fermeture_proposee_par", "fermeture_prevue_le"])


def cloturer(crise) -> dict:
    """La clôture elle-même, la même qu'on la décide sur l'instant ou qu'elle arrive à échéance :
    date de fin, purge des demandes, offres et signalements déjà désactivés, effacement des
    rapports gardés et des liens. Ne notifie ni ne journalise : c'est à l'appelant."""
    crise.end_date = timezone.now()
    crise.save(update_fields=["end_date"])
    Offer.objects.filter(crisis=crise, actif=False).delete()
    Request.objects.filter(crisis=crise, actif=False).delete()
    Information.objects.filter(crisis=crise, actif=False).delete()
    return {"rapports_effaces": effacer_les_rapports(crise)}


def a_cloturer(maintenant=None):
    """Les crises dont l'échéance de clôture est passée. Jamais une crise d'essai."""
    from .models import Crisis

    return Crisis.objects.filter(end_date__isnull=True, essai=False, fermeture_prevue_le__isnull=False,
                                 fermeture_prevue_le__lte=maintenant or timezone.now())


# ─────────────────────────────── remise du rapport par courriel ───────────────────────────────

def masquer(adresse: str) -> str:
    """« j•••••@exemple.fr » : assez pour reconnaître la sienne, pas pour l'apprendre."""
    nom, _, domaine = adresse.partition("@")
    return f"{nom[:1]}{'•' * max(3, len(nom) - 1)}@{domaine}"


def _objet_de(demande):
    modele = {"dossier": Dossier, "bien": BienSinistre}[demande.nature]
    return modele.objects.filter(pk=demande.objet_id).first()


def decrire(jeton: str) -> dict:
    """Ce que la page du lien affiche avant l'envoi. Lève `ClotureImpossible` si le lien est mort."""
    demande = DemandeRapport.objects.filter(jeton_empreinte=empreinte_jeton(jeton)).select_related("crise").first()
    if demande is None or demande.crise.end_date is not None:
        raise ClotureImpossible("Ce lien n'est plus valable : la crise est close, ou le lien n'existe pas.")
    objet = _objet_de(demande)
    if objet is None:
        raise ClotureImpossible("Ce rapport n'est plus disponible.")
    libelle = f"Dossier {objet.numero} — {objet.titre}" if demande.nature == "dossier" else f"{objet.get_type_bien_display()} — {objet.designation}"
    return {"rapport": libelle, "crise": demande.crise.name, "adresse": masquer(demande.email),
            "disponible_jusqu_au": demande.crise.fermeture_prevue_le, "deja_envoye": demande.nb_envois > 0}


def remettre(jeton: str, request) -> dict:
    """Envoie le rapport en pièce jointe à l'adresse du lien — jamais à une autre."""
    from .audit import send_mail_with_attachment_logged

    description = decrire(jeton)
    demande = DemandeRapport.objects.select_related("crise").get(jeton_empreinte=empreinte_jeton(jeton))
    aujourd_hui = timezone.localdate()
    if demande.dernier_envoi and timezone.localtime(demande.dernier_envoi).date() == aujourd_hui \
            and demande.envois_du_jour >= ENVOIS_MAX_PAR_JOUR:
        raise ClotureImpossible("Ce rapport a déjà été envoyé plusieurs fois aujourd'hui. Regardez dans vos courriers "
                                "indésirables, ou réessayez demain.")
    objet = _objet_de(demande)
    if demande.nature == "dossier":
        resume = rapports_pdf.dossier_resume(objet, _nommer)
        nom = f"rapport-dossier-{objet.numero}.pdf"
    else:
        resume = rapports_pdf.bien_resume(objet, _nommer)
        nom = "rapport-bien-sinistre.pdf"
    pdf = rapports_pdf.generer(demande.nature, resume, edite_par="la personne concernée (lien reçu par courriel)")
    conserver(demande.nature, objet.pk, pdf, crise=demande.crise)
    send_mail_with_attachment_logged(
        request, f"Votre rapport — {description['rapport']}",
        "Bonjour,\n\nVous trouverez en pièce jointe le rapport que vous avez demandé.\n\n"
        "Conservez-le : il ne sera plus disponible après la clôture de la crise.\n",
        None, [demande.email], nom, pdf, "application/pdf")
    memes_jour = demande.dernier_envoi and timezone.localtime(demande.dernier_envoi).date() == aujourd_hui
    demande.envois_du_jour = (demande.envois_du_jour + 1) if memes_jour else 1
    demande.nb_envois += 1
    demande.dernier_envoi = timezone.now()
    demande.save(update_fields=["envois_du_jour", "nb_envois", "dernier_envoi"])
    return {**description, "envoye": True, "deja_envoye": True}
