"""Mise à jour des satellites depuis le central.

Demande de Sylvain du 14/11/2026. Trois choses, dans l'ordre où on les a construites :

1. **Voir** — chaque satellite est-il à jour ? La référence est la dernière version SIGNÉE
   publiée : le central ne connaît pas son propre commit (son image n'embarque pas git), et
   surtout « à jour » doit vouloir dire « sur la dernière version que le responsable a
   déclarée bonne pour les satellites », pas « sur le dernier commit poussé ».
2. **Ordonner** — un ordre attend que le satellite vienne le chercher ; le satellite rapporte
   chaque étape, et le résultat.
3. **Ne faire confiance qu'à la signature** — voir `signature_satellites.py`.

**Rien n'est automatique.** Une mise à jour arrête le site local d'un satellite complet le
temps de reconstruire : la décision est prise par quelqu'un, satellite par satellite, et elle
est refusée par défaut pendant une crise.
"""
import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

#: Un ordre que le satellite n'est pas venu chercher expire : au-delà, plus personne ne se
#: souvient de l'avoir donné, et le voir s'exécuter des semaines après serait une surprise.
EXPIRATION_ORDRE = datetime.timedelta(days=7)
#: Une mise à jour commencée dont on n'a plus de nouvelles est tenue pour échouée. Large : la
#: construction du site sur un Raspberry Pi se compte en dizaines de minutes.
SILENCE_MAX_EN_COURS = datetime.timedelta(hours=6)
#: Au-delà, l'agent est considéré comme absent (il passe toutes les deux minutes).
AGENT_PRESENT_DEPUIS = datetime.timedelta(hours=24)
#: Le journal gardé par ordre. On garde la FIN : c'est là qu'est l'erreur.
TAILLE_MAX_JOURNAL = 40_000


class MiseAJourRefusee(Exception):
    """L'ordre ne peut pas être donné. `code` permet à l'écran de réagir (confirmation de
    crise), `message` est lisible tel quel."""

    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def version_de_reference():
    """La dernière version publiée et non retirée, ou `None`."""
    from .models import VersionSatellite

    return VersionSatellite.objects.filter(retiree=False).first()


def _commit_rapporte(version):
    """Le commit dans ce que le satellite rapporte.

    Les satellites installés avant le 14/11/2026 envoient `git describe --always` : un
    préfixe court, ou « v1.2-3-gabc1234 » s'il existe des étiquettes. Les nouveaux envoient le
    commit complet."""
    version = (version or "").strip().lower()
    if "-g" in version:
        version = version.rsplit("-g", 1)[1]
    return version


def meme_version(rapportee, commit):
    """Vrai si ce que rapporte le satellite désigne ce commit (préfixe d'au moins 7)."""
    rapportee = _commit_rapporte(rapportee)
    return len(rapportee) >= 7 and commit.startswith(rapportee)


def etat_version(satellite, reference=None):
    """`A_JOUR`, `EN_RETARD`, `INCONNUE`, ou `None` s'il n'y a aucune version publiée.

    `EN_RETARD` veut dire « pas sur la version de référence » : un satellite qu'on aurait mis
    en avance à la main y est aussi, et c'est juste — il n'est pas sur une version signée."""
    reference = reference or version_de_reference()
    if reference is None:
        return None
    if not _commit_rapporte(satellite.version_logicielle) \
            or satellite.version_logicielle == "inconnue":
        return "INCONNUE"
    return "A_JOUR" if meme_version(satellite.version_logicielle, reference.commit) \
        else "EN_RETARD"


def agent_present(satellite):
    """L'agent de mise à jour de ce satellite s'est-il manifesté récemment ?"""
    vu = satellite.agent_mise_a_jour_vu
    return bool(vu and timezone.now() - vu <= AGENT_PRESENT_DEPUIS)


def crises_en_cours(institution):
    """Les crises ouvertes où cette institution est engagée, hors crises d'essai.

    Une crise d'essai ne bloque pas : elle sert justement à essayer, y compris une mise à jour.
    """
    from .models import Crisis, Environment

    return list(Crisis.objects.filter(
        environment=Environment.PROD, end_date__isnull=True, essai=False,
        implications__institution=institution, implications__actif=True,
    ).distinct().values_list("name", flat=True))


