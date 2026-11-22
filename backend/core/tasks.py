"""Tâches Celery -- simulation d'inondation, imports longs, et calculs de propagation radio (voir core/inondation.py
pour la justification : le calcul peut dépasser largement le timeout gunicorn sur une grande
commune, jamais exécuté en synchrone dans une requête HTTP).

Deux tâches INDÉPENDANTES (paliers vs adresses), pas une seule combinée -- demande explicite du
2026-09-30, suite à l'échec du chargement complet sur Bordeaux (tué par le time limit Celery
alors que le calcul du relief/niveau d'eau, lui, est toujours borné). La tâche adresses a son
propre budget de temps, plus généreux et indépendant de celui des paliers (voir les décorateurs
ci-dessous) : une grande ville peut légitimement prendre plus longtemps à charger sans que ça
bloque quoi que ce soit d'autre."""
from celery import shared_task
from django.utils import timezone


def _marquer_tache(commune_code, environment, type_tache, statut, erreur=None):
    from .models import TacheSimulationInondation

    TacheSimulationInondation.objects.update_or_create(
        commune_code=commune_code, environment=environment, type_tache=type_tache,
        defaults={"statut": statut, "date_fin": timezone.now(), "erreur": erreur},
    )


#: File des travaux lourds (amorçage départemental, chargements d'adresses en masse et ce qu'ils
#: déclenchent), consommée par son propre worker (ac_celery_worker_lourd, un processus, priorité
#: basse) : ils ne retardent jamais les alertes, notifications et tâches de crise de la file
#: par défaut. Décidé le 22/11/2026, après l'amorçage de la Gironde.
FILE_LOURDE = "lourd"


@shared_task(acks_late=True, time_limit=300, soft_time_limit=270)
def calculer_paliers_task(commune_code: str, environment: str, forcer: bool = False):
    """Grille d'altitude + paliers d'eau -- toujours borné (grille plafonnée, voir
    inondation.py:MAX_COTE), budget de temps volontairement court (5 min) : si ça dépasse,
    quelque chose d'anormal se passe (l'API IGN ne répond pas), pas la taille de la commune."""
    from .models import TypeTacheInondation, StatutTacheInondation
    from .inondation import calculer_paliers_inondation

    try:
        calculer_paliers_inondation(commune_code, forcer=forcer, environment=environment)
    except Exception as exc:
        _marquer_tache(commune_code, environment, TypeTacheInondation.PALIERS, StatutTacheInondation.ECHEC, str(exc))
        raise
    else:
        _marquer_tache(commune_code, environment, TypeTacheInondation.PALIERS, StatutTacheInondation.TERMINEE)


@shared_task(acks_late=True, time_limit=1800, soft_time_limit=1750)
def charger_adresses_task(commune_code: str, environment: str, forcer: bool = False):
    """Scan BAN + seuil par adresse -- NON borné en principe (dépend du nombre d'adresses de la
    commune, voir inondation.py:SEUIL_VOIES_MAX pour le garde-fou), budget de temps bien plus
    généreux que la tâche paliers (30 min) puisque désormais indépendante : ne bloque jamais la
    simulation du niveau d'eau, même en cas d'échec ou de lenteur."""
    from .models import TypeTacheInondation, StatutTacheInondation
    from .inondation import seuils_inondation_adresses

    try:
        seuils_inondation_adresses(commune_code, forcer=forcer, environment=environment)
    except Exception as exc:
        _marquer_tache(commune_code, environment, TypeTacheInondation.ADRESSES, StatutTacheInondation.ECHEC, str(exc))
        raise
    else:
        _marquer_tache(commune_code, environment, TypeTacheInondation.ADRESSES, StatutTacheInondation.TERMINEE)


@shared_task(acks_late=True, time_limit=300, soft_time_limit=270)
def calculer_ruissellement_task(commune_code: str, environment: str, forcer: bool = False):
    """Accumulation de flux (crue éclair) -- même grille que la tâche paliers, toujours bornée,
    même budget de temps court (pas de risque de reproduire le bug Bordeaux : pas de boucle
    géométrique coûteuse, voir core/ruissellement.py)."""
    from .models import TypeTacheInondation, StatutTacheInondation
    from .ruissellement import calculer_accumulation_flux

    try:
        calculer_accumulation_flux(commune_code, forcer=forcer, environment=environment)
    except Exception as exc:
        _marquer_tache(commune_code, environment, TypeTacheInondation.RUISSELLEMENT, StatutTacheInondation.ECHEC, str(exc))
        raise
    else:
        _marquer_tache(commune_code, environment, TypeTacheInondation.RUISSELLEMENT, StatutTacheInondation.TERMINEE)


