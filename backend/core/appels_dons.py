"""Appels aux dons : dire précisément ce qu'il faut, et fermer chaque ligne quand elle est couverte.

Demande de Sylvain du 17/11/2026, après les incendies de l'été où des familles ont tout perdu :
« on fait un inventaire de ce dont on a besoin (vêtements, électroménager…), et des institutions
distantes peuvent consulter cet appel, prendre contact, organiser une collecte, la livraison […]
Ce doit être suffisamment précis en quantité pour pas que la moitié de la France collecte des
chauffe-biberons alors qu'il n'en faut qu'un. »

Quatre temps :

1. **Le besoin part des foyers.** On saisit qui compose un foyer (profil, âge, tailles), le
   trousseau proposé (`trousseau_pour`) se coche et s'ajuste, et le besoin de l'appel est la
   SOMME des foyers. Les foyers restent dans l'institution, chiffrés : l'appel ne porte que des
   lignes « T-shirt, homme, L : 14 ».
2. **Une ligne se ferme.** Une institution s'engage sur une quantité (`engager`) ; le reste à
   couvrir baisse aussitôt pour toutes les autres, et on ne peut pas s'engager au-delà. C'est
   LA règle du module : on ne promet pas ce qui est déjà promis.
3. **Un engagement qui ne part pas se relâche** (`relacher_les_retards`) : sans envoi annoncé
   passé le délai de l'appel, la part est rendue aux autres.
4. **À l'arrivée on compte** (`recevoir`) : ce qui est là entre en stock (core/stocks.py), au
   nom de l'institution qui a donné ; l'écart rouvre la ligne.

Visible des institutions qui ont un compte, pas du public : un appel public attire du vrac qu'il
faut ensuite trier, stocker et jeter.
"""
import datetime

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from . import stocks
from .models import (
    AppelAuxDons, ArticleStock, BesoinDon, BesoinFoyer, EngagementDon, EnvoiDon, FoyerSinistre, PublicDon, StatutAppelDons,
    StatutEngagementDon, StatutEnvoiDon, TypeMouvementStock,
)

ErreurStock = stocks.ErreurStock

# ── Le catalogue : ce qu'on peut demander, pour qui, dans quelles tailles ────────────────────

ADULTES = ["XS", "S", "M", "L", "XL", "XXL", "3XL"]
ENFANTS = ["2 ans", "3 ans", "4 ans", "5 ans", "6 ans", "8 ans", "10 ans", "12 ans", "14 ans", "16 ans"]
BEBES = ["Naissance", "1 mois", "3 mois", "6 mois", "9 mois", "12 mois", "18 mois", "24 mois"]
POINTURES_ADULTES = [str(p) for p in range(35, 49)]
POINTURES_ENFANTS = [str(p) for p in range(18, 40)]
COUCHES = ["Taille 1", "Taille 2", "Taille 3", "Taille 4", "Taille 5", "Taille 6"]
TOUS = [p.value for p in PublicDon]
GRANDS = ["HOMME", "FEMME", "GARCON", "FILLE"]

