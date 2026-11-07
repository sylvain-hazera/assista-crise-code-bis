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
