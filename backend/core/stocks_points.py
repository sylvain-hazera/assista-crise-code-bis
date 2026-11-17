"""Le stock d'un point d'accueil ou de regroupement, tenu par les mêmes mouvements que le stock
permanent (core/stocks.py).

Remarque de Sylvain du 17/11/2026 : « il y a un tout petit début dans le stock des points
d'accueil ; cette notion et leur utilisation doivent être fortement améliorées ». Jusqu'ici un
point avait une jauge posée à la main et des apports comptés à l'entrée ; rien n'était compté à
la sortie, et « demander un transfert » n'envoyait qu'un courriel.

Un point devient un LIEU DE STOCK : chaque institution qui y apporte du matériel y a un dépôt
(`DepotStock.point`). On dote le point depuis un dépôt (transfert), on y reçoit un don (entrée),
on y distribue (sortie), on rapatrie le reste à la fermeture (transfert retour). La ligne de
stock du point (`MaterielPoint`, une par besoin du catalogue) reste ce que l'équipe regarde :
sa quantité est recalculée ici à chaque mouvement.

La jauge (nul / faible / OK / en trop) reste un jugement de l'équipe ; on ne corrige que
l'évidence : zéro en stock est « nul », et une ligne « nulle » qui reçoit du stock devient « OK ».
"""
import re
import unicodedata

from django.db import transaction
from django.db.models import F, Sum

from . import stocks
from .models import (
    ArticleStock, ContributionMateriel, DepotStock, MaterielCatalogue, MaterielPoint, MouvementStock, NiveauStock,
    StatutMateriel, TypeMouvementStock,
)

ZERO = stocks.ZERO


def institution_du_point(point, a_defaut=None):
    """L'institution qui tient le point : celle de son équipe, à défaut celle de son responsable,
    à défaut `a_defaut` (celle de la personne qui agit)."""
    equipe = point.equipe
    if equipe is not None and equipe.institution_id:
        return equipe.institution
    responsable = point.responsable
    if responsable is not None and getattr(responsable, "institution_id", None):
        return responsable.institution
    return a_defaut


def depot_du_point(point, institution, environment):
    depot, _ = DepotStock.objects.get_or_create(
        institution=institution, point=point, environment=environment, defaults={"nom": f"Point — {point.nom}"[:120]})
    return depot


def _reference(nom: str) -> str:
    texte = unicodedata.normalize("NFKD", nom or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9]+", "-", texte).strip("-")[:50] or "ARTICLE"


def article_pour(item, institution, environment, unite="unité"):
    """L'article de l'institution qui correspond à ce besoin du catalogue ; créé au besoin."""
    article = ArticleStock.objects.filter(institution=institution, environment=environment, catalogue=item).order_by("date_creation").first()
    if article is not None:
        return article
    reference, n = _reference(item.nom), 1
    base = reference
    while ArticleStock.objects.filter(institution=institution, environment=environment, reference__iexact=reference).exists():
        n += 1
        reference = f"{base}-{n}"
    return ArticleStock.objects.create(institution=institution, environment=environment, reference=reference, designation=item.nom[:200],
                                       catalogue=item, categorie=item.categorie or "", unite=(unite or "unité")[:20])


def item_de(article):
    """Le besoin du catalogue auquel correspond l'article ; relié (ou créé) d'après son libellé."""
    if article.catalogue_id:
        return article.catalogue
    item = MaterielCatalogue.objects.filter(nom__iexact=article.designation[:100]).first() \
        or MaterielCatalogue.objects.create(nom=article.designation[:100], categorie=article.categorie or None)
    article.catalogue = item
    article.save(update_fields=["catalogue", "date_maj"])
    return item


def quantites(point) -> dict:
    """`{identifiant du besoin: quantité}` d'après le journal, pour les besoins qui y figurent."""
    lignes = MouvementStock.objects.filter(depot__point=point, article__catalogue__isnull=False).values(
        item=F("article__catalogue_id")).annotate(total=Sum("quantite"))
    return {ligne["item"]: ligne["total"] or ZERO for ligne in lignes}


