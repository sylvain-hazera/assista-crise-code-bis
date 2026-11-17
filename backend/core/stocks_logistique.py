"""Ce qui organise le stock autour des besoins : demandes de transfert entre points, réservations,
dotations types, et « où est-ce qu'on en a ? ».

Suite du chantier des stocks (17/11/2026) :

- **Un transfert se demande** (`demander_un_transfert`, `accepter`, `refuser`). Ceux qui tiennent
  le point de départ décident, pour tout ou partie : ils peuvent en avoir besoin au dernier
  moment. C'est l'acceptation qui déplace le stock — jamais la demande.
- **Réserver** met du stock de côté sans le sortir (`reserver`, `servir`, `liberer`) : il reste
  compté dans le dépôt, mais une sortie pour quelqu'un d'autre ne peut plus le prendre.
- **Une dotation type** (sac d'intervention, caisse du véhicule) se vérifie, se sort et se
  rentre d'un geste (`verifier_un_lot`, `sortir_un_lot`, `rentrer_un_lot`).
- **Disponibilité** (`ou_trouver`) : pour un besoin du catalogue, ce que l'institution a, où, et
  ce qui en est libre.
"""
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from . import stocks, stocks_points
from .models import (
    ArticleStock, DemandeTransfertStock, DepotStock, MouvementStock, ReservationStock, StatutDemandeTransfert,
    StatutReservationStock, TypeMouvementStock,
)

ErreurStock = stocks.ErreurStock
ZERO = stocks.ZERO


# ── Demandes de transfert entre points ───────────────────────────────────────────────────────

def demander_un_transfert(*, source, destination, item, quantite, message="", auteur=None, environment) -> DemandeTransfertStock:
    if source.pk == destination.pk:
        raise ErreurStock("Le point d'arrivée est le même que celui de départ.")
    try:
        quantite = int(quantite)
    except (TypeError, ValueError):
        raise ErreurStock("Quantité : nombre entier attendu.")
    if quantite <= 0:
        raise ErreurStock("Demandez au moins une pièce.")
    return DemandeTransfertStock.objects.create(source=source, destination=destination, item=item, quantite=quantite,
                                                message=(message or "").strip()[:300], demande_par=auteur, environment=environment)


@transaction.atomic
def accepter(demande, *, quantite=None, reponse="", auteur=None, a_defaut=None) -> DemandeTransfertStock:
    """Ceux qui tiennent le point de départ acceptent, pour tout ou partie : le stock part alors."""
    demande = DemandeTransfertStock.objects.select_for_update().select_related("source", "destination", "item").get(pk=demande.pk)
    if demande.statut != StatutDemandeTransfert.DEMANDEE:
        raise ErreurStock("Cette demande a déjà reçu sa réponse.")
    try:
        accordee = demande.quantite if quantite in (None, "") else int(quantite)
    except (TypeError, ValueError):
        raise ErreurStock("Quantité accordée : nombre entier attendu.")
    if accordee <= 0 or accordee > demande.quantite:
        raise ErreurStock(f"Accordez entre 1 et {demande.quantite} pièce(s), ou refusez la demande.")
    stocks_points.transferer_entre_points(
        source=demande.source, destination=demande.destination, item=demande.item, quantite=accordee, environment=demande.environment,
        auteur=auteur, a_defaut=a_defaut, motif=f"Transfert demandé par « {demande.destination.nom} », accordé par « {demande.source.nom} »")
    demande.statut, demande.quantite_accordee = StatutDemandeTransfert.ACCEPTEE, accordee
    demande.reponse, demande.decide_par, demande.date_decision = (reponse or "").strip()[:300], auteur, timezone.now()
    demande.save()
    return demande


def refuser(demande, *, reponse="", auteur=None, annuler=False) -> DemandeTransfertStock:
    if demande.statut != StatutDemandeTransfert.DEMANDEE:
        raise ErreurStock("Cette demande a déjà reçu sa réponse.")
    demande.statut = StatutDemandeTransfert.ANNULEE if annuler else StatutDemandeTransfert.REFUSEE
    demande.reponse, demande.decide_par, demande.date_decision = (reponse or "").strip()[:300], auteur, timezone.now()
    demande.save()
    return demande


# ── Réservations ─────────────────────────────────────────────────────────────────────────────

@transaction.atomic
def reserver(*, article, depot, quantite, auteur=None, demande=None, equipe=None, pour="") -> ReservationStock:
    """Met de côté. Refusé au-delà de ce qui est libre dans le dépôt (stock moins déjà réservé)."""
    article = ArticleStock.objects.select_for_update().get(pk=article.pk)
    quantite = stocks.decimal(quantite)
    if quantite <= 0:
        raise ErreurStock("Réservez une quantité supérieure à zéro.")
    libre = stocks.quantite_en_stock(article, depot) - stocks.quantite_reservee(article, depot)
    if quantite > libre:
        raise ErreurStock(f"Il n'y a que {stocks._nombre(max(libre, ZERO))} {article.unite} de « {article.designation} » de libre dans "
                          f"« {depot.nom} » : on ne peut pas en réserver {stocks._nombre(quantite)}.")
    return ReservationStock.objects.create(article=article, depot=depot, quantite=quantite, auteur=auteur, demande=demande, equipe=equipe,
                                           pour=(pour or "").strip()[:200], environment=article.environment)


