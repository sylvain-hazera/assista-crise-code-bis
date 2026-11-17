"""Gestion des stocks d'une institution : dépôts, articles, mouvements.

Demande de Sylvain du 17/11/2026 : « on s'attaque au chantier gestion des stocks pour me passer
de Dolibarr ». Ce module tient le stock PERMANENT d'une association ou d'une collectivité — ce
qu'elle possède, où, en quelle quantité, et ce qui en est sorti pour quoi. Il est distinct du
stock des points opérationnels (`MaterielPoint`), qui est la jauge d'un centre pendant une crise.

Trois règles :

- **Le stock ne se saisit pas, il se déduit.** Aucune colonne « quantité » ne se modifie : la
  quantité d'un article dans un dépôt est la somme de ses mouvements. Un mouvement ne se
  corrige ni ne se supprime ; une erreur se rattrape par un mouvement contraire ou par un
  inventaire. C'est ce qui permet de répondre à « où est passé ce carton ? ».
- **Une sortie ne rend jamais un stock négatif.** Si le compte n'y est pas, c'est le stock
  enregistré qui est faux : on le dit, et on fait un inventaire.
- **Un inventaire dit ce qu'on a compté**, pas un écart : le mouvement d'ajustement est calculé.

Les lots et dates de péremption sont facultatifs, ligne par ligne : un article sans lot se gère
en vrac. Le coût unitaire d'un article est un coût moyen pondéré, recalculé à chaque entrée
valorisée ; il n'a de valeur qu'indicative (ce n'est pas une comptabilité).
"""
import csv
import datetime
import io
import re
import unicodedata
import uuid
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import ArticleStock, DepotStock, MouvementStock, TypeMouvementStock

#: En deçà de ce délai, un lot est signalé « bientôt périmé ».
JOURS_ALERTE_PEREMPTION = 30
ZERO = Decimal("0")


class ErreurStock(Exception):
    """Un mouvement refusé, avec un message lisible par la personne qui le saisit."""


def decimal(valeur, champ="quantite") -> Decimal:
    """« 12,5 », « 1 234.50 », 3 -> Decimal. Lève ErreurStock sinon."""
    if isinstance(valeur, Decimal):
        return valeur
    texte = str(valeur if valeur is not None else "").strip().replace(" ", "").replace("\xa0", "").replace(" ", "")
    if "," in texte and "." in texte:
        texte = texte.replace(".", "") if texte.rfind(",") > texte.rfind(".") else texte.replace(",", "")
    texte = texte.replace(",", ".")
    try:
        nombre = Decimal(texte)
    except (InvalidOperation, ValueError):
        raise ErreurStock(f"{champ} : nombre attendu.")
    if not nombre.is_finite():
        raise ErreurStock(f"{champ} : nombre attendu.")
    return nombre


def quantite_reservee(article, depot=None, sauf=None) -> Decimal:
    """Ce qui est mis de côté (réservations actives), que personne d'autre ne doit sortir."""
    from .models import ReservationStock, StatutReservationStock
    reservations = ReservationStock.objects.filter(article=article, statut=StatutReservationStock.ACTIVE)
    if depot is not None:
        reservations = reservations.filter(depot=depot)
    if sauf is not None:
        reservations = reservations.exclude(pk=sauf.pk)
    return reservations.aggregate(total=Sum("quantite"))["total"] or ZERO


def quantite_en_stock(article, depot=None, lot=None, date_peremption=None) -> Decimal:
    """Ce qu'il y a, d'après les mouvements. `lot=None` : tous lots confondus."""
    mouvements = MouvementStock.objects.filter(article=article)
    if depot is not None:
        mouvements = mouvements.filter(depot=depot)
    if lot is not None:
        mouvements = mouvements.filter(lot=lot, date_peremption=date_peremption)
    return mouvements.aggregate(total=Sum("quantite"))["total"] or ZERO