#: Une entrée : (désignation, publics concernés, « mesure » qui fixe la grille, neuf exigé, quantité du trousseau).
#: Mesure : « haut », « bas », « pointure », « couches », ou « » (pas de taille).
_VETEMENTS = [
    ("T-shirt", GRANDS, "haut", False, 4), ("Pull, sweat", GRANDS, "haut", False, 2), ("Chemise, chemisier", ["HOMME", "FEMME"], "haut", False, 1),
    ("Pantalon", GRANDS, "bas", False, 2), ("Short, jupe", GRANDS, "bas", False, 1), ("Manteau, blouson", GRANDS, "haut", False, 1),
    ("Pyjama", GRANDS, "haut", False, 2), ("Sous-vêtements (lot de 3)", GRANDS, "bas", True, 2), ("Soutien-gorge, brassière", ["FEMME", "FILLE"], "haut", True, 2),
    ("Chaussettes (lot de 3)", GRANDS, "pointure", True, 2), ("Chaussures", GRANDS, "pointure", False, 1), ("Chaussons", GRANDS, "pointure", False, 1),
    ("Body", ["BEBE"], "haut", True, 6), ("Pyjama, grenouillère", ["BEBE"], "haut", False, 4), ("Gilet, pull", ["BEBE"], "haut", False, 2),
    ("Pantalon, legging", ["BEBE"], "haut", False, 3), ("Combinaison, manteau", ["BEBE"], "haut", False, 1), ("Bonnet, chaussons", ["BEBE"], "haut", False, 2),
]
CATALOGUE = {
    "VETEMENTS": {"libelle": "Vêtements et chaussures", "articles": _VETEMENTS},
    "LINGE": {"libelle": "Linge et literie", "articles": [
        ("Serviette de toilette", [], "", False, 2), ("Parure de draps 1 personne", [], "", False, 1), ("Parure de draps 2 personnes", [], "", False, 1),
        ("Couette, couverture", [], "", False, 1), ("Oreiller", [], "", True, 1), ("Matelas 1 personne", [], "", False, 1), ("Matelas 2 personnes", [], "", False, 1),
        ("Torchons (lot)", [], "", False, 1)]},
    "PUERICULTURE": {"libelle": "Puériculture", "articles": [
        ("Couches (paquet)", ["BEBE"], "couches", True, 4), ("Biberons (lot)", ["BEBE"], "", True, 1), ("Chauffe-biberon", ["BEBE"], "", False, 1),
        ("Lit parapluie", ["BEBE"], "", False, 1), ("Poussette", ["BEBE"], "", False, 1), ("Siège auto", ["BEBE"], "", False, 1),
        ("Chaise haute", ["BEBE"], "", False, 1), ("Baignoire bébé", ["BEBE"], "", False, 1), ("Gigoteuse", ["BEBE"], "haut", False, 2),
        ("Lait infantile (boîte)", ["BEBE"], "", True, 2)]},
    "HYGIENE": {"libelle": "Hygiène", "articles": [
        ("Kit d'hygiène (savon, dentifrice, brosse, shampoing)", [], "", True, 1), ("Protections périodiques (paquet)", [], "", True, 2),
        ("Rasoirs, mousse", [], "", True, 1), ("Lessive", [], "", True, 1), ("Papier toilette (lot)", [], "", True, 1)]},
    "CUISINE": {"libelle": "Cuisine et vaisselle", "articles": [
        ("Kit vaisselle 4 personnes", [], "", False, 1), ("Batterie de casseroles et poêle", [], "", False, 1), ("Couverts (lot)", [], "", False, 1),
        ("Bouilloire", [], "", False, 1), ("Cafetière", [], "", False, 1)]},
    "ELECTROMENAGER": {"libelle": "Électroménager", "articles": [
        ("Réfrigérateur", [], "", False, 1), ("Plaque de cuisson", [], "", False, 1), ("Four à micro-ondes", [], "", False, 1),
        ("Lave-linge", [], "", False, 1), ("Aspirateur", [], "", False, 1), ("Radiateur d'appoint", [], "", False, 1), ("Fer à repasser", [], "", False, 1)]},
    "MOBILIER": {"libelle": "Mobilier", "articles": [
        ("Lit 1 personne", [], "", False, 1), ("Lit 2 personnes", [], "", False, 1), ("Table", [], "", False, 1), ("Chaise", [], "", False, 4),
        ("Armoire, commode", [], "", False, 1), ("Canapé", [], "", False, 1)]},
    "OUTILLAGE": {"libelle": "Outillage et bricolage", "articles": [
        ("Caisse à outils garnie", [], "", False, 1), ("Perceuse-visseuse", [], "", False, 1), ("Escabeau", [], "", False, 1),
        ("Outils de jardin (lot)", [], "", False, 1), ("Tondeuse", [], "", False, 1), ("Brouette", [], "", False, 1),
        ("Matériel de nettoyage (seaux, balais, raclettes)", [], "", False, 1), ("Rallonge, multiprise", [], "", False, 1),
        ("Lampe torche et piles", [], "", False, 1), ("Outillage professionnel (à décrire)", [], "", False, 1)]},
    "LOISIRS": {"libelle": "Jeux, jouets et loisirs", "articles": [
        ("Jouet, doudou", ["GARCON", "FILLE", "BEBE"], "", False, 1), ("Jeu de société", [], "", False, 1), ("Livres", TOUS, "", False, 3),
        ("Vélo", GRANDS, "", False, 1), ("Trottinette, draisienne", ["GARCON", "FILLE"], "", False, 1), ("Casque de vélo", GRANDS, "", False, 1),
        ("Ballon, jeux d'extérieur", ["GARCON", "FILLE"], "", False, 1), ("Matériel de dessin, loisirs créatifs", ["GARCON", "FILLE"], "", False, 1),
        ("Cartes à collectionner, figurines", ["GARCON", "FILLE"], "", False, 1), ("Console, jeux vidéo", GRANDS, "", False, 1),
        ("Instrument de musique", GRANDS, "", False, 1), ("Équipement de sport (à décrire)", GRANDS, "", False, 1),
        ("Télévision", [], "", False, 1), ("Ordinateur, tablette", [], "", False, 1)]},
    "ANIMAUX": {"libelle": "Animaux de compagnie", "articles": [
        ("Croquettes chien (sac)", [], "", True, 1), ("Croquettes chat (sac)", [], "", True, 1), ("Litière", [], "", True, 1),
        ("Panier, caisse de transport", [], "", False, 1), ("Laisse, collier, gamelles", [], "", False, 1)]},
    "SCOLAIRE": {"libelle": "École", "articles": [
        ("Cartable", ["GARCON", "FILLE"], "", False, 1), ("Fournitures scolaires (lot)", ["GARCON", "FILLE"], "", True, 1), ("Trousse garnie", ["GARCON", "FILLE"], "", True, 1)]},
    "DIVERS": {"libelle": "Autre", "articles": [
        ("Valise, sac de voyage", [], "", False, 1), ("Téléphone et chargeur", [], "", False, 1), ("Lunettes (à décrire)", TOUS, "", False, 1),
        ("Poussette, fauteuil, aide à la mobilité", [], "", False, 1)]},
}