@transaction.atomic
def servir(reservation, auteur=None) -> ReservationStock:
    """La personne vient chercher : le stock réservé sort, la réservation est close."""
    if reservation.statut != StatutReservationStock.ACTIVE:
        raise ErreurStock("Cette réservation n'est plus active.")
    stocks.enregistrer(article=reservation.article, depot=reservation.depot, type_mouvement=TypeMouvementStock.SORTIE,
                       quantite=reservation.quantite, auteur=auteur, tiers=reservation.pour, equipe=reservation.equipe,
                       crise=reservation.demande.crisis if reservation.demande_id else None, motif="Réservation servie", reservation=reservation)
    reservation.statut, reservation.date_fin = StatutReservationStock.SERVIE, timezone.now()
    reservation.save(update_fields=["statut", "date_fin"])
    return reservation


def liberer(reservation) -> ReservationStock:
    if reservation.statut != StatutReservationStock.ACTIVE:
        raise ErreurStock("Cette réservation n'est plus active.")
    reservation.statut, reservation.date_fin = StatutReservationStock.ANNULEE, timezone.now()
    reservation.save(update_fields=["statut", "date_fin"])
    return reservation


def ou_trouver(institution, environment, item=None, recherche="") -> list[dict]:
    """« On l'a ? Où ? » : pour un besoin du catalogue (ou un mot), les articles de l'institution,
    dépôt par dépôt, avec ce qui est libre une fois les réservations déduites. Les stocks des
    points d'accueil y figurent : ils sont à l'institution aussi."""
    articles = ArticleStock.objects.filter(institution=institution, environment=environment, actif=True)
    if item is not None:
        articles = articles.filter(catalogue=item)
    cherche = (recherche or "").strip().casefold()
    if cherche:
        articles = [a for a in articles if cherche in f"{a.designation} {a.reference} {a.code_barres}".casefold()]
    articles = list(articles)
    depots = {d.id: d for d in DepotStock.objects.filter(institution=institution, environment=environment)}
    stock = {(m["article_id"], m["depot_id"]): m["t"] for m in MouvementStock.objects.filter(article__in=articles).values(
        "article_id", "depot_id").annotate(t=Sum("quantite"))}
    reserve = {(r["article_id"], r["depot_id"]): r["t"] for r in ReservationStock.objects.filter(
        article__in=articles, statut=StatutReservationStock.ACTIVE).values("article_id", "depot_id").annotate(t=Sum("quantite"))}
    rendu = []
    for article in sorted(articles, key=lambda a: a.designation.casefold()):
        lieux = [{"depot": str(d), "depot_nom": depots[d].nom, "au_point": bool(depots[d].point_id), "en_stock": quantite,
                  "reserve": reserve.get((article.id, d), ZERO), "libre": max(quantite - reserve.get((article.id, d), ZERO), ZERO)}
                 for (a, d), quantite in stock.items() if a == article.id and quantite > 0 and d in depots]
        rendu.append({"article": str(article.id), "designation": article.designation, "reference": article.reference, "unite": article.unite,
                      "libre": sum((l["libre"] for l in lieux), ZERO), "lieux": sorted(lieux, key=lambda l: l["depot_nom"].casefold())})
    return rendu


# ── Dotations types ──────────────────────────────────────────────────────────────────────────

def verifier_un_lot(lot, depot) -> list[dict]:
    """Ligne par ligne : ce que la dotation demande, ce qui est libre dans le dépôt, ce qui manque."""
    lignes = []
    for ligne in lot.lignes.select_related("article"):
        libre = stocks.quantite_en_stock(ligne.article, depot) - stocks.quantite_reservee(ligne.article, depot)
        lignes.append({"article": str(ligne.article_id), "designation": ligne.article.designation, "unite": ligne.article.unite,
                       "requis": ligne.quantite, "libre": max(libre, ZERO), "manque": max(ligne.quantite - libre, ZERO)})
    return lignes


@transaction.atomic
def sortir_un_lot(lot, depot, *, auteur=None, equipe=None, crise=None, motif="") -> list:
    """Sort toute la dotation, ou rien : un sac incomplet qui part sans qu'on le sache est pire
    qu'un sac qui ne part pas. Ce qui manque est dit, ligne par ligne."""
    manques = [l for l in verifier_un_lot(lot, depot) if l["manque"] > 0]
    if manques:
        raise ErreurStock("La dotation « " + lot.nom + " » n'est pas complète dans « " + depot.nom + " » : il manque "
                          + ", ".join(f"{stocks._nombre(m['manque'])} {m['unite']} de {m['designation']}" for m in manques) + ".")
    return [stocks.enregistrer(article=ligne.article, depot=depot, type_mouvement=TypeMouvementStock.SORTIE, quantite=ligne.quantite,
                               auteur=auteur, equipe=equipe, crise=crise, motif=(motif or f"Dotation « {lot.nom} »")[:300])
            for ligne in lot.lignes.select_related("article")]


@transaction.atomic
def rentrer_un_lot(lot, depot, *, quantites=None, auteur=None, equipe=None, motif="") -> list:
    """Retour de la dotation. `quantites` : {article: quantité revenue} ; à défaut, tout revient.
    Ce qui a été consommé ne revient pas : on dit ce qu'on a compté."""
    quantites = quantites or {}
    mouvements = []
    for ligne in lot.lignes.select_related("article"):
        revenue = stocks.decimal(quantites.get(str(ligne.article_id), ligne.quantite))
        if revenue < 0 or revenue > ligne.quantite:
            raise ErreurStock(f"« {ligne.article.designation} » : il en revient entre 0 et {stocks._nombre(ligne.quantite)}.")
        if revenue > 0:
            mouvements.append(stocks.enregistrer(article=ligne.article, depot=depot, type_mouvement=TypeMouvementStock.ENTREE, quantite=revenue,
                                                 auteur=auteur, equipe=equipe, motif=(motif or f"Retour de la dotation « {lot.nom} »")[:300]))
    return mouvements