@transaction.atomic
def enregistrer(*, article, depot, type_mouvement, quantite, auteur=None, lot="", date_peremption=None,
                prix_unitaire=None, motif="", tiers="", crise=None, mission=None, equipe=None, date_mouvement=None,
                reservation=None, comme=None, lien=None):
    """Enregistre une entrée, une sortie ou un inventaire, et rend le mouvement (None si un
    inventaire ne constate aucun écart).

    `quantite` est toujours positive : la quantité entrée, sortie, ou COMPTÉE (inventaire)."""
    if article.institution_id != depot.institution_id or article.environment != depot.environment:
        raise ErreurStock("Cet article et ce dépôt n'appartiennent pas à la même institution.")
    # Verrou sur l'article : deux sorties simultanées ne doivent pas se croire toutes deux servies.
    article = ArticleStock.objects.select_for_update().get(pk=article.pk)
    quantite = decimal(quantite)
    lot = (lot or "").strip()[:60]
    if quantite < 0:
        raise ErreurStock("La quantité ne peut pas être négative.")

    if type_mouvement == TypeMouvementStock.ENTREE:
        if quantite == 0:
            raise ErreurStock("Quantité entrée : indiquez un nombre supérieur à zéro.")
        variation = quantite
        if prix_unitaire is not None:
            prix_unitaire = decimal(prix_unitaire, "prix_unitaire")
            if prix_unitaire < 0:
                raise ErreurStock("Le prix ne peut pas être négatif.")
            avant = max(quantite_en_stock(article), ZERO)
            ancien = article.prix_unitaire if article.prix_unitaire is not None else prix_unitaire
            article.prix_unitaire = ((avant * ancien + quantite * prix_unitaire) / (avant + quantite)).quantize(Decimal("0.0001"))
            article.save(update_fields=["prix_unitaire", "date_maj"])
    elif type_mouvement == TypeMouvementStock.SORTIE:
        if quantite == 0:
            raise ErreurStock("Quantité sortie : indiquez un nombre supérieur à zéro.")
        disponible = quantite_en_stock(article, depot, lot if lot or date_peremption else None, date_peremption)
        # Ce qui est réservé pour quelqu'un reste dans le dépôt mais ne se sort pas pour un autre
        # (`reservation` : celle qu'on est justement en train de servir).
        reserve = quantite_reservee(article, depot, sauf=reservation)
        libre = quantite_en_stock(article, depot) - reserve
        if quantite <= disponible and quantite > libre:
            raise ErreurStock(
                f"Sur les {_nombre(quantite_en_stock(article, depot))} {article.unite} de « {article.designation} » du dépôt « {depot.nom} », "
                f"{_nombre(reserve)} sont réservés : il n'en reste que {_nombre(max(libre, ZERO))} à sortir. Servez ou annulez une réservation.")
        if quantite > disponible:
            ou = f" dans le lot « {lot} »" if lot else ""
            raise ErreurStock(
                f"Il n'y a que {_nombre(disponible)} {article.unite} de « {article.designation} »{ou} dans le dépôt "
                f"« {depot.nom} » : on ne peut pas en sortir {_nombre(quantite)}. Si le stock réel est différent, faites un inventaire.")
        variation = -quantite
    elif type_mouvement == TypeMouvementStock.INVENTAIRE:
        variation = quantite - quantite_en_stock(article, depot, lot, date_peremption)
        if variation == 0:
            return None
        prix_unitaire = None
    else:
        raise ErreurStock("Type de mouvement inconnu.")

    # `comme` / `lien` : le type sous lequel la ligne s'inscrit au journal (un transfert est une
    # sortie puis une entrée, inscrites « transfert » et liées). La ligne est écrite JUSTE du
    # premier coup, jamais retouchée : un satellite la remonte au central telle qu'elle naît.
    return MouvementStock.objects.create(
        article=article, depot=depot, type=comme or type_mouvement, transfert=lien, quantite=variation, lot=lot, date_peremption=date_peremption,
        prix_unitaire=prix_unitaire, motif=(motif or "").strip()[:300], tiers=(tiers or "").strip()[:200],
        crise=crise, mission=mission, equipe=equipe, auteur=auteur, environment=article.environment,
        date_mouvement=date_mouvement or timezone.now())