def synchroniser(point, item, environment):
    """Reporte la quantité du journal sur la ligne de stock du point, et corrige la jauge quand
    elle contredit l'évidence."""
    total = MouvementStock.objects.filter(depot__point=point, article__catalogue=item).aggregate(t=Sum("quantite"))["t"] or ZERO
    ligne, _ = MaterielPoint.objects.get_or_create(point=point, item=item, defaults={"environment": environment})
    article = ArticleStock.objects.filter(mouvements__depot__point=point, catalogue=item).first()
    ligne.quantite = max(int(total), 0)
    if article is not None:
        ligne.unite = article.unite
    if total <= 0:
        ligne.niveau_stock = NiveauStock.NUL
    elif ligne.niveau_stock == NiveauStock.NUL:
        ligne.niveau_stock = NiveauStock.OK
    ligne.save(update_fields=["quantite", "unite", "niveau_stock", "date_maj"])
    return ligne


def _reprendre_les_apports(point, item, institution, environment, auteur, sauf=None):
    """Avant le premier mouvement d'une ligne : les apports déjà tracés (comptés à l'entrée
    seulement, avant le 17/11/2026) entrent au journal, pour que le total ne retombe pas."""
    if MouvementStock.objects.filter(depot__point=point, article__catalogue=item).exists():
        return
    apports = ContributionMateriel.objects.filter(materiel_point__point=point, materiel_point__item=item).exclude(statut=StatutMateriel.RETIRE)
    if sauf is not None:
        apports = apports.exclude(pk=sauf.pk)
    deja = apports.aggregate(t=Sum("quantite"))["t"] or 0
    if deja > 0:
        stocks.enregistrer(article=article_pour(item, institution, environment), depot=depot_du_point(point, institution, environment),
                           type_mouvement=TypeMouvementStock.ENTREE, quantite=deja, auteur=auteur, motif="Reprise des apports déjà tracés")


@transaction.atomic
def doter(*, point, article, source, quantite, auteur=None, lot="", date_peremption=None, motif=""):
    """Envoie du matériel d'un dépôt de l'institution vers le point : un vrai transfert."""
    item = item_de(article)
    _reprendre_les_apports(point, item, article.institution, article.environment, auteur)
    arrivee = depot_du_point(point, article.institution, article.environment)
    mouvements = stocks.transferer(article=article, source=source, destination=arrivee, quantite=quantite, auteur=auteur, lot=lot,
                                   date_peremption=date_peremption, motif=motif or f"Dotation du point « {point.nom} »", crise=point.crise)
    synchroniser(point, item, article.environment)
    return mouvements


@transaction.atomic
def recevoir(*, point, item, quantite, institution, environment, auteur=None, tiers="", unite="unité", apport=None):
    """Un don ou un apport reçu directement au point : une entrée au journal."""
    _reprendre_les_apports(point, item, institution, environment, auteur, sauf=apport)
    mouvement = stocks.enregistrer(
        article=article_pour(item, institution, environment, unite), depot=depot_du_point(point, institution, environment),
        type_mouvement=TypeMouvementStock.ENTREE, quantite=quantite, auteur=auteur, tiers=tiers, crise=point.crise,
        motif="Apport reçu au point")
    synchroniser(point, item, environment)
    return mouvement


