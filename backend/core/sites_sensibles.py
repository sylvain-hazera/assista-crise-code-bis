"""Import et mise à jour des SiteSensible depuis les sources ouvertes (voir core/opendata/).

Deux principes, tenus par les tests :

1. Rien n'entre jamais ailleurs qu'en PROPOSE. L'open data remplit le formulaire, il ne signe
   pas le plan de sauvegarde.
2. Un même établissement ne produit qu'UNE ligne, quel que soit le nombre de sources qui le
   connaissent. Le SIRET sert de clé commune : 15 des 25 ICPE de Châteauneuf-du-Faou sont aussi
   des établissements SIRENE, et l'agent n'a pas à relire deux fois la même ferme.
3. Un ré-import n'écrase JAMAIS le travail d'un agent. Le nom corrigé, l'effectif estimé, le
   commentaire et la décision (retenu/écarté) sont à lui ; la source ne peut que rafraîchir ses
   propres attributs, COMPLÉTER ce qui est encore vide, et reclasser une ligne que personne n'a
   encore relue. Sans cette règle, le bouton « Actualiser » détruirait silencieusement des
   heures de relecture."""
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


def _siret(propose):
    """Le SIRET annoncé par la source, seule clé partagée entre elles : Géorisques le donne sur
    les 27 ICPE de Châteauneuf, et SIRENE en fait son identifiant d'établissement."""
    siret = (propose.attributs or {}).get("siret")
    siret = str(siret).strip() if siret else ""
    return siret or None


def _site_du_meme_siret(institution, environment, propose):
    """Le même établissement, déjà connu par une AUTRE source.

    15 des 25 installations classées de Châteauneuf-du-Faou partagent leur SIRET avec un
    établissement SIRENE : sans ce rapprochement, l'agent relirait quinze fois la même ferme
    deux fois — une fois sous son code AIOT, une fois sous son SIRET — et le plan compterait
    double."""
    siret = _siret(propose)
    if not siret:
        return None
    return SiteSensible.objects.filter(
        institution=institution, environment=environment, attributs__siret=siret,
    ).exclude(source=propose.source).order_by("date_import").first()


# Ce qu'une source peut apporter à une ligne tenue par une autre : son identifiant, ce qu'elle
# sait de l'activité, et ce que l'autre n'a pas. On complète, on ne remplace pas.
CLES_COMPLEMENTAIRES = (
    "naf", "naf_libelle", "tranche_effectif", "siren", "nature_juridique",
    "especes", "cheptel", "code_aiot", "statut_seveso", "regime", "ied", "uai", "finess",
)


def _fusionner(existant, propose):
    """Verse ce qu'une seconde source sait dans la ligne qui existe déjà, sans rien lui retirer.

    Rend True si quelque chose a changé."""
    modifie = False
    attributs = dict(existant.attributs or {})

    for cle in CLES_COMPLEMENTAIRES:
        valeur = (propose.attributs or {}).get(cle)
        if valeur in (None, "", [], {}) or attributs.get(cle) not in (None, "", [], {}):
            continue
        attributs[cle] = valeur
        modifie = True

    # Le nom vu par l'autre source est souvent meilleur (SIRENE dit « SCEA CONAN » là où
    # Géorisques dit « CONAN (SCEA) »), mais renommer une ligne n'est pas le travail d'un
    # import : on le montre à l'agent, il tranche.
    if propose.nom and propose.nom != existant.nom and not attributs.get("nom_autre_source"):
        attributs["nom_autre_source"] = propose.nom
        modifie = True

    liees = sorted({existant.source, propose.source} | set(attributs.get("sources_liees") or []))
    if liees != attributs.get("sources_liees"):
        attributs["sources_liees"] = liees
        modifie = True

    if modifie:
        existant.attributs = attributs

    # Une source peut révéler un usage que l'autre ignorait : une ferme connue comme enjeu par
    # Géorisques est aussi un moyen d'action pour SIRENE. Même garde que partout : tant que
    # personne n'a statué.
    if existant.statut == StatutSiteSensible.PROPOSE and existant.valide_par_id is None:
        if propose.est_enjeu and not existant.est_enjeu:
            existant.est_enjeu = True
            modifie = True
        if propose.est_ressource and not existant.est_ressource:
            existant.est_ressource = True
            modifie = True

    # Si la seconde source identifie une personne physique, la ligne entière en devient une —
    # y compris quand le registre d'origine publie l'adresse (c'est le cas de Géorisques). Sans
    # ça, le même exploitant serait masqué d'un côté et exposé de l'autre, et le masquage ne
    # vaudrait rien.
    if propose.personne_physique and not existant.personne_physique:
        existant.personne_physique = True
        coordonnees = _coordonnees_personnelles(propose)
        if not coordonnees and existant.location is not None:
            coordonnees = {"latitude": existant.location.y, "longitude": existant.location.x}
        if coordonnees:
            existant.donnees_personnelles = coordonnees
        existant.location = None
        modifie = True

    if not existant.adresse and propose.adresse:
        existant.adresse = propose.adresse
        modifie = True
    if not existant.telephone and propose.telephone:
        existant.telephone = propose.telephone
        modifie = True

    if modifie:
        existant.save()
    return modifie