@shared_task(acks_late=True, time_limit=1800, soft_time_limit=1740)
def importer_sites_sensibles_task(institution_id, source, perimetre, commune_nom=None,
                                  environment=None, options=None):
    """Tout import qui ne tient pas dans une requête HTTP : les deux sources lourdes quel que
    soit le périmètre, et toute source dès que le périmètre dépasse la commune.

    FINESS : ~50 Mo à télécharger et ~750 Mo de JSON à parcourir pour en extraire une commune
    (voir core/opendata/finess.py). SIRENE : onze thèmes paginés 25 par 25, soit une centaine
    d'appels sur une grande ville et davantage sur un département (voir core/opendata/sirene.py),
    et `options` porte alors les thèmes demandés. `perimetre` arrive sous la forme
    `{niveau, code}` : la liste des communes se reconstruit ici (voir construire_perimetre).

    Deux limites de temps emboîtées, et l'ordre compte : l'import s'arrête LUI-MÊME au bout de
    son budget (opendata.base.BUDGET_SECONDES, 15 min) en consignant ce qui manque, bien avant
    que Celery ne le tue à 30 min. Une tâche tuée par Celery ne consigne rien : l'écran
    resterait sur « recherche en cours » indéfiniment, ce qui est exactement ce qu'on a vu en
    production le 27/10/2026. La limite dure n'est qu'un dernier filet."""
    from django.utils import timezone

    from .models import Institution, StatutImportOpenData
    from .sites_sensibles import _marquer, executer_import

    institution = Institution.objects.filter(pk=institution_id).first()
    if institution is None:
        return
    try:
        executer_import(institution, source, perimetre, commune_nom, environment, options)
    except Exception as exc:
        # executer_import absorbe déjà les pannes de source ; on n'arrive ici que sur un imprévu
        # (base indisponible, flux au format inattendu). L'état doit quand même cesser d'afficher
        # « en cours » à l'écran, sinon l'agent attend indéfiniment.
        _marquer(
            institution, environment or institution.environment, source,
            statut=StatutImportOpenData.ECHEC, erreur=str(exc), date_fin=timezone.now(),
        )
        raise


@shared_task(acks_late=True, time_limit=1800, soft_time_limit=1740)
def calculer_couverture_radio_task(couverture_id: str):
    """Couverture radio d'un site sur le relief (voir core/relief_radio.py).

    Budget de temps généreux (30 min) pour la même raison que la tâche adresses : le coût ne
    vient pas du calcul mais de l'API d'altimétrie IGN, limitée à 2,5 requêtes par seconde et
    partagée avec les simulations d'inondation. Un site neuf de 40 km de rayon demande une
    trentaine de lots ; un site déjà calculé une fois ne demande presque rien (cache
    `PointAltitude`).

    Un échec est enregistré SUR la couverture elle-même, avec son message : une couverture
    manquante sans explication enverrait l'exploitant chercher une panne inexistante."""
    from .models import CouvertureRadioSite, StatutCouvertureRadio
    from .relief_radio import calculer_couverture

    couverture = CouvertureRadioSite.objects.filter(id=couverture_id).first()
    if couverture is None:
        return
    try:
        calculer_couverture(couverture)
    except Exception as exc:
        CouvertureRadioSite.objects.filter(id=couverture_id).update(
            statut=StatutCouvertureRadio.ECHEC, erreur=str(exc)[:2000], date_calcul=timezone.now(),
        )
        raise


@shared_task(acks_late=True, time_limit=900, soft_time_limit=840)
def calibrer_radio_task(environment: str):
    """Compare le modèle de propagation aux liaisons mesurées (voir relief_radio.calibrer).

    Asynchrone parce qu'elle demande un profil de terrain par liaison retenue : quelques dizaines
    de lots IGN. Le résultat est une ligne de `CalibrationRadio` ; aucune couverture déjà
    calculée n'est modifiée -- elles portent la perte d'environnement qui était en vigueur au
    moment de leur calcul, et la fausser après coup rendrait un résultat non reproductible."""
    from .relief_radio import calibrer

    return calibrer(environment)


@shared_task(acks_late=True, time_limit=600, soft_time_limit=570)
def relever_zonages_officiels_task(commune_code: str, environment: str, forcer: bool = False):
    """Relève les zones inondables officielles d'une commune auprès de Géorisques, une requête
    par scénario, espacées (voir core/zonages_officiels.py). En tâche de fond : cinq requêtes
    et leurs pauses ne tiennent pas dans le délai d'une page."""
    # 18/11/2026 : UN relevé pour tout ce que Géorisques publie sur la commune — risques, arrêtés
    # de catastrophe naturelle, atlas, mouvements de terrain, radon, sismicité, zones inondables
    # et plans de prévention. Il nourrit toutes les pages (core/releve_georisques.py).
    from .releve_georisques import relever_tout

    return relever_tout(commune_code, environment, forcer=forcer)


