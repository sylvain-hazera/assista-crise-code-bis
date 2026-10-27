"""Tâches Celery -- pour l'instant uniquement la simulation d'inondation (voir core/inondation.py
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


@shared_task(acks_late=True, time_limit=900, soft_time_limit=840)
def importer_sites_sensibles_task(institution_id, source, commune_code, commune_nom=None,
                                  environment=None, options=None):
    """Les deux imports qui ne tiennent pas dans une requête HTTP.

    FINESS : ~50 Mo à télécharger et ~750 Mo de JSON à parcourir pour en extraire une commune
    (voir core/opendata/finess.py). SIRENE : jusqu'à sept thèmes paginés 25 par 25, soit une
    cinquantaine d'appels sur une grande ville (voir core/opendata/sirene.py), et `options`
    porte alors les thèmes demandés. Budget de 15 min, très au-dessus de la minute mesurée :
    ce qui dépasse serait une anomalie du producteur, pas la taille de la commune."""
    from django.utils import timezone

    from .models import Institution, StatutImportOpenData
    from .sites_sensibles import _marquer, executer_import

    institution = Institution.objects.filter(pk=institution_id).first()
    if institution is None:
        return
    try:
        executer_import(institution, source, commune_code, commune_nom, environment, options)
    except Exception as exc:
        # executer_import absorbe déjà les pannes de source ; on n'arrive ici que sur un imprévu
        # (base indisponible, flux au format inattendu). L'état doit quand même cesser d'afficher
        # « en cours » à l'écran, sinon l'agent attend indéfiniment.
        _marquer(
            institution, environment or institution.environment, source,
            statut=StatutImportOpenData.ECHEC, erreur=str(exc), date_fin=timezone.now(),
        )
        raise