def _coordonnees_personnelles(propose):
    """Les coordonnées d'une personne physique, destinées au champ chiffré."""
    if propose.latitude is None or propose.longitude is None:
        return {}
    return {"latitude": propose.latitude, "longitude": propose.longitude}


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

    # La catégorie vient de la source, et son classement s'améliore avec le temps : les
    # élevages ont longtemps atterri avec les usines. On la rafraîchit, mais seulement sur une
    # ligne vierge de toute décision — dès qu'un agent a retenu ou écarté le site, le rangement
    # est le sien.
    if existant.statut == StatutSiteSensible.PROPOSE and existant.valide_par_id is None:
        if existant.categorie != propose.categorie:
            existant.categorie = propose.categorie
            modifie = True
        # Même règle pour le rôle : tant que personne n'a statué, il appartient à la source.
        if (existant.est_enjeu, existant.est_ressource) != (propose.est_enjeu,
                                                            propose.est_ressource):
            existant.est_enjeu = propose.est_enjeu
            existant.est_ressource = propose.est_ressource
            modifie = True

    # Personne physique ou non est un fait de la source, pas une appréciation : toujours à jour,
    # sinon une ligne cesserait d'être protégée (ou le resterait à tort) après un changement de
    # forme juridique.
    if existant.personne_physique != propose.personne_physique:
        existant.personne_physique = propose.personne_physique
        modifie = True

    # Le reste n'est que complété, jamais remplacé.
    if not existant.adresse and propose.adresse:
        existant.adresse = propose.adresse
        modifie = True
    if not existant.telephone and propose.telephone:
        existant.telephone = propose.telephone
        modifie = True
    if propose.personne_physique:
        # Jamais de point en clair pour un domicile : des coordonnées GPS le désignent aussi
        # sûrement que l'adresse.
        coordonnees = _coordonnees_personnelles(propose)
        if existant.location is not None:
            existant.location = None
            modifie = True
        if coordonnees and not existant.donnees_personnelles:
            existant.donnees_personnelles = coordonnees
            modifie = True
    elif existant.location is None:
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
        # Pas connu sous cet identifiant — mais peut-être sous celui d'une autre source.
        jumeau = _site_du_meme_siret(institution, environment, propose)
        if jumeau is not None:
            if _fusionner(jumeau, propose):
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
            location=None if propose.personne_physique else _point(propose),
            personne_physique=propose.personne_physique,
            donnees_personnelles=(
                _coordonnees_personnelles(propose) if propose.personne_physique else {}
            ),
            est_enjeu=propose.est_enjeu,
            est_ressource=propose.est_ressource,
            attributs=propose.attributs,
            date_source=_parse_date(propose.attributs.get("date_maj_source")),
            statut=StatutSiteSensible.PROPOSE,
        )
        crees += 1
    return {"crees": crees, "mis_a_jour": majs, "inchanges": inchanges,
            "total": crees + majs + inchanges}


def importer_source(institution, source, commune_code, commune_nom=None, environment=None,
                    options=None):
    """Collecte une source et enregistre ses propositions. Ne lève jamais : une source en panne
    rend un compte rendu à zéro, les autres continuent.

    `options` est passé tel quel au connecteur : seul SIRENE en a besoin (`categories`, les
    thèmes que la commune veut recenser)."""
    connecteur = CONNECTEURS.get(source)
    if connecteur is None:
        raise ValueError(f"Source inconnue : {source}")
    environment = environment or institution.environment
    try:
        proposes = connecteur.collecter(commune_code, **(options or {}))
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


def executer_import(institution, source, commune_code, commune_nom=None, environment=None,
                    options=None):
    """Exécute un import de bout en bout et consigne son résultat dans ImportOpenData.

    Point d'entrée unique, appelé soit directement (sources API, quelques centaines de ms) soit
    depuis la tâche Celery (FINESS) : la trace en base est la même dans les deux cas."""
    from django.utils import timezone

    from .models import StatutImportOpenData

    environment = environment or institution.environment
    resultat = importer_source(institution, source, commune_code, commune_nom, environment,
                               options)
    echec = "erreur" in resultat
    _marquer(
        institution, environment, source,
        statut=StatutImportOpenData.ECHEC if echec else StatutImportOpenData.TERMINEE,
        resultat={k: v for k, v in resultat.items() if k != "erreur"},
        erreur=resultat.get("erreur"),
        date_fin=timezone.now(),
    )
    return resultat


def lancer_import(institution, source, commune_code, commune_nom=None, environment=None,
                  options=None):
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
            str(institution.id), source, commune_code, commune_nom, environment, options,
        )
        return None, True
    return (executer_import(institution, source, commune_code, commune_nom, environment, options),
            False)