@shared_task(queue=FILE_LOURDE, acks_late=True, time_limit=1800, soft_time_limit=1770)
def charger_adresses_departement_task(communes: list):
    """Charge les adresses de ces communes depuis le fichier départemental de la Base Adresse
    Nationale (core/referentiel_adresses.py) : un téléchargement par département.

    Renommée le 21/11/2026 : elle s'appelait aussi `charger_adresses_task`, comme la tâche de
    la simulation d'inondation plus haut, qu'elle écrasait — le worker l'annonçait
    (DuplicateTaskNameWarning) et la simulation appelait alors cette fonction-ci avec trois
    arguments au lieu d'un."""
    from .referentiel_adresses import charger_communes, communes_manquantes

    # Les communes chargées entre-temps (par l'amorçage, ou une demande précédente) ne justifient
    # pas un nouveau téléchargement du fichier départemental.
    restantes = sorted(communes_manquantes(communes))
    return charger_communes(restantes) if restantes else {"lues": 0, "creees": 0, "modifiees": 0, "retirees": 0}


@shared_task(acks_late=True, time_limit=900, soft_time_limit=870)
def relever_adresses_commune_task(commune_code: str, environment: str):
    """Rapatrie les adresses d'une commune depuis la Base Adresse Nationale, sans simulation
    (core/rattachement_adresses.py) : pour rattacher les personnes du registre à leur adresse là
    où aucune simulation d'inondation n'a été lancée."""
    from .rattachement_adresses import relever_les_adresses

    return relever_les_adresses(commune_code, environment)


@shared_task(acks_late=True, time_limit=900, soft_time_limit=870)
def prevenir_le_reseau_des_dons_task(appel_id: str):
    """Prévient les institutions du périmètre d'un appel aux dons qui vient de s'ouvrir ou de
    s'élargir (core/notifications_dons.py). En tâche de fond : un appel national écrit à beaucoup
    de monde, et l'ouverture ne doit pas attendre la fin des envois."""
    from .models import AppelAuxDons
    from .notifications_dons import prevenir_le_reseau

    appel = AppelAuxDons.objects.select_related("institution", "crise").filter(pk=appel_id).first()
    return prevenir_le_reseau(appel) if appel is not None else {"institutions": 0, "personnes": 0}


@shared_task(acks_late=True, time_limit=120, soft_time_limit=100)
def pousser_notification_task(notification_id: str):
    """Notification poussée vers les applications web (core/notifications_application.pousser)."""
    from .notifications_application import pousser
    return pousser(notification_id)


@shared_task(acks_late=True, time_limit=120, soft_time_limit=100)
def pousser_notification_site_task(notification_id: str):
    """Notification de l'administration poussée vers les appareils abonnés (poste de pilotage)."""
    from .notifications_application import pousser_notification_site
    return pousser_notification_site(notification_id)



@shared_task(queue=FILE_LOURDE, acks_late=True, time_limit=4 * 3600, soft_time_limit=4 * 3600 - 60)
def amorcer_departement_task(amorcage_id: str, etapes=None, jeton=None):
    """Amorçage d'un département (core/amorcage_departement.py) : annuaire officiel commune par
    commune, adresses, risques, sites sensibles. Long par nature (un appel à l'Annuaire et à
    Géorisques par commune) : quatre heures de budget, chaque étape consignée au fil de l'eau.
    `jeton` : posé par une reprise ; un message d'avant la reprise (sans le bon jeton) est ignoré."""
    from .amorcage_departement import ETAPES, executer
    from .models import AmorcageDepartement

    amorcage = AmorcageDepartement.objects.select_related("delegation__collectivite").filter(pk=amorcage_id).first()
    if amorcage is None:
        return
    attendu = ((amorcage.etapes or {}).get("_principal") or {}).get("jeton")
    if attendu and jeton != attendu:
        return
    executer(amorcage, [e for e in (etapes or ETAPES) if e in ETAPES])


@shared_task(queue=FILE_LOURDE, acks_late=True, time_limit=900, soft_time_limit=870)
def enchainer_amorcage_task(etape: str, communes: list, environment: str, reference=None, jeton=None):
    """Amorçage départemental, étapes longues : une commune, puis la tâche se reprogramme
    (core/amorcage_departement.enchainer). L'avancement est en base ; `communes` n'est plus
    lu (gardé pour la forme des anciens messages, qui sont ignorés faute de jeton)."""
    from .amorcage_departement import enchainer
    if not reference or not jeton:
        return
    enchainer("entreprises" if etape == "sirene" else etape, reference, jeton, environment)


