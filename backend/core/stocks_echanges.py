"""Ce que le stock échange avec l'extérieur : commandes aux fournisseurs, factures, prêts.

Demandes de Sylvain du 17/11/2026 : « commandes et factures : reprends » ; « prêt de matériel :
reprends-le, à double sens — un particulier ou un pro prête à l'institution, et l'institution
prête à un particulier ou un pro. Ces prêts doivent être tracés, avec si possible une fiche
d'état du matériel au début et au retour du prêt, et des photos ».

Tout passe par le journal de stock (core/stocks.py) : recevoir une commande, c'est une entrée ;
prêter un article du stock, c'est une sortie, et son retour une entrée. Rien ici ne modifie une
quantité autrement.

Ce n'est pas une comptabilité : une facture est une pièce rangée avec sa commande (numéro,
montants, échéance, date de paiement), pas une écriture.
"""
import datetime

from django.db import transaction
from django.utils import timezone

from . import stocks
from .models import (
    CommandeStock, EtatMaterielPrete, LigneCommandeStock, PretMateriel, SensPret, StatutCommandeStock, StatutPret,
    TypeMouvementStock,
)

ErreurStock = stocks.ErreurStock


# ── Commandes ────────────────────────────────────────────────────────────────────────────────

def numero_de_commande(institution, environment, aujourd_hui=None) -> str:
    """« CF-2026-0007 » : le suivant de l'année pour cette institution."""
    annee = (aujourd_hui or timezone.localdate()).year
    prefixe = f"CF-{annee}-"
    derniers = CommandeStock.objects.filter(institution=institution, environment=environment, numero__startswith=prefixe).values_list(
        "numero", flat=True)
    rang = max((int(n[len(prefixe):]) for n in derniers if n[len(prefixe):].isdigit()), default=0) + 1
    return f"{prefixe}{rang:04d}"


def poser_les_lignes(commande, lignes, articles) -> None:
    """Remplace les lignes d'une commande encore en brouillon. `articles` : ceux de l'institution,
    par identifiant."""
    if commande.statut != StatutCommandeStock.BROUILLON:
        raise ErreurStock("Cette commande est partie : ses lignes ne se modifient plus. Annulez-la et refaites-en une.")
    nouvelles = []
    for ligne in lignes or []:
        article = articles.get(str(ligne.get("article")))
        if article is None:
            raise ErreurStock("Une ligne désigne un article qui n'est pas dans votre stock.")
        quantite = stocks.decimal(ligne.get("quantite"))
        if quantite <= 0:
            raise ErreurStock(f"« {article.designation} » : la quantité commandée doit être supérieure à zéro.")
        prix = ligne.get("prix_unitaire")
        prix = stocks.decimal(prix, "prix_unitaire") if prix not in (None, "") else None
        if prix is not None and prix < 0:
            raise ErreurStock("Un prix ne peut pas être négatif.")
        nouvelles.append(LigneCommandeStock(commande=commande, article=article, quantite=quantite, prix_unitaire=prix))
    commande.lignes.all().delete()
    LigneCommandeStock.objects.bulk_create(nouvelles)


def total_de(commande):
    """Montant de la commande d'après ses lignes valorisées ; None si aucune ne l'est."""
    montants = [l.quantite * l.prix_unitaire for l in commande.lignes.all() if l.prix_unitaire is not None]
    return sum(montants, stocks.ZERO).quantize(stocks.Decimal("0.01")) if montants else None


@transaction.atomic
def recevoir(commande, receptions, depot, auteur=None) -> list:
    """Réception, totale ou partielle : `receptions` = [{ligne, quantite[, lot, date_peremption]}].
    Chaque quantité reçue entre en stock au prix de la ligne."""
    if commande.statut not in (StatutCommandeStock.COMMANDEE, StatutCommandeStock.RECUE_EN_PARTIE):
        raise ErreurStock("Seule une commande passée (et pas encore entièrement reçue) se réceptionne.")
    if depot is None:
        raise ErreurStock("Indiquez le dépôt où ranger ce qui est reçu.")
    lignes = {str(l.id): l for l in commande.lignes.select_related("article")}
    mouvements = []
    for reception in receptions or []:
        ligne = lignes.get(str(reception.get("ligne")))
        if ligne is None:
            raise ErreurStock("Une réception désigne une ligne qui n'est pas dans cette commande.")
        quantite = stocks.decimal(reception.get("quantite"))
        if quantite == 0:
            continue
        if quantite < 0:
            raise ErreurStock("Une quantité reçue ne peut pas être négative.")
        peremption = stocks._date(reception.get("date_peremption")) if reception.get("date_peremption") else None
        mouvements.append(stocks.enregistrer(
            article=ligne.article, depot=depot, type_mouvement=TypeMouvementStock.ENTREE, quantite=quantite, auteur=auteur,
            lot=reception.get("lot") or "", date_peremption=peremption, prix_unitaire=ligne.prix_unitaire,
            tiers=commande.tiers.nom, motif=f"Réception de la commande {commande.numero}"))
        ligne.quantite_recue += quantite
        ligne.save(update_fields=["quantite_recue"])
    if not mouvements:
        raise ErreurStock("Indiquez au moins une quantité reçue.")
    tout_recu = all(l.quantite_recue >= l.quantite for l in lignes.values())
    commande.statut = StatutCommandeStock.RECUE if tout_recu else StatutCommandeStock.RECUE_EN_PARTIE
    commande.save(update_fields=["statut"])
    return mouvements


# ── Prêts ────────────────────────────────────────────────────────────────────────────────────

