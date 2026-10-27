"""Import et mise à jour des SiteSensible depuis les sources ouvertes (voir core/opendata/).

Deux principes, tenus par les tests :

1. Rien n'entre jamais ailleurs qu'en PROPOSE. L'open data remplit le formulaire, il ne signe
   pas le plan de sauvegarde.
2. Un ré-import n'écrase JAMAIS le travail d'un agent. Le nom corrigé, l'effectif estimé, le
   commentaire et la décision (retenu/écarté) sont à lui ; la source ne peut que rafraîchir ses
   propres attributs et COMPLÉTER ce qui est encore vide. Sans cette règle, le bouton
   « Actualiser » détruirait silencieusement des heures de relecture."""
import datetime
import logging

from django.contrib.gis.geos import Point

from .models import CategorieSiteSensible, SiteSensible, StatutSiteSensible
from .opendata import CONNECTEURS

logger = logging.getLogger(__name__)

FORMATS_DATE = ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d")

# Plancher de vraisemblance : toutes les sources branchées ici sont des jeux de données du XXIe
# siècle. Géorisques rend des `date_maj` sentinelles en 1900 (vu en direct sur une ICPE réelle) ;
# afficher « données du 12/02/1900 » à un agent serait plus trompeur que ne rien afficher.
ANNEE_MINIMALE = 2000


def _parse_date(valeur):
    """Date annoncée par une source, dans l'un des formats qu'elles emploient — None si illisible
    ou invraisemblable (une date de fraîcheur fausse serait pire que pas de date du tout)."""
    if not valeur:
        return None
    texte = str(valeur).strip()[:10]
    for format_date in FORMATS_DATE:
        try:
            date = datetime.datetime.strptime(texte, format_date).date()
        except ValueError:
            continue
        return date if date.year >= ANNEE_MINIMALE else None
    return None


def _point(site):
    if site.latitude is None or site.longitude is None:
        return None
    try:
        return Point(float(site.longitude), float(site.latitude), srid=4326)
    except (TypeError, ValueError):
        return None


def _appliquer(existant, propose, commune_code, commune_nom):
    """Met à jour une ligne déjà connue, sans toucher à ce qui relève de la décision humaine.

    Rend True si quelque chose a changé."""
    modifie = False

    date_source = _parse_date(propose.attributs.get("date_maj_source"))
    if date_source and existant.date_source != date_source:
        existant.date_source = date_source
        modifie = True

    # Les attributs appartiennent à la source : un site qui passe Seveso seuil haut doit le dire.
    if existant.attributs != propose.attributs:
        existant.attributs = propose.attributs
        modifie = True

    # Le reste n'est que complété, jamais remplacé.
    if not existant.adresse and propose.adresse:
        existant.adresse = propose.adresse
        modifie = True
    if not existant.telephone and propose.telephone:
        existant.telephone = propose.telephone
        modifie = True
    if existant.location is None:
        point = _point(propose)
        if point is not None:
            existant.location = point
            modifie = True
    if not existant.commune_code and commune_code:
        existant.commune_code = commune_code
        existant.commune_nom = commune_nom
        modifie = True

    if modifie:
        existant.save()
    return modifie


def enregistrer_proposes(institution, environment, commune_code, commune_nom, proposes):
    """Dépose une liste de SitePropose en base et rend le compte rendu de l'opération."""
    crees = majs = inchanges = 0
    for propose in proposes:
        existant = SiteSensible.objects.filter(
            institution=institution, environment=environment,
            source=propose.source, source_id=propose.source_id,
        ).first()
        if existant is not None:
            if _appliquer(existant, propose, commune_code, commune_nom):
                majs += 1
            else:
                inchanges += 1
            continue
        SiteSensible.objects.create(
            institution=institution,
            environment=environment,
            commune_code=commune_code,
            commune_nom=commune_nom,
            source=propose.source,
            source_id=propose.source_id,
            categorie=propose.categorie,
            nom=propose.nom[:255],
            adresse=propose.adresse,
            telephone=propose.telephone[:30],
            location=_point(propose),
            attributs=propose.attributs,
            date_source=_parse_date(propose.attributs.get("date_maj_source")),
            statut=StatutSiteSensible.PROPOSE,
        )
        crees += 1
    return {"crees": crees, "mis_a_jour": majs, "inchanges": inchanges,
            "total": crees + majs + inchanges}