@transaction.atomic
def transferer(*, article, source, destination, quantite, auteur=None, lot="", date_peremption=None, motif="", crise=None):
    """Déplace une quantité d'un dépôt à un autre : deux mouvements liés, ou aucun."""
    if source.pk == destination.pk:
        raise ErreurStock("Le dépôt d'arrivée est le même que celui de départ.")
    if destination.institution_id != article.institution_id:
        raise ErreurStock("Le dépôt d'arrivée n'appartient pas à la même institution.")
    lien = uuid.uuid4()
    commun = {"article": article, "quantite": quantite, "auteur": auteur, "lot": lot, "date_peremption": date_peremption, "motif": motif,
              "crise": crise, "comme": TypeMouvementStock.TRANSFERT, "lien": lien}
    sortie = enregistrer(depot=source, type_mouvement=TypeMouvementStock.SORTIE, **commun)
    entree = enregistrer(depot=destination, type_mouvement=TypeMouvementStock.ENTREE, **commun)
    return sortie, entree


def manques_du_lieu(article, depot) -> list[str]:
    """Ce qui manque à ce lieu pour garder ou préparer cette denrée (vide : tout va bien).

    Demande de Sylvain du 17/11/2026 : tenir compte du stockage au froid et de la nécessité de
    cuisiner ou de réchauffer. On SIGNALE, on ne bloque pas : un mouvement constate ce qui s'est
    passé, et refuser de l'écrire ne remettrait pas le carton au frais.

    La préparation ne se juge qu'à un point d'accueil : c'est là qu'on sert. Un dépôt range."""
    from .models import ConservationStock, CuissonLieu, PreparationStock

    lieu, manques = depot.moyens, []
    if article.conservation == ConservationStock.FRAIS and not lieu.froid_positif:
        manques.append("à garder au frais, et ce lieu n'a pas de réfrigérateur")
    if article.conservation == ConservationStock.SURGELE and not lieu.froid_negatif:
        manques.append("surgelé, et ce lieu n'a pas de congélateur")
    if depot.point_id:
        if article.preparation == PreparationStock.A_RECHAUFFER and lieu.cuisson == CuissonLieu.AUCUNE:
            manques.append("à réchauffer, et ce point n'a rien pour chauffer")
        if article.preparation == PreparationStock.A_CUISINER and lieu.cuisson != CuissonLieu.CUISINE:
            manques.append("à cuisiner, et ce point n'a pas de cuisine")
    return manques


@transaction.atomic
def inventorier(depot, comptes: list[dict], articles: dict, auteur=None, motif="Inventaire du dépôt") -> dict:
    """Saisie d'un inventaire d'un bloc : `comptes` = [{article, quantite[, lot, date_peremption]}],
    une ligne par quantité COMPTÉE. Tout passe ou rien. Rend le nombre de lignes comptées et
    celles qui ont donné lieu à une correction."""
    corrections = []
    for compte in comptes or []:
        if compte.get("quantite") in (None, ""):
            continue                         # ligne laissée vide : pas comptée, pas corrigée
        article = articles.get(str(compte.get("article")))
        if article is None:
            raise ErreurStock("Une ligne désigne un article qui n'est pas dans votre stock.")
        peremption = _date(compte.get("date_peremption")) if compte.get("date_peremption") else None
        mouvement = enregistrer(article=article, depot=depot, type_mouvement=TypeMouvementStock.INVENTAIRE, quantite=compte["quantite"],
                                auteur=auteur, lot=compte.get("lot") or "", date_peremption=peremption, motif=motif)
        if mouvement is not None:
            corrections.append(mouvement)
    return {"comptees": sum(1 for c in comptes or [] if c.get("quantite") not in (None, "")), "corrections": corrections}


def _nombre(valeur: Decimal) -> str:
    """12.000 -> « 12 », 2.500 -> « 2,5 »."""
    texte = f"{valeur.normalize():f}" if valeur else "0"
    return texte.replace(".", ",")