def grille(public: str, mesure: str) -> list[str]:
    """Les tailles proposées pour un public et une mesure."""
    if mesure == "couches":
        return COUCHES
    if public == "BEBE":
        return BEBES if mesure in ("haut", "bas") else []
    enfant = public in ("GARCON", "FILLE")
    if mesure == "pointure":
        return POINTURES_ENFANTS if enfant else POINTURES_ADULTES
    if mesure in ("haut", "bas"):
        return (ENFANTS + ADULTES[:3]) if enfant else ADULTES
    return []


def urgence_de(quantite: int) -> int:
    """Ce qu'il faut tout de suite sur ce qu'il faut pour durer : la moitié, au moins une pièce.
    Deux T-shirts sur quatre permettent de passer les premiers jours."""
    return max(1, int(quantite) // 2)


def catalogue() -> list[dict]:
    """Le catalogue tel que l'écran le lit : familles, articles, publics, grilles de tailles."""
    return [{
        "famille": code, "libelle": famille["libelle"],
        "articles": [{"designation": designation, "publics": publics, "mesure": mesure, "neuf_exige": neuf, "quantite": quantite,
                      "quantite_urgence": urgence_de(quantite),
                      "tailles": {p: grille(p, mesure) for p in (publics or [""])} if mesure else {}}
                     for designation, publics, mesure, neuf, quantite in famille["articles"]],
    } for code, famille in CATALOGUE.items()]


def trousseau_pour(personne) -> list[dict]:
    """Ce qu'on propose pour une personne d'après son profil et ses tailles : à cocher, à ajuster."""
    tailles = {"haut": personne.taille_haut, "bas": personne.taille_bas or personne.taille_haut, "pointure": personne.pointure, "couches": ""}
    lignes = []
    for code in ("VETEMENTS", "PUERICULTURE", "SCOLAIRE"):
        for designation, publics, mesure, neuf, quantite in CATALOGUE[code]["articles"]:
            if personne.public not in publics:
                continue
            lignes.append({"famille": code, "designation": designation, "public": personne.public, "taille": tailles.get(mesure, "") if mesure else "",
                           "neuf_exige": neuf, "quantite": quantite, "quantite_urgence": urgence_de(quantite), "mesure": mesure})
    return lignes


# ── Foyers ───────────────────────────────────────────────────────────────────────────────────

def reference_de_foyer(institution, environment) -> str:
    rangs = [int(r[2:]) for r in FoyerSinistre.objects.filter(institution=institution, environment=environment).values_list("reference", flat=True)
             if r.startswith("F-") and r[2:].isdigit()]
    return f"F-{max(rangs, default=0) + 1:03d}"


def _cle(ligne) -> tuple:
    """Deux lignes se fondent si elles demandent la même chose. Un mot personnel (« son vélo
    rose ») garde sa ligne à part : c'est CE vélo qu'on cherche."""
    return (ligne.famille, ligne.designation, ligne.public, ligne.taille, (ligne.message or "").strip())


@transaction.atomic
def reprendre_les_foyers(appel) -> dict:
    """Pose sur l'appel la somme de ce qu'il manque encore aux foyers de la même crise (et de la
    même institution). Ne baisse jamais une ligne sous ce qui est déjà promis ou reçu."""
    foyers = FoyerSinistre.objects.filter(institution=appel.institution, environment=appel.environment)
    foyers = foyers.filter(crise=appel.crise) if appel.crise_id else foyers
    sommes: dict = {}
    for besoin in BesoinFoyer.objects.filter(foyer__in=foyers):
        manque = besoin.quantite - besoin.quantite_remise
        if manque > 0:
            entree = sommes.setdefault(_cle(besoin), {"quantite": 0, "neuf": False, "personnes": 0, "urgent": 0})
            entree["quantite"] += manque
            entree["personnes"] += 1           # une ligne de foyer = une personne (ou un foyer) à servir
            entree["urgent"] += max(min(besoin.quantite_urgence, besoin.quantite) - besoin.quantite_remise, 0)
            entree["neuf"] = entree["neuf"] or besoin.neuf_exige
    existantes = {_cle(b): b for b in appel.besoins.all()}
    creees = ajustees = 0
    for cle, somme in sommes.items():
        ligne = existantes.get(cle)
        if ligne is None:
            BesoinDon.objects.create(appel=appel, famille=cle[0], designation=cle[1], public=cle[2], taille=cle[3], message=cle[4][:300],
                                     neuf_exige=somme["neuf"], quantite_voulue=somme["quantite"], nb_beneficiaires=somme["personnes"],
                                     quantite_urgente=somme["urgent"])
            creees += 1
        else:
            voulue = max(somme["quantite"], couvert(ligne))
            nouveau = (voulue, ligne.neuf_exige or somme["neuf"], somme["personnes"], min(somme["urgent"], voulue))
            if nouveau != (ligne.quantite_voulue, ligne.neuf_exige, ligne.nb_beneficiaires, ligne.quantite_urgente):
                ligne.quantite_voulue, ligne.neuf_exige, ligne.nb_beneficiaires, ligne.quantite_urgente = nouveau
                ligne.save(update_fields=["quantite_voulue", "neuf_exige", "nb_beneficiaires", "quantite_urgente"])
                ajustees += 1
    return {"foyers": foyers.count(), "lignes_creees": creees, "lignes_ajustees": ajustees}


# ── Périmètre de l'appel ─────────────────────────────────────────────────────────────────────

#: Les portées proposées, en kilomètres. Aucune : toute la France.
PORTEES_KM = (50, 100, 200, 500)


def position_de(institution):
    """(longitude, latitude) de la commune d'une institution, ou None si on ne sait pas."""
    from .models import Commune
    if institution is None or not institution.commune_code:
        return None
    commune = Commune.objects.filter(code=institution.commune_code).first()
    if commune is None or commune.centre_latitude is None or commune.centre_longitude is None:
        return None
    return (commune.centre_longitude, commune.centre_latitude)


def centre_de(appel):
    """D'où se mesure la portée : le lieu de la crise, à défaut la commune de l'institution."""
    if appel.crise_id and appel.crise.location:
        return (appel.crise.location.x, appel.crise.location.y)
    return position_de(appel.institution)


def distance_km(a, b) -> float:
    """Distance à vol d'oiseau entre deux points (longitude, latitude)."""
    import math
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(h))