def en_retard(pret, aujourd_hui=None) -> bool:
    return pret.statut == StatutPret.EN_COURS and pret.retour_prevu is not None and pret.retour_prevu < (aujourd_hui or timezone.localdate())


def _mouvement_de_pret(pret, depart: bool, quantite, auteur):
    """Le mouvement de stock d'un prêt qui porte sur un article du stock ; rien sinon."""
    if pret.article_id is None or pret.depot_id is None or quantite <= 0:
        return None
    # Prêt consenti : sort au départ, rentre au retour. Prêt reçu : l'inverse.
    sort = depart == (pret.sens == SensPret.CONSENTI)
    libelle = ("Prêt à " if pret.sens == SensPret.CONSENTI else "Prêt de ") + pret.tiers.nom
    return stocks.enregistrer(
        article=pret.article, depot=pret.depot, type_mouvement=TypeMouvementStock.SORTIE if sort else TypeMouvementStock.ENTREE,
        quantite=quantite, auteur=auteur, tiers=pret.tiers.nom, crise=pret.crise,
        motif=(libelle if depart else "Retour — " + libelle.lower())[:300])


@transaction.atomic
def ouvrir(pret, auteur=None):
    """Enregistre un prêt qui commence, et fait bouger le stock s'il porte sur un article."""
    if pret.quantite <= 0:
        raise ErreurStock("La quantité prêtée doit être supérieure à zéro.")
    if pret.article_id and not pret.depot_id:
        raise ErreurStock("Indiquez le dépôt : celui d'où l'article sort, ou celui où il est rangé le temps du prêt.")
    if pret.article_id and not pret.designation:
        pret.designation = pret.article.designation
    if not pret.designation:
        raise ErreurStock("Dites ce qui est prêté.")
    if pret.retour_prevu and pret.retour_prevu < pret.date_debut:
        raise ErreurStock("Le retour prévu précède le début du prêt.")
    pret.cree_par = auteur
    pret.save()
    _mouvement_de_pret(pret, True, pret.quantite, auteur)
    return pret


@transaction.atomic
def rendre(pret, *, etat_retour, constat_retour="", quantite_rendue=None, date_retour=None, auteur=None):
    """Clôt un prêt par sa fiche de retour. Rendu en moins bon état qu'au départ, ou en moindre
    quantité : le prêt est « rendu avec réserve », et la fiche dit pourquoi."""
    if pret.statut != StatutPret.EN_COURS:
        raise ErreurStock("Ce prêt est déjà rendu.")
    if etat_retour not in EtatMaterielPrete.values:
        raise ErreurStock("Indiquez l'état du matériel au retour.")
    rendue = pret.quantite if quantite_rendue in (None, "") else stocks.decimal(quantite_rendue, "quantite_rendue")
    if rendue < 0 or rendue > pret.quantite:
        raise ErreurStock("La quantité rendue ne peut ni être négative ni dépasser la quantité prêtée.")
    ordre = list(EtatMaterielPrete.values)
    abime = ordre.index(etat_retour) > ordre.index(pret.etat_depart)
    pret.etat_retour, pret.constat_retour = etat_retour, (constat_retour or "").strip()
    pret.quantite_rendue = rendue
    pret.date_retour = date_retour or timezone.localdate()
    if pret.date_retour < pret.date_debut:
        raise ErreurStock("Le retour ne peut pas précéder le début du prêt.")
    pret.statut = StatutPret.LITIGE if (abime or rendue < pret.quantite) else StatutPret.RENDU
    pret.rendu_par = auteur
    pret.save()
    _mouvement_de_pret(pret, False, rendue, auteur)
    return pret


def resume(pret, nommer, photos_de) -> dict:
    """Ce que dit la fiche de prêt (PDF). `photos_de(moment)` rend les photos « DEPART » / « RETOUR »."""
    jour = lambda d: d.strftime("%d/%m/%Y") if d else ""        # noqa: E731
    return {
        "designation": pret.designation, "identification": pret.identification or "", "sens": pret.get_sens_display(),
        "consenti": pret.sens == SensPret.CONSENTI, "institution": pret.institution.nom,
        "tiers": pret.tiers.nom, "tiers_type": pret.tiers.get_type_display(),
        "tiers_contact": " — ".join(m for m in (pret.tiers.contact, pret.tiers.telephone, pret.tiers.email) if m),
        "quantite": stocks._nombre(pret.quantite), "unite": pret.article.unite if pret.article_id else "",
        "quantite_rendue": stocks._nombre(pret.quantite_rendue) if pret.quantite_rendue is not None else "",
        "debut": jour(pret.date_debut), "retour_prevu": jour(pret.retour_prevu), "retour": jour(pret.date_retour),
        "etat_depart": pret.get_etat_depart_display(), "constat_depart": pret.constat_depart or "",
        "etat_retour": pret.get_etat_retour_display() if pret.etat_retour else "", "constat_retour": pret.constat_retour or "",
        "statut": pret.get_statut_display(), "rendu": pret.statut != StatutPret.EN_COURS, "reserve": pret.statut == StatutPret.LITIGE,
        "en_retard": en_retard(pret), "conditions": pret.conditions or "", "crise": pret.crise.name if pret.crise_id else "",
        "enregistre_par": nommer(pret.cree_par) if pret.cree_par_id else "", "rendu_a": nommer(pret.rendu_par) if pret.rendu_par_id else "",
        "photos_depart": photos_de("DEPART"), "photos_retour": photos_de("RETOUR"),
    }