def rafraichir(satellite):
    """Fait vieillir les ordres ouverts de ce satellite : expiration, silence trop long.

    Fait à la lecture plutôt que par une tâche planifiée : l'état n'a d'importance que
    lorsque quelqu'un — ou l'agent — le regarde."""
    from .models import MiseAJourSatellite, StatutMiseAJour

    maintenant = timezone.now()
    MiseAJourSatellite.objects.filter(
        satellite=satellite, statut=StatutMiseAJour.DEMANDEE,
        date_demande__lt=maintenant - EXPIRATION_ORDRE,
    ).update(
        statut=StatutMiseAJour.EXPIREE, date_fin=maintenant,
        etape="Le satellite n'est pas venu chercher cet ordre.",
    )
    MiseAJourSatellite.objects.filter(
        satellite=satellite, statut=StatutMiseAJour.EN_COURS,
        date_debut__lt=maintenant - SILENCE_MAX_EN_COURS,
    ).update(
        statut=StatutMiseAJour.ECHOUEE, date_fin=maintenant,
        etape="Plus de nouvelles du satellite depuis le début de la mise à jour.",
    )


def ordre_ouvert(satellite):
    from .models import MiseAJourSatellite, StatutMiseAJour

    rafraichir(satellite)
    return MiseAJourSatellite.objects.filter(
        satellite=satellite,
        statut__in=[StatutMiseAJour.DEMANDEE, StatutMiseAJour.EN_COURS],
    ).select_related("version").first()


def demander(satellite, utilisateur, version=None, malgre_crise=False):
    """Enregistre un ordre de mise à jour. Lève `MiseAJourRefusee` avec la raison.

    Les refus, dans l'ordre : satellite non validé, pas d'agent, aucune version publiée,
    version retirée, déjà à jour, ordre déjà ouvert, crise en cours non confirmée."""
    from .models import MiseAJourSatellite, StatutEnrolementSatellite

    if satellite.statut_enrolement != StatutEnrolementSatellite.APPROUVE:
        raise MiseAJourRefusee("NON_VALIDE", "Ce satellite n'est pas validé.")
    if not agent_present(satellite):
        raise MiseAJourRefusee(
            "SANS_AGENT",
            "Ce satellite n'a pas d'agent de mise à jour en service. Sur place, une dernière "
            "fois : ./installer.sh mettre-a-jour — c'est elle qui l'installe.")
    version = version or version_de_reference()
    if version is None:
        raise MiseAJourRefusee("AUCUNE_VERSION", "Aucune version signée n'est publiée.")
    if version.retiree:
        raise MiseAJourRefusee("VERSION_RETIREE", "Cette version a été retirée.")
    if meme_version(satellite.version_logicielle, version.commit):
        raise MiseAJourRefusee("DEJA_A_JOUR", "Ce satellite est déjà sur cette version.")
    if ordre_ouvert(satellite) is not None:
        raise MiseAJourRefusee(
            "DEJA_DEMANDEE", "Une mise à jour est déjà demandée ou en cours sur ce satellite.")

    crises = crises_en_cours(satellite.institution)
    if crises and not malgre_crise:
        raise MiseAJourRefusee(
            "CRISE_EN_COURS",
            "Une crise est en cours pour cette institution : la mise à jour rend le satellite "
            "indisponible le temps de reconstruire. Confirmez pour la lancer quand même.",
            crises=crises)

    try:
        with transaction.atomic():
            return MiseAJourSatellite.objects.create(
                satellite=satellite, version=version, demandee_par=utilisateur,
                version_avant=satellite.version_logicielle or "",
                malgre_crise=bool(crises),
            )
    except IntegrityError:
        # Deux clics simultanés : la contrainte a tranché, on le dit comme le cas ordinaire.
        raise MiseAJourRefusee(
            "DEJA_DEMANDEE",
            "Une mise à jour est déjà demandée ou en cours sur ce satellite.") from None