@transaction.atomic
def distribuer(*, point, item, quantite, environment, auteur=None, motif="", tiers="", comme=None, lien=None):
    """Sort du stock du point ce qui est distribué ou consommé. Les lots qui périment le plus
    tôt partent les premiers ; si plusieurs institutions ont doté le point, on puise chez l'une
    puis chez l'autre."""
    quantite = stocks.decimal(quantite)
    if quantite <= 0:
        raise stocks.ErreurStock("Quantité distribuée : indiquez un nombre supérieur à zéro.")
    lignes = [l for l in MouvementStock.objects.filter(depot__point=point, article__catalogue=item).values(
        "article_id", "depot_id", "lot", "date_peremption").annotate(total=Sum("quantite")) if l["total"] > 0]
    disponible = sum((l["total"] for l in lignes), ZERO)
    if quantite > disponible:
        raise stocks.ErreurStock(
            f"Il n'y a que {stocks._nombre(disponible)} « {item.nom} » en stock sur ce point : on ne peut pas en distribuer "
            f"{stocks._nombre(quantite)}. Si le stock réel est différent, faites un inventaire du point.")
    lignes.sort(key=lambda l: (l["date_peremption"] is None, l["date_peremption"], l["lot"]))
    articles = {a.id: a for a in ArticleStock.objects.filter(pk__in={l["article_id"] for l in lignes})}
    depots = {d.id: d for d in DepotStock.objects.filter(pk__in={l["depot_id"] for l in lignes})}
    reste, mouvements = quantite, []
    for ligne in lignes:
        if reste <= 0:
            break
        part = min(reste, ligne["total"])
        mouvements.append(stocks.enregistrer(
            article=articles[ligne["article_id"]], depot=depots[ligne["depot_id"]], type_mouvement=TypeMouvementStock.SORTIE,
            quantite=part, auteur=auteur, lot=ligne["lot"], date_peremption=ligne["date_peremption"],
            motif=motif or "Distribution au point", tiers=tiers, crise=point.crise, comme=comme, lien=lien))
        reste -= part
    synchroniser(point, item, environment)
    return mouvements


@transaction.atomic
def transferer_entre_points(*, source, destination, item, quantite, environment, auteur=None, a_defaut=None, motif=""):
    """Envoie du stock d'un point à un autre : un vrai déplacement, là où « demander un
    transfert » n'envoyait qu'un courriel.

    **Le stock change de mains avec le point** (décision de Sylvain du 17/11/2026) : un don reçu
    à un point appartient à l'institution qui le tient, et « peut changer d'institution lors
    d'un transfert vers un autre point appartenant à une autre institution ». Ce qui arrive au
    point d'arrivée entre donc dans le stock de l'institution qui tient CE point ; le journal
    garde de qui ça vient. Lots et dates de péremption suivent."""
    import uuid

    if source.pk == destination.pk:
        raise stocks.ErreurStock("Le point d'arrivée est le même que celui de départ.")
    receveuse = institution_du_point(destination, a_defaut=a_defaut)
    if receveuse is None:
        raise stocks.ErreurStock("Le point d'arrivée n'est rattaché à aucune institution : affectez-lui une équipe.")
    libelle = motif or f"Transfert de « {source.nom} » vers « {destination.nom} »"
    lien, entrees = uuid.uuid4(), []
    sorties = distribuer(point=source, item=item, quantite=quantite, environment=environment, auteur=auteur, motif=libelle,
                         comme=TypeMouvementStock.TRANSFERT, lien=lien)
    arrivee = depot_du_point(destination, receveuse, environment)
    _reprendre_les_apports(destination, item, receveuse, environment, auteur)
    for sortie in sorties:
        donneuse = sortie.depot.institution
        article = sortie.article if donneuse.pk == receveuse.pk else article_pour(item, receveuse, environment, sortie.article.unite)
        if donneuse.pk != receveuse.pk and (article.conservation, article.preparation) != (sortie.article.conservation, sortie.article.preparation) \
                and not article.mouvements.exists():
            # L'article vient d'être créé chez la receveuse : il garde ce qu'on sait de la denrée.
            article.conservation, article.preparation, article.perissable = (
                sortie.article.conservation, sortie.article.preparation, sortie.article.perissable)
            article.save(update_fields=["conservation", "preparation", "perissable", "date_maj"])
        entrees.append(stocks.enregistrer(
            article=article, depot=arrivee, type_mouvement=TypeMouvementStock.ENTREE, quantite=-sortie.quantite, auteur=auteur,
            lot=sortie.lot, date_peremption=sortie.date_peremption, prix_unitaire=sortie.article.prix_unitaire,
            crise=destination.crise, tiers=donneuse.nom if donneuse.pk != receveuse.pk else "",
            motif=(libelle + (f" — passe de {donneuse.nom} à {receveuse.nom}" if donneuse.pk != receveuse.pk else ""))[:300],
            comme=TypeMouvementStock.TRANSFERT, lien=lien))
    synchroniser(destination, item, environment)
    return sorties, entrees