@shared_task(queue=FILE_LOURDE, acks_late=True, time_limit=600, soft_time_limit=570)
def reprendre_amorcages_task(silence_minutes: int = 30):
    """Relance les amorçages arrêtés (core/amorcage_departement.reprendre)."""
    from .amorcage_departement import reprendre
    return reprendre(silence_minutes)


def _reprise_au_demarrage(sender=None, **kwargs):
    """Au démarrage du worker des travaux lourds (redéploiement, redémarrage de la machine) :
    tout ce qui tournait a été coupé, on le reprend là où il en était (22/11/2026)."""
    nom = str(getattr(sender, "hostname", "") or "")
    if nom.startswith("lourd@"):
        reprendre_amorcages_task.apply_async(args=[0], countdown=30)


from celery.signals import worker_ready  # noqa: E402

worker_ready.connect(_reprise_au_demarrage, weak=False)


#: Pause entre deux courriels d'une campagne : un SMTP d'institution n'accepte pas 500 messages d'un coup.
PAUSE_CAMPAGNE_S = 0.5


@shared_task(queue=FILE_LOURDE, acks_late=True, time_limit=4 * 3600, soft_time_limit=4 * 3600 - 60)
def envoyer_campagne_invitation_task(campagne_id: str, institution_ids: list):
    """Campagne « Rejoindre votre collectivité » préparée dans la fenêtre de rédaction : un
    courriel à la fois, par le connecteur choisi, sans passer par la relecture (c'était la
    fenêtre). Un échec n'arrête pas les autres ; tout est compté sur la campagne."""
    import time

    from django.utils import timezone

    from . import invitation_collectivite as ic
    from .audit import audit_log
    from .branding import get_mail_branding
    from .envoi_connecteurs import EchecEnvoi, envoyer
    from .models import CampagneInvitation, Environment, Institution

    campagne = CampagneInvitation.objects.select_related("delegation__aasc", "delegation__collectivite", "cree_par").get(pk=campagne_id)
    delegation = campagne.delegation
    permises = [delegation.aasc, delegation.collectivite]
    reply_to = get_mail_branding(delegation.aasc)["reply_to"]
    institutions = {str(i.id): i for i in Institution.objects.filter(id__in=institution_ids, actif=True)}
    erreurs = list(campagne.erreurs or [])
    for rang, inst_id in enumerate(institution_ids):
        inst = institutions.get(str(inst_id))
        if inst is None:
            continue
        preparation = ic.preparer(inst)
        if preparation["etat"] == "deja_membre":
            campagne.deja_membres += 1
        elif preparation["etat"] == "sans_email":
            campagne.sans_adresse += 1
        else:
            invitation = ic.invitation_pour(inst, delegation, preparation["destinataire"], campagne.cree_par)
            champs = ic.valeurs(inst, delegation, preparation, ic.lien(invitation))
            sujet, corps = ic.rendre(campagne.sujet, champs), ic.rendre(campagne.corps, champs)
            destinataire = preparation["destinataire"]
            if campagne.environment == Environment.DEMO and campagne.cree_par and campagne.cree_par.email:
                destinataire, sujet = campagne.cree_par.email, f"[DEMO] {sujet}"
            try:
                envoyer(campagne.connecteur, sujet, corps, destinataire, reply_to=reply_to, institutions_permises=permises)
                campagne.envoyees += 1
            except EchecEnvoi as echec:
                campagne.echecs += 1
                erreurs.append({"collectivite": inst.nom, "motif": str(echec)[:300]})
            if PAUSE_CAMPAGNE_S and rang < len(institution_ids) - 1:
                time.sleep(PAUSE_CAMPAGNE_S)
        campagne.erreurs = erreurs[-200:]
        campagne.save(update_fields=["envoyees", "echecs", "sans_adresse", "deja_membres", "erreurs"])
    campagne.statut, campagne.date_fin = CampagneInvitation.Statut.TERMINEE, timezone.now()
    campagne.save(update_fields=["statut", "date_fin"])
    audit_log(request=None, action_code="ENVOI_MASSE", objet_type="DelegationGestion", objet_id=delegation.id,
              commentaire=(f"Campagne « Rejoindre votre collectivité » par {campagne.connecteur_libelle} : "
                           f"{campagne.envoyees} envoyée(s), {campagne.echecs} échec(s), "
                           f"{campagne.sans_adresse} sans adresse, {campagne.deja_membres} déjà présente(s)"))