def etat(institution, environment, depot=None, aujourd_hui=None) -> list[dict]:
    """L'état du stock d'une institution, article par article : quantité totale et par dépôt,
    alerte de seuil, lots périmés ou qui vont l'être, valeur indicative."""
    aujourd_hui = aujourd_hui or timezone.localdate()
    bientot = aujourd_hui + datetime.timedelta(days=JOURS_ALERTE_PEREMPTION)
    mouvements = MouvementStock.objects.filter(article__institution=institution, environment=environment)
    if depot is not None:
        mouvements = mouvements.filter(depot=depot)
    par_article: dict = {}
    for ligne in mouvements.values("article_id", "depot_id", "lot", "date_peremption").annotate(total=Sum("quantite")):
        if ligne["total"]:
            par_article.setdefault(ligne["article_id"], []).append(ligne)

    lignes = []
    from .models import ReservationStock, StatutReservationStock
    reserves = {r["article_id"]: r["t"] for r in ReservationStock.objects.filter(
        article__institution=institution, environment=environment, statut=StatutReservationStock.ACTIVE).values("article_id").annotate(t=Sum("quantite"))}
    lieux = {d.id: d for d in DepotStock.objects.filter(institution=institution, environment=environment).select_related("point")}
    articles = ArticleStock.objects.filter(institution=institution, environment=environment).order_by("designation")
    for article in articles:
        detail = par_article.get(article.id, [])
        par_depot: dict = {}
        lots, perime, a_surveiller, prochaine = [], ZERO, ZERO, None
        for ligne in detail:
            par_depot[ligne["depot_id"]] = par_depot.get(ligne["depot_id"], ZERO) + ligne["total"]
            if ligne["lot"] or ligne["date_peremption"]:
                lots.append({"depot": str(ligne["depot_id"]), "lot": ligne["lot"], "date_peremption": ligne["date_peremption"],
                             "quantite": ligne["total"]})
            echeance = ligne["date_peremption"]
            if echeance and ligne["total"] > 0:
                if echeance < aujourd_hui:
                    perime += ligne["total"]
                elif echeance <= bientot:
                    a_surveiller += ligne["total"]
                prochaine = echeance if prochaine is None or echeance < prochaine else prochaine
        total = sum(par_depot.values(), ZERO)
        if not article.actif and total == 0:
            continue
        reserve = reserves.get(article.id, ZERO)
        denree = [{"depot": str(d), "nom": lieux[d].nom, "manques": manques_du_lieu(article, lieux[d])}
                  for d, q in par_depot.items() if q > 0 and d in lieux]
        denree = [d for d in denree if d["manques"]]
        lignes.append({
            "article": article, "total": total,
            "par_depot": {str(d): q for d, q in par_depot.items() if q},
            "lots": sorted(lots, key=lambda l: (l["date_peremption"] or datetime.date.max, l["lot"])),
            "sous_seuil": article.seuil_alerte is not None and total <= article.seuil_alerte,
            "perime": perime, "bientot_perime": a_surveiller, "prochaine_peremption": prochaine,
            "mal_range": denree, "reserve": reserve, "disponible": max(total - reserve, ZERO),
            "valeur": (total * article.prix_unitaire).quantize(Decimal("0.01")) if article.prix_unitaire is not None and total > 0 else None,
        })
    return lignes


def bilan_de_crise(institution, crise, environment) -> dict:
    """Ce que le stock de l'institution a donné et reçu pour une crise : pour le rapport de crise,
    et pour une demande de remboursement ou de subvention. Les valeurs sont indicatives (coût
    moyen de l'article), et absentes quand l'article n'a pas de coût."""
    mouvements = MouvementStock.objects.filter(article__institution=institution, crise=crise, environment=environment).select_related("article")
    sorties, entrees = {}, {}
    for m in mouvements:
        if m.type == TypeMouvementStock.TRANSFERT:
            continue                       # un déplacement entre dépôts ou points : ni reçu ni donné
        cible = sorties if m.quantite < 0 else entrees
        ligne = cible.setdefault(m.article_id, {"article": m.article, "quantite": ZERO})
        ligne["quantite"] += abs(m.quantite)

    def lignes(cible):
        rendu, valeur = [], ZERO
        for ligne in sorted(cible.values(), key=lambda l: l["article"].designation.casefold()):
            a = ligne["article"]
            montant = (ligne["quantite"] * a.prix_unitaire).quantize(Decimal("0.01")) if a.prix_unitaire is not None else None
            valeur += montant or ZERO
            rendu.append({"designation": a.designation, "quantite": _nombre(ligne["quantite"]), "unite": a.unite, "valeur": montant})
        return rendu, valeur

    distribue, valeur_distribuee = lignes(sorties)
    recu, valeur_recue = lignes(entrees)
    return {"distribue": distribue, "valeur_distribuee": valeur_distribuee, "recu": recu, "valeur_recue": valeur_recue}


