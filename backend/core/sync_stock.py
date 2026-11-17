"""Le stock sur un satellite : tenu hors connexion, remonté au central, redescendu du central.

Un point d'accueil coupé d'Internet doit pouvoir recevoir, distribuer et compter. Le journal de
stock s'y prête mieux que tout le reste : il n'ajoute que des lignes, jamais retouchées
(core/stocks.py). Il n'y a donc **pas de conflit** à arbitrer entre le satellite et le central :
chacun inscrit ses mouvements, et la quantité est la somme des deux.

- **Montant** (satellite -> central), par la file de core/sync_outbox.py : dépôts et articles
  CRÉÉS sur place (le dépôt d'un point, l'article d'un don) et tous les mouvements. Rejoués dans
  l'ordre de création : le dépôt et l'article précèdent toujours leurs mouvements.
- **Descendant** (central -> satellite FULL), avec `SatelliteViewSet.donnees` : les dépôts, les
  articles et les mouvements de l'institution du satellite, pour qu'il parte du bon stock.

Trois points à connaître :

- **Le catalogue ne voyage pas par identifiant.** Un besoin du catalogue (« Lit de camp ») n'a
  pas le même identifiant d'un déploiement à l'autre : l'article le cite par son NOM.
- **Une fiche modifiée ne remonte pas.** Seules les créations voyagent : changer le seuil d'un
  article sur le satellite reste local. Le coût moyen, recalculé aux entrées, peut donc différer
  légèrement entre les deux ; il est indicatif.
- **Deux sorties faites des deux côtés pendant une coupure peuvent, additionnées, dépasser le
  stock.** Aucun des deux ne pouvait le savoir. Le total devient alors négatif, l'article passe
  en alerte, et un inventaire le remet d'aplomb : on ne perd aucune ligne pour autant.
"""
from decimal import Decimal

CHAMPS = {
    "DepotStock": ["institution_id", "nom", "adresse", "commentaire", "point_id", "froid_positif", "froid_negatif", "cuisson", "actif"],
    "ArticleStock": ["institution_id", "reference", "designation", "categorie", "unite", "seuil_alerte", "perissable", "conservation",
                     "preparation", "prix_unitaire", "code_barres", "description", "actif"],
    "MouvementStock": ["article_id", "depot_id", "type", "quantite", "lot", "date_peremption", "prix_unitaire", "motif", "tiers",
                       "crise_id", "mission_id", "equipe_id", "transfert", "auteur_id", "date_mouvement"],
}
#: Liens vers des objets qui existent des deux côtés sous le même identifiant — ou pas encore :
#: absents, ils sont laissés vides plutôt que de faire échouer la ligne.
LIENS_FACULTATIFS = {
    "DepotStock": {"point_id": "PointOperationnel"},
    "ArticleStock": {},
    "MouvementStock": {"crise_id": "Crisis", "mission_id": "Mission", "equipe_id": "Team", "auteur_id": "User"},
}


def _valeur(valeur):
    if isinstance(valeur, Decimal):
        return str(valeur)
    if hasattr(valeur, "isoformat"):
        return valeur.isoformat()
    return str(valeur) if hasattr(valeur, "hex") and not isinstance(valeur, (str, bytes)) else valeur


def payload(instance, nom_modele) -> dict:
    """Ce qui voyage pour une ligne de stock, dans un sens comme dans l'autre."""
    donnees = {champ: _valeur(getattr(instance, champ)) for champ in CHAMPS[nom_modele]}
    if nom_modele == "ArticleStock":
        donnees["catalogue_cle"] = instance.catalogue.nom if instance.catalogue_id else None
    return donnees


def preparer(nom_modele, donnees: dict) -> dict:
    """À l'arrivée : le catalogue se retrouve par son nom, et un lien vers un objet inconnu ici
    est laissé vide."""
    from django.apps import apps

    donnees = dict(donnees)
    if nom_modele == "ArticleStock":
        cle = donnees.pop("catalogue_cle", None)
        if cle:
            donnees["catalogue_id"] = apps.get_model("core", "MaterielCatalogue").objects.get_or_create(nom=cle)[0].id
    for champ, nom_cible in LIENS_FACULTATIFS[nom_modele].items():
        if donnees.get(champ) and not apps.get_model("core", nom_cible).objects.filter(pk=donnees[champ]).exists():
            donnees[champ] = None
    return donnees


def apres(nom_modele, objet_id) -> None:
    """Un mouvement arrivé sur le dépôt d'un point d'accueil met à jour la ligne de stock du point."""
    if nom_modele != "MouvementStock":
        return
    from . import stocks_points
    from .models import MouvementStock
    mouvement = MouvementStock.objects.select_related("depot__point", "article__catalogue").filter(pk=objet_id).first()
    if mouvement is not None and mouvement.depot.point_id and mouvement.article.catalogue_id:
        stocks_points.synchroniser(mouvement.depot.point, mouvement.article.catalogue, mouvement.environment)


# ── Descendant : ce que le central donne au satellite ────────────────────────────────────────

def pour_satellite(institution, environment) -> dict:
    """Le stock de l'institution du satellite : dépôts, articles, puis mouvements (dans cet ordre)."""
    from .models import ArticleStock, DepotStock, MouvementStock

    def lignes(modele, queryset):
        return [{"id": str(o.id), "environment": o.environment, **payload(o, modele)} for o in queryset]

    return {
        "depots": lignes("DepotStock", DepotStock.objects.filter(institution=institution, environment=environment)),
        "articles": lignes("ArticleStock", ArticleStock.objects.filter(institution=institution, environment=environment).select_related("catalogue")),
        "mouvements": lignes("MouvementStock", MouvementStock.objects.filter(article__institution=institution, environment=environment)
                             .order_by("date_creation")),
    }


def appliquer(donnees: dict) -> dict:
    """Sur le satellite : inscrit ce qui manque. Rien n'est écrasé : une ligne déjà là — venue du
    central ou créée sur place — reste telle quelle. Jamais tout ou rien."""
    import logging

    from django.apps import apps

    logger = logging.getLogger(__name__)
    compteurs = {"applique": 0, "ignore": 0, "erreur": 0}
    for cle, nom_modele in (("depots", "DepotStock"), ("articles", "ArticleStock"), ("mouvements", "MouvementStock")):
        Modele = apps.get_model("core", nom_modele)
        for item in (donnees or {}).get(cle) or []:
            try:
                if Modele.objects.filter(pk=item["id"]).exists():
                    compteurs["ignore"] += 1
                    continue
                champs = preparer(nom_modele, {c: v for c, v in item.items() if c not in ("id", "environment")})
                objet = Modele(id=item["id"], environment=item.get("environment", "PROD"), **champs)
                # Ce n'est pas une écriture locale à faire remonter (voir sync_outbox.enregistrer_evenement).
                objet._synchronisation_entrante = True
                objet.save()
                compteurs["applique"] += 1
            except Exception:
                logger.exception("Échec application entrante du stock %s %s", nom_modele, item.get("id"))
                compteurs["erreur"] += 1
    return compteurs