def distance_a(appel, institution):
    """À combien de kilomètres de l'appel se trouve cette institution ; None si on ne sait pas."""
    centre = (appel.centre.x, appel.centre.y) if appel.centre else None
    position = position_de(institution)
    return distance_km(centre, position) if centre and position else None


def a_portee(appel, institution) -> bool:
    """L'appel s'adresse-t-il à cette institution ? Oui s'il est national, ou si elle est dans le
    rayon. Oui aussi quand on ne sait pas la situer : on ne cache pas un appel par ignorance."""
    if appel.portee_km is None:
        return True
    distance = distance_a(appel, institution)
    return distance is None or distance <= appel.portee_km


def libelle_portee(appel) -> str:
    return f"dans un rayon de {appel.portee_km} km" if appel.portee_km else "dans toute la France"


# ── Engagements ──────────────────────────────────────────────────────────────────────────────

EN_COURS = (StatutEngagementDon.PROMIS, StatutEngagementDon.EXPEDIE)


def couvert(besoin) -> int:
    """Ce qui est reçu, plus ce qui est encore promis ou en route."""
    promis = besoin.engagements.filter(statut__in=EN_COURS).aggregate(t=Sum("quantite"))["t"] or 0
    return besoin.quantite_recue + promis


def reste(besoin) -> int:
    return max(besoin.quantite_voulue - couvert(besoin), 0)


