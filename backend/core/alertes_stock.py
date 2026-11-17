"""Les alertes du stock, portées à ceux qui le tiennent au lieu d'attendre qu'ils viennent voir.

Avant, un seuil franchi, un lot périmé ou un prêt en retard ne se voyaient que sur la page
« Stocks ». Ce module en fait un relevé par institution, envoyé par les canaux de
`notifications_dons.prevenir` (site, application, courriel, salon Matrix des permanents).

**Un relevé ne part que s'il a changé.** La même liste tous les matins, personne ne la lit plus
au bout de trois jours : on garde l'empreinte du dernier relevé envoyé (`AlerteStockEnvoyee`) et
on ne réécrit que si quelque chose est apparu ou a disparu.

**À qui.** Aux membres du bureau de l'institution et à ceux qui ont enregistré un mouvement de
stock dans les quatre-vingt-dix derniers jours : ce sont eux qui tiennent le stock, pas tout
l'annuaire.
"""
import datetime
import hashlib

from django.utils import timezone

from . import stocks, stocks_echanges
from .models import AlerteStockEnvoyee, ContactInstitution, FactureStock, MouvementStock, PretMateriel, StatutPret, User

JOURS_ACTIVITE = 90


def releve(institution, environment, aujourd_hui=None) -> list[str]:
    """Les alertes du moment, une par ligne, dans un ordre stable."""
    aujourd_hui = aujourd_hui or timezone.localdate()
    lignes = []
    for article in stocks.etat(institution, environment, aujourd_hui=aujourd_hui):
        a = article["article"]
        if article["sous_seuil"]:
            lignes.append(f"Seuil franchi — {a.designation} : {stocks._nombre(article['total'])} {a.unite} en stock (seuil {stocks._nombre(a.seuil_alerte)}).")
        if article["perime"] > 0:
            lignes.append(f"Périmé — {a.designation} : {stocks._nombre(article['perime'])} {a.unite} à retirer.")
        if article["bientot_perime"] > 0:
            lignes.append(f"Bientôt périmé — {a.designation} : {stocks._nombre(article['bientot_perime'])} {a.unite} d'ici le "
                          f"{article['prochaine_peremption']:%d/%m/%Y}." if article["prochaine_peremption"] else
                          f"Bientôt périmé — {a.designation} : {stocks._nombre(article['bientot_perime'])} {a.unite}.")
        for lieu in article["mal_range"]:
            lignes.append(f"Denrée mal rangée — {a.designation} ({lieu['nom']}) : {' ; '.join(lieu['manques'])}.")
    prets = PretMateriel.objects.filter(institution=institution, environment=environment, statut=StatutPret.EN_COURS).select_related("tiers")
    for pret in prets:
        if stocks_echanges.en_retard(pret, aujourd_hui):
            sens = "prêté à" if pret.sens == "CONSENTI" else "prêté par"
            lignes.append(f"Prêt en retard — {pret.designation}, {sens} {pret.tiers.nom} : retour prévu le {pret.retour_prevu:%d/%m/%Y}.")
    factures = FactureStock.objects.filter(institution=institution, environment=environment, payee_le__isnull=True, echeance__lt=aujourd_hui)
    for facture in factures.select_related("tiers"):
        lignes.append(f"Facture échue — {facture.numero} ({facture.tiers.nom}), {facture.montant_ttc} € : échéance du {facture.echeance:%d/%m/%Y}.")
    from .models import AppareilStock, EtatAppareilStock
    bientot = aujourd_hui + datetime.timedelta(days=30)
    for appareil in AppareilStock.objects.filter(institution=institution, environment=environment).exclude(etat=EtatAppareilStock.REFORME):
        prochain = appareil.controle_prochain_le
        nom = appareil.designation + (f" (n° {appareil.numero})" if appareil.numero else "")
        if appareil.etat == EtatAppareilStock.EN_PANNE:
            lignes.append(f"Appareil en panne — {nom}.")
        if prochain is not None and prochain < aujourd_hui:
            lignes.append(f"Contrôle en retard — {nom} : {appareil.controle_libelle or 'contrôle périodique'} dû depuis le {prochain:%d/%m/%Y}.")
        elif prochain is not None and prochain <= bientot:
            lignes.append(f"Contrôle à prévoir — {nom} : {appareil.controle_libelle or 'contrôle périodique'} avant le {prochain:%d/%m/%Y}.")
    return sorted(lignes)


def destinataires(institution, environment) -> list:
    depuis = timezone.now() - datetime.timedelta(days=JOURS_ACTIVITE)
    actifs = MouvementStock.objects.filter(article__institution=institution, environment=environment, date_creation__gte=depuis,
                                           auteur__isnull=False).values_list("auteur_id", flat=True)
    bureau = ContactInstitution.objects.filter(institution=institution, actif=True, membre_bureau=True).values_list("utilisateur_id", flat=True)
    return list(User.objects.filter(pk__in={*actifs, *bureau}, is_active=True))


def envoyer(institution, environment, forcer=False, simuler=False) -> dict:
    """Envoie le relevé s'il a changé depuis le dernier (ou si `forcer`). Rend ce qui a été fait."""
    from .notifications_dons import prevenir

    lignes = releve(institution, environment)
    empreinte = hashlib.sha256("\n".join(lignes).encode()).hexdigest()
    dernier = AlerteStockEnvoyee.objects.filter(institution=institution, environment=environment).first()
    inchange = dernier is not None and dernier.empreinte == empreinte
    bilan = {"institution": institution.nom, "alertes": len(lignes), "envoye": False, "destinataires": 0}
    # Rien à dire et rien n'avait été dit : silence. Tout est rentré dans l'ordre : on le dit une fois.
    if (inchange and not forcer) or (not lignes and dernier is None):
        return bilan
    personnes = destinataires(institution, environment)
    bilan["destinataires"] = len(personnes)
    if simuler or not personnes:
        return bilan
    if lignes:
        titre = f"Stock de {institution.nom} : {len(lignes)} point(s) à voir"
        corps = "\n".join(f"- {ligne}" for ligne in lignes) + "\n\nCe relevé ne vous est renvoyé que s'il change."
    else:
        titre, corps = f"Stock de {institution.nom} : plus rien à signaler", "Les alertes du dernier relevé sont toutes levées."
    prevenir(de=institution, vers=institution, titre=titre, corps=corps, personnes=personnes, environment=environment)
    AlerteStockEnvoyee.objects.update_or_create(institution=institution, environment=environment,
                                                defaults={"empreinte": empreinte, "nombre": len(lignes)})
    bilan["envoye"] = True
    return bilan