def denrees(point) -> dict:
    """`{identifiant du besoin: {conservation, preparation, manques}}` pour ce qui est en stock au
    point : ce qu'il faut pour le garder et le servir, et ce qui manque au point pour cela."""
    resultat = {}
    lignes = MouvementStock.objects.filter(depot__point=point, article__catalogue__isnull=False).values("article_id", "depot_id").annotate(
        total=Sum("quantite"))
    presents = [(l["article_id"], l["depot_id"]) for l in lignes if l["total"] > 0]
    articles = {a.id: a for a in ArticleStock.objects.filter(pk__in={a for a, _ in presents})}
    depots = {d.id: d for d in DepotStock.objects.filter(pk__in={d for _, d in presents}).select_related("point")}
    for article_id, depot_id in presents:
        article = articles[article_id]
        fiche = resultat.setdefault(article.catalogue_id, {"conservation": article.conservation, "preparation": article.preparation, "manques": []})
        for manque in stocks.manques_du_lieu(article, depots[depot_id]):
            if manque not in fiche["manques"]:
                fiche["manques"].append(manque)
    return resultat


@transaction.atomic
def compter(*, point, item, quantite, institution, environment, auteur=None):
    """Inventaire d'une ligne du point : ce qu'on a compté. L'écart est porté sur le dépôt de
    `institution` à ce point (lots confondus : au point on compte des cartons, pas des lots)."""
    quantite = stocks.decimal(quantite)
    if quantite < 0:
        raise stocks.ErreurStock("La quantité comptée ne peut pas être négative.")
    _reprendre_les_apports(point, item, institution, environment, auteur)
    actuel = quantites(point).get(item.id, ZERO)
    ecart = quantite - actuel
    if ecart > 0:
        stocks.enregistrer(article=article_pour(item, institution, environment), depot=depot_du_point(point, institution, environment),
                           type_mouvement=TypeMouvementStock.ENTREE, quantite=ecart, auteur=auteur, crise=point.crise,
                           motif="Inventaire du point : écart constaté", comme=TypeMouvementStock.INVENTAIRE)
    elif ecart < 0:
        distribuer(point=point, item=item, quantite=-ecart, environment=environment, auteur=auteur,
                   motif="Inventaire du point : écart constaté", comme=TypeMouvementStock.INVENTAIRE)
    return synchroniser(point, item, environment)


@transaction.atomic
def rapatrier(*, point, institution, destination, environment, auteur=None) -> int:
    """À la fermeture du point : tout ce que l'institution y a encore revient dans un de ses
    dépôts. Rend le nombre de lignes rapatriées."""
    depot = DepotStock.objects.filter(institution=institution, point=point, environment=environment).first()
    if depot is None:
        return 0
    lignes = [l for l in MouvementStock.objects.filter(depot=depot).values("article_id", "lot", "date_peremption").annotate(
        total=Sum("quantite")) if l["total"] > 0]
    articles = {a.id: a for a in ArticleStock.objects.filter(pk__in={l["article_id"] for l in lignes}).select_related("catalogue")}
    for ligne in lignes:
        article = articles[ligne["article_id"]]
        stocks.transferer(article=article, source=depot, destination=destination, quantite=ligne["total"], auteur=auteur,
                          lot=ligne["lot"], date_peremption=ligne["date_peremption"], motif=f"Retour du point « {point.nom} »")
        if article.catalogue_id:
            synchroniser(point, article.catalogue, environment)
    return len(lignes)