def relacher_les_retards(appel=None, maintenant=None) -> int:
    """Rend aux autres les parts promises dont l'envoi n'a pas été annoncé dans le délai."""
    maintenant = maintenant or timezone.now()
    retards = EngagementDon.objects.filter(statut=StatutEngagementDon.PROMIS, expire_le__lt=maintenant)
    if appel is not None:
        retards = retards.filter(besoin__appel=appel)
    return retards.update(statut=StatutEngagementDon.RELACHE)


@transaction.atomic
def engager(besoin, institution, quantite, auteur=None) -> EngagementDon:
    """« J'en fournis `quantite` » : refusé au-delà de ce qui reste à couvrir."""
    besoin = BesoinDon.objects.select_for_update().select_related("appel").get(pk=besoin.pk)
    appel = besoin.appel
    if appel.statut != StatutAppelDons.OUVERT:
        raise ErreurStock("Cet appel n'est pas ouvert : on ne peut plus s'y engager.")
    if institution.pk == appel.institution_id:
        raise ErreurStock("C'est votre propre appel : ce que vous avez déjà se range dans votre stock, sans engagement.")
    if not a_portee(appel, institution):
        raise ErreurStock(f"Cet appel est lancé {libelle_portee(appel)} : votre institution est plus loin. Il sera élargi si le "
                          "besoin n'est pas couvert près du sinistre.")
    relacher_les_retards(appel)
    try:
        quantite = int(quantite)
    except (TypeError, ValueError):
        raise ErreurStock("Quantité : nombre entier attendu.")
    if quantite <= 0:
        raise ErreurStock("Engagez-vous sur au moins une pièce.")
    a_couvrir = reste(besoin)
    if a_couvrir == 0:
        raise ErreurStock(f"« {libelle(besoin)} » est déjà entièrement couvert : inutile d'en collecter.")
    if quantite > a_couvrir:
        raise ErreurStock(f"Il n'en reste que {a_couvrir} à couvrir pour « {libelle(besoin)} » : engagez-vous sur {a_couvrir} au plus.")
    return EngagementDon.objects.create(
        besoin=besoin, institution=institution, quantite=quantite, cree_par=auteur,
        expire_le=timezone.now() + datetime.timedelta(days=appel.delai_engagement_jours))


def libelle(besoin) -> str:
    morceaux = [besoin.designation, besoin.get_public_display().lower() if besoin.public else "", besoin.taille]
    return ", ".join(m for m in morceaux if m)


def pour_qui(besoin) -> str:
    """« pour 14 personnes », « pour 1 foyer » : c'est ainsi qu'un besoin se dit. Demander « 56
    T-shirts » fait oublier que ce sont quatorze personnes qui n'ont plus rien à se mettre."""
    nombre = max(besoin.nb_beneficiaires, 1)
    if besoin.public:
        nom = {"HOMME": ("homme", "hommes"), "FEMME": ("femme", "femmes"), "GARCON": ("garçon", "garçons"),
               "FILLE": ("fille", "filles"), "BEBE": ("bébé", "bébés")}[besoin.public]
        return f"pour {nombre} {nom[1] if nombre > 1 else nom[0]}"
    return f"pour {nombre} foyer{'s' if nombre > 1 else ''}"