def importer_source(institution, source, commune_code, commune_nom=None, environment=None):
    """Collecte une source et enregistre ses propositions. Ne lève jamais : une source en panne
    rend un compte rendu à zéro, les autres continuent."""
    connecteur = CONNECTEURS.get(source)
    if connecteur is None:
        raise ValueError(f"Source inconnue : {source}")
    environment = environment or institution.environment
    try:
        proposes = connecteur.collecter(commune_code)
    except Exception as exc:
        logger.warning("Import %s pour la commune %s : %s", source, commune_code, exc)
        return {"crees": 0, "mis_a_jour": 0, "inchanges": 0, "total": 0, "erreur": str(exc)}
    return enregistrer_proposes(institution, environment, commune_code, commune_nom, proposes)


def synthese_par_categorie(institution, environment):
    """Compte des sites par catégorie et par statut — l'en-tête de la page, qui doit dire d'un
    coup d'œil ce qui reste à relire."""
    synthese = {}
    lignes = SiteSensible.objects.filter(
        institution=institution, environment=environment,
    ).values_list("categorie", "statut")
    for categorie, statut in lignes:
        case = synthese.setdefault(categorie, {code: 0 for code, _ in StatutSiteSensible.choices})
        case[statut] = case.get(statut, 0) + 1
    return {
        "par_categorie": [
            {"categorie": code, "libelle": libelle, **synthese.get(code, {})}
            for code, libelle in CategorieSiteSensible.choices
            if code in synthese
        ],
        "a_relire": sum(
            case.get(StatutSiteSensible.PROPOSE, 0) for case in synthese.values()
        ),
    }


def _marquer(institution, environment, source, **champs):
    from .models import ImportOpenData

    tache, _ = ImportOpenData.objects.update_or_create(
        institution=institution, environment=environment, source=source, defaults=champs,
    )
    return tache


def executer_import(institution, source, commune_code, commune_nom=None, environment=None):
    """Exécute un import de bout en bout et consigne son résultat dans ImportOpenData.

    Point d'entrée unique, appelé soit directement (sources API, quelques centaines de ms) soit
    depuis la tâche Celery (FINESS) : la trace en base est la même dans les deux cas."""
    from django.utils import timezone

    from .models import StatutImportOpenData

    environment = environment or institution.environment
    resultat = importer_source(institution, source, commune_code, commune_nom, environment)
    echec = "erreur" in resultat
    _marquer(
        institution, environment, source,
        statut=StatutImportOpenData.ECHEC if echec else StatutImportOpenData.TERMINEE,
        resultat={k: v for k, v in resultat.items() if k != "erreur"},
        erreur=resultat.get("erreur"),
        date_fin=timezone.now(),
    )
    return resultat


def lancer_import(institution, source, commune_code, commune_nom=None, environment=None):
    """Lance un import : synchrone pour les API filtrables par commune, délégué à Celery pour
    FINESS (voir opendata/__init__.py). Rend (resultat, asynchrone)."""
    from .models import StatutImportOpenData
    from .opendata import SOURCES_ASYNCHRONES

    environment = environment or institution.environment
    if source in SOURCES_ASYNCHRONES:
        from .tasks import importer_sites_sensibles_task

        _marquer(
            institution, environment, source,
            statut=StatutImportOpenData.EN_COURS, erreur=None, date_fin=None, resultat={},
        )
        importer_sites_sensibles_task.delay(
            str(institution.id), source, commune_code, commune_nom, environment,
        )
        return None, True
    return executer_import(institution, source, commune_code, commune_nom, environment), False