def demander_action(satellite, utilisateur, action):
    """Demande à l'agent l'un des ordres de la liste fermée `ActionSatellite` (17/11/2026) :
    regarder (diagnostic, journaux, migrations, machine, réseau, dépôt) ou agir (redémarrer,
    migrer, reconstruire, libérer de la place, sauvegarder).

    Pas de version, pas de signature : ces ordres ne font entrer aucun code, et l'agent refuse
    tout mot qu'il ne connaît pas. Pas de refus pendant une crise non plus — c'est précisément
    là qu'on a besoin de savoir pourquoi un satellite ne répond plus."""
    from .models import ActionSatellite, MiseAJourSatellite, StatutEnrolementSatellite

    if action not in ActionSatellite.values or action == ActionSatellite.MISE_A_JOUR:
        raise MiseAJourRefusee("ACTION_INCONNUE", "Action inconnue.")
    if satellite.statut_enrolement != StatutEnrolementSatellite.APPROUVE:
        raise MiseAJourRefusee("NON_VALIDE", "Ce satellite n'est pas validé.")
    if not agent_present(satellite):
        raise MiseAJourRefusee(
            "SANS_AGENT", "Ce satellite n'a pas d'agent en service : rien ne peut lui être demandé d'ici.")
    if action not in (satellite.actions_agent or []):
        # Un agent ancien prendrait ce mot pour une mise à jour sans numéro de version et
        # répondrait « numéro de version invalide » : on le dit ici, clairement.
        raise MiseAJourRefusee(
            "AGENT_TROP_ANCIEN",
            "L'agent de ce satellite ne connaît pas encore cet ordre : mettez d'abord le "
            "satellite à jour. Son agent se met à jour avec le code, même si le redémarrage "
            "échoue.")
    if ordre_ouvert(satellite) is not None:
        raise MiseAJourRefusee(
            "DEJA_DEMANDEE", "Un ordre est déjà demandé ou en cours sur ce satellite.")
    try:
        with transaction.atomic():
            return MiseAJourSatellite.objects.create(
                satellite=satellite, action=action, demandee_par=utilisateur,
                version_avant=satellite.version_logicielle or "",
            )
    except IntegrityError:
        raise MiseAJourRefusee(
            "DEJA_DEMANDEE", "Un ordre est déjà demandé ou en cours sur ce satellite.") from None


def annuler(satellite):
    """Annule un ordre que le satellite n'a pas encore pris. Renvoie l'ordre, ou lève.

    Une mise à jour COMMENCÉE ne s'annule pas : le satellite est au milieu d'une
    reconstruction, et l'arrêter là le laisserait dans un état que personne n'a prévu."""
    from .models import StatutMiseAJour

    ordre = ordre_ouvert(satellite)
    if ordre is None:
        raise MiseAJourRefusee("AUCUN_ORDRE", "Aucune mise à jour n'est en attente.")
    if ordre.statut != StatutMiseAJour.DEMANDEE:
        raise MiseAJourRefusee(
            "DEJA_COMMENCEE", "La mise à jour a commencé sur le satellite : elle ne "
                              "s'annule plus.")
    ordre.statut = StatutMiseAJour.ANNULEE
    ordre.date_fin = timezone.now()
    ordre.save(update_fields=["statut", "date_fin"])
    return ordre


def enregistrer_rapport(ordre, statut, etape="", journal="", version=""):
    """Ce que le satellite dit de l'avancement. Renvoie `True` si le rapport est accepté.

    `False` veut dire « arrêtez-vous » : l'ordre a été annulé ou a expiré entre-temps. C'est
    pour cela que le satellite doit d'abord faire accepter un rapport `EN_COURS` avant de
    toucher à quoi que ce soit — c'est sa prise en charge de l'ordre."""
    from .models import StatutMiseAJour

    if statut not in (StatutMiseAJour.EN_COURS, StatutMiseAJour.REUSSIE,
                      StatutMiseAJour.ECHOUEE):
        return False
    if ordre.statut not in (StatutMiseAJour.DEMANDEE, StatutMiseAJour.EN_COURS):
        # Le compte rendu final d'une mise à jour tenue pour perdue (satellite resté coupé
        # du central plus longtemps que SILENCE_MAX_EN_COURS) est tout de même pris : c'est la
        # vérité, et elle vaut mieux que « plus de nouvelles ».
        tardif = (ordre.statut == StatutMiseAJour.ECHOUEE and ordre.date_debut is not None
                  and statut in (StatutMiseAJour.REUSSIE, StatutMiseAJour.ECHOUEE))
        if not tardif:
            return False

    maintenant = timezone.now()
    champs = ["statut", "etape", "journal"]
    if ordre.date_debut is None:
        ordre.date_debut = maintenant
        champs.append("date_debut")
    ordre.statut = statut
    ordre.etape = (etape or "")[:200]
    if journal:
        ordre.journal = journal[-TAILLE_MAX_JOURNAL:]
    if statut in (StatutMiseAJour.REUSSIE, StatutMiseAJour.ECHOUEE):
        ordre.date_fin = maintenant
        champs.append("date_fin")
    ordre.save(update_fields=champs)

    if statut == StatutMiseAJour.REUSSIE:
        # Un diagnostic ou un redémarrage n'a pas de version cible : on prend ce que l'agent
        # rapporte, et rien s'il ne rapporte rien.
        installee = version or (ordre.version.commit if ordre.version_id else "")
        if installee:
            satellite = ordre.satellite
            satellite.version_logicielle = installee[:50]
            satellite.save(update_fields=["version_logicielle"])
    return True