def formulation(besoin) -> str:
    """La ligne telle qu'on la lit : « T-shirt, taille L — pour 14 hommes (56 pièces) »."""
    texte = besoin.designation + (f", taille {besoin.taille}" if besoin.taille else "")
    pieces = besoin.quantite_voulue
    detail = f" ({pieces} pièces)" if pieces != besoin.nb_beneficiaires else ""
    return f"{texte} — {pour_qui(besoin)}{detail}"


@transaction.atomic
def annoncer_un_envoi(appel, institution, engagements, *, date_expedition, arrivee_prevue=None, transporteur="", contact="",
                      commentaire="", auteur=None, environment=None) -> EnvoiDon:
    """L'institution dit ce qui part : ses engagements passent « expédié » et ne se relâchent plus."""
    engagements = list(EngagementDon.objects.select_for_update().filter(
        pk__in=engagements, institution=institution, besoin__appel=appel, statut=StatutEngagementDon.PROMIS))
    if not engagements:
        raise ErreurStock("Aucun de vos engagements en cours sur cet appel n'est désigné.")
    envoi = EnvoiDon.objects.create(
        appel=appel, institution=institution, date_expedition=date_expedition, arrivee_prevue=arrivee_prevue,
        transporteur=(transporteur or "")[:200], contact=contact or "", commentaire=commentaire or "", cree_par=auteur,
        environment=environment or appel.environment)
    EngagementDon.objects.filter(pk__in=[e.pk for e in engagements]).update(statut=StatutEngagementDon.EXPEDIE, envoi=envoi)
    return envoi


def _article_du_besoin(besoin, institution, environment):
    """L'article de stock qui correspond à une ligne d'appel ; créé à la première réception."""
    from .stocks_points import _reference
    reference = _reference(libelle(besoin))[:60]
    article = ArticleStock.objects.filter(institution=institution, environment=environment, reference__iexact=reference).first()
    return article or ArticleStock.objects.create(institution=institution, environment=environment, reference=reference,
                                                  designation=libelle(besoin)[:200], unite="pièce")


@transaction.atomic
def recevoir(envoi, comptes: dict, depot=None, auteur=None) -> list:
    """Réception d'un envoi par l'institution qui a lancé l'appel. `comptes` : {engagement: quantité
    comptée} ; un engagement absent est compté conforme. Ce qui est là entre en stock dans `depot`
    (s'il est donné) ; ce qui manque rouvre la ligne."""
    if envoi.statut != StatutEnvoiDon.ANNONCE:
        raise ErreurStock("Cet envoi est déjà réceptionné.")
    appel, mouvements = envoi.appel, []
    for engagement in envoi.engagements.select_for_update().select_related("besoin"):
        try:
            comptee = int(comptes.get(str(engagement.id), engagement.quantite))
        except (TypeError, ValueError):
            raise ErreurStock("Quantité comptée : nombre entier attendu.")
        if comptee < 0:
            raise ErreurStock("Une quantité comptée ne peut pas être négative.")
        besoin = engagement.besoin
        engagement.statut, engagement.quantite_recue = StatutEngagementDon.RECU, comptee
        engagement.save(update_fields=["statut", "quantite_recue"])
        besoin.quantite_recue += comptee
        besoin.save(update_fields=["quantite_recue"])
        if depot is not None and comptee > 0:
            mouvements.append(stocks.enregistrer(
                article=_article_du_besoin(besoin, appel.institution, appel.environment), depot=depot,
                type_mouvement=TypeMouvementStock.ENTREE, quantite=comptee, auteur=auteur, tiers=envoi.institution.nom,
                crise=appel.crise, motif=f"Don reçu — appel « {appel.titre} »"[:300]))
    envoi.statut, envoi.recu_le = StatutEnvoiDon.RECU, timezone.now()
    envoi.save(update_fields=["statut", "recu_le"])
    return mouvements