# ── Reprise d'un export (Dolibarr ou tableur) ────────────────────────────────────────────────

def _cle(titre: str) -> str:
    texte = unicodedata.normalize("NFKD", titre or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", texte).strip()


#: Titres de colonnes reconnus (exports Dolibarr en français et en anglais, tableurs maison).
COLONNES = {
    "reference": ("ref", "reference", "ref produit", "ref product", "product ref", "code", "code article"),
    "designation": ("libelle", "label", "designation", "nom", "produit", "product", "article", "product label", "libelle produit"),
    "quantite": ("stock", "stock physique", "physical stock", "quantite", "qte", "qty", "quantity", "stock reel", "real stock",
                 "units", "nombre"),
    "depot": ("entrepot", "warehouse", "depot", "emplacement", "lieu", "ref entrepot", "warehouse ref", "libelle entrepot",
              "warehouse label", "location"),
    "unite": ("unite", "unit"),
    "seuil": ("seuil", "seuil alerte", "seuil d alerte", "stock limite", "limite stock pour alerte", "stock limite pour alerte", "stock limit for alert",
              "stock alert", "alerte"),
    "prix": ("pmp", "prix", "prix unitaire", "cout", "weighted average price", "average price", "prix moyen pondere",
             "prix de revient", "cost price", "prix d achat"),
    "lot": ("lot", "numero de lot", "lot serie", "batch", "lot serial", "numero lot"),
    "peremption": ("peremption", "date de peremption", "dlc", "dluo", "ddm", "eat by", "sell by", "date peremption",
                   "eat by date", "sell by date", "expiration"),
    "code_barres": ("code barres", "code barre", "barcode", "ean", "gtin"),
    "categorie": ("categorie", "category", "famille"),
}
_PAR_TITRE = {titre: champ for champ, titres in COLONNES.items() for titre in titres}


def _date(texte: str):
    texte = (texte or "").strip()[:10]
    for forme in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.datetime.strptime(texte, forme).date()
        except ValueError:
            continue
    return None


def lire_tableau(contenu: bytes) -> tuple[list[str], list[dict]]:
    """Un CSV (virgule, point-virgule ou tabulation ; UTF-8 ou Latin-1) -> champs reconnus et lignes."""
    try:
        texte = contenu.decode("utf-8-sig")
    except UnicodeDecodeError:
        texte = contenu.decode("latin-1")
    premiere = texte.split("\n", 1)[0]
    separateur = max(";,\t", key=premiere.count)
    lecteur = csv.reader(io.StringIO(texte), delimiter=separateur)
    try:
        titres = next(lecteur)
    except StopIteration:
        raise ErreurStock("Le fichier est vide.")
    champs = [_PAR_TITRE.get(_cle(titre)) for titre in titres]
    if "designation" not in champs and "reference" not in champs:
        raise ErreurStock("Aucune colonne « Référence » ni « Libellé » reconnue dans la première ligne du fichier.")
    lignes = []
    for numero, valeurs in enumerate(lecteur, start=2):
        ligne = {champ: (valeurs[i] or "").strip() for i, champ in enumerate(champs) if champ and i < len(valeurs)}
        if any(ligne.values()):
            lignes.append({"_ligne": numero, **ligne})
    return [c for c in champs if c], lignes


def importer(contenu: bytes, institution, environment, auteur=None, depot_par_defaut=None, simuler=False) -> dict:
    """Reprend un export : crée les articles et dépôts qui manquent, et pose les quantités par
    un INVENTAIRE (rejouer le même fichier ne double donc rien). `simuler` : compte sans écrire."""
    champs, lignes = lire_tableau(contenu)
    bilan = {"colonnes": champs, "lignes": len(lignes), "articles_crees": 0, "articles_existants": 0, "depots_crees": 0,
             "quantites_posees": 0, "erreurs": [], "simulation": simuler}
    articles = {a.reference.casefold(): a for a in ArticleStock.objects.filter(institution=institution, environment=environment)}
    depots = {d.nom.casefold(): d for d in DepotStock.objects.filter(institution=institution, environment=environment)}

    with transaction.atomic():
        for ligne in lignes:
            try:
                designation = ligne.get("designation") or ligne.get("reference") or ""
                reference = (ligne.get("reference") or designation)[:60]
                if not reference:
                    raise ErreurStock("ni référence ni libellé")
                article = articles.get(reference.casefold())
                if article is None:
                    article = ArticleStock(
                        institution=institution, environment=environment, reference=reference, designation=designation[:200],
                        unite=(ligne.get("unite") or "unité")[:20], code_barres=(ligne.get("code_barres") or "")[:64],
                        seuil_alerte=decimal(ligne["seuil"], "seuil") if ligne.get("seuil") else None,
                        prix_unitaire=decimal(ligne["prix"], "prix") if ligne.get("prix") else None,
                        perissable=bool(ligne.get("peremption")))
                    if not simuler:
                        article.save()
                    articles[reference.casefold()] = article
                    bilan["articles_crees"] += 1
                else:
                    bilan["articles_existants"] += 1
                if not ligne.get("quantite"):
                    continue
                quantite = decimal(ligne["quantite"])
                if quantite < 0:
                    raise ErreurStock("quantité négative : à corriger dans le fichier ou par un inventaire")
                nom_depot = (ligne.get("depot") or "").strip()[:120]
                depot = depots.get(nom_depot.casefold()) if nom_depot else depot_par_defaut
                if depot is None and nom_depot:
                    depot = DepotStock(institution=institution, environment=environment, nom=nom_depot)
                    if not simuler:
                        depot.save()
                    depots[nom_depot.casefold()] = depot
                    bilan["depots_crees"] += 1
                if depot is None:
                    raise ErreurStock("pas de dépôt : ajoutez une colonne « Entrepôt » ou choisissez un dépôt par défaut")
                if not simuler:
                    enregistrer(article=article, depot=depot, type_mouvement=TypeMouvementStock.INVENTAIRE, quantite=quantite,
                                auteur=auteur, lot=ligne.get("lot") or "", date_peremption=_date(ligne.get("peremption")),
                                motif="Reprise d'un fichier")
                bilan["quantites_posees"] += 1
            except ErreurStock as erreur:
                bilan["erreurs"].append({"ligne": ligne["_ligne"], "message": str(erreur)})
    return bilan


def exporter(lignes: list[dict], depots: dict) -> str:
    """L'état du stock en CSV (point-virgule, pour un tableur français), une ligne par article et dépôt."""
    tampon = io.StringIO()
    sortie = csv.writer(tampon, delimiter=";")
    sortie.writerow(["Référence", "Libellé", "Entrepôt", "Stock", "Unité", "Seuil d'alerte", "Prix unitaire", "Catégorie", "Code-barres"])
    for ligne in lignes:
        article = ligne["article"]
        for depot_id, quantite in (ligne["par_depot"] or {"": ZERO}).items():
            sortie.writerow([
                article.reference, article.designation, depots.get(depot_id, ""), _nombre(quantite), article.unite,
                _nombre(article.seuil_alerte) if article.seuil_alerte is not None else "",
                _nombre(article.prix_unitaire) if article.prix_unitaire is not None else "",
                article.get_categorie_display() if article.categorie else "", article.code_barres])
    return "﻿" + tampon.getvalue()