@transaction.atomic
def remettre(besoin_foyer, quantite, depot=None, auteur=None):
    """Remise à un foyer, sortie du stock si on dit d'où.

    Remettre n'est pas couvrir (remarque de Sylvain du 17/11/2026 : « remettre 3 T-shirts permet
    de passer quelques jours mais pas dans la durée »). Une remise ne ferme donc rien : la ligne
    est « à couvrir », puis « dépannée » quand le foyer a de quoi passer les premiers jours, puis
    « couverte » quand il a de quoi durer (`BesoinFoyer.etat`). On peut remettre en plusieurs
    fois, et remettre plus que prévu : c'est alors le besoin qui avait été sous-estimé, et il
    est relevé d'autant."""
    try:
        quantite = int(quantite)
    except (TypeError, ValueError):
        raise ErreurStock("Quantité : nombre entier attendu.")
    if quantite <= 0:
        raise ErreurStock("Indiquez combien de pièces sont remises.")
    foyer = besoin_foyer.foyer
    if depot is not None:
        from .stocks_points import _reference
        reference = _reference(", ".join(m for m in (besoin_foyer.designation, besoin_foyer.get_public_display().lower() if besoin_foyer.public else "",
                                                       besoin_foyer.taille) if m))[:60]
        article = ArticleStock.objects.filter(institution=foyer.institution, environment=foyer.environment, reference__iexact=reference).first()
        if article is None:
            raise ErreurStock("Cet article n'est pas dans votre stock : remettez-le sans indiquer de dépôt, ou faites-le d'abord entrer.")
        stocks.enregistrer(article=article, depot=depot, type_mouvement=TypeMouvementStock.SORTIE, quantite=quantite, auteur=auteur,
                           crise=foyer.crise, motif=f"Remis au foyer {foyer.reference}")
    besoin_foyer.quantite_remise += quantite
    besoin_foyer.quantite = max(besoin_foyer.quantite, besoin_foyer.quantite_remise)
    besoin_foyer.save(update_fields=["quantite_remise", "quantite"])
    return besoin_foyer


def a_rappeler(maintenant=None, avance_jours=2):
    """Les engagements promis, pas encore annoncés, qui seront relâchés d'ici `avance_jours` et
    dont le rappel n'est pas parti."""
    maintenant = maintenant or timezone.now()
    return EngagementDon.objects.filter(
        statut=StatutEngagementDon.PROMIS, rappel_envoye_le__isnull=True, expire_le__gt=maintenant,
        expire_le__lte=maintenant + datetime.timedelta(days=avance_jours),
        besoin__appel__statut=StatutAppelDons.OUVERT).select_related("besoin__appel__institution", "institution", "cree_par")


def avis_publics(environment) -> list[dict]:
    """Ce que tout le monde peut lire des appels ouverts : ce qu'il faut, pour combien de
    personnes, ce qui reste à couvrir, les mots personnels. Ni contact, ni lieu de livraison, ni
    qui s'est engagé : organiser une collecte passe par une institution du réseau, qui les voit."""
    relacher_les_retards()
    avis = []
    appels = AppelAuxDons.objects.filter(statut=StatutAppelDons.OUVERT, environment=environment).select_related(
        "institution", "crise").prefetch_related("besoins__engagements").order_by("-date_ouverture")
    for appel in appels:
        lignes = []
        for besoin in appel.besoins.all():
            promis = sum(e.quantite for e in besoin.engagements.all() if e.statut in EN_COURS)
            a_couvrir = max(besoin.quantite_voulue - besoin.quantite_recue - promis, 0)
            lignes.append({"famille": besoin.famille, "famille_libelle": CATALOGUE.get(besoin.famille, CATALOGUE["DIVERS"])["libelle"],
                           "formulation": formulation(besoin), "message": besoin.message, "neuf_exige": besoin.neuf_exige,
                           "reste": a_couvrir, "couvert": a_couvrir == 0, "urgent": besoin.quantite_urgente > besoin.quantite_recue})
        voulu = sum(b.quantite_voulue for b in appel.besoins.all())
        avis.append({"id": str(appel.id), "titre": appel.titre, "description": appel.description, "institution_nom": appel.institution.nom,
                     "crise_nom": appel.crise.name if appel.crise_id else None, "date_ouverture": appel.date_ouverture, "lignes": lignes,
                     "portee_km": appel.portee_km, "portee": libelle_portee(appel),
                     "latitude": round(appel.centre.y, 2) if appel.centre else None, "longitude": round(appel.centre.x, 2) if appel.centre else None,
                     "pieces_voulues": voulu, "pieces_restantes": sum(l["reste"] for l in lignes)})
    return avis
