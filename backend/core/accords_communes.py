"""L'accord d'une institution sur une crise, **commune par commune** (17/11/2026).

Sur une crise qui touche plusieurs communes, une association agréée — ou la réserve communale
d'une autre commune venue en renfort — n'intervient chez un maire qu'avec son accord. Jusqu'ici
la déclaration n'avait qu'UN statut : la première mairie qui répondait la faisait passer à
« validée », et les autres ne pouvaient plus ni accepter chez elles, ni refuser.

L'état tient en deux listes sur `ImplicationInstitution`, sans second modèle :

- `communes` : où l'institution est acceptée. Avec le statut VALIDEE, une liste vide veut dire
  « toute la crise » — c'est le cas des institutions publiques, acceptées d'office, et d'une
  acceptation donnée par qui couvre la crise entière (un conseil départemental).
- `communes_refusees` : où une mairie a dit non.

Une commune de la crise absente des deux attend encore. Le statut se déduit : VALIDEE dès
qu'une commune est accordée, REFUSEE quand toutes ont refusé, EN_ATTENTE sinon. Les droits de
lecture, eux, ne changent pas de source : `zone_scoping.communes_accordees` lit `communes`.

Qui a accordé quoi est tracé en main courante par la vue, pas ici.
"""
from .models import StatutImplication, TypeImplication


def communes_de_la_crise(crise) -> list:
    return [c for c in (crise.zone_communes or []) if c]


def soumise_a_accord(implication) -> bool:
    """Cette déclaration dépend-elle de l'accord des communes ?

    Oui pour un acteur privé (association, entreprise), et pour une collectivité venue en
    renfort hors de chez elle. Non pour une institution publique sur son propre terrain : elle
    est acceptée d'office, et aucune mairie ne peut la récuser."""
    if implication.type_implication != TypeImplication.ACTEUR:
        return False
    if implication.renfort:
        return True
    from .views import _institution_est_publique
    return not _institution_est_publique(implication.institution)


def toute_la_crise(implication) -> bool:
    return implication.statut == StatutImplication.VALIDEE and not implication.communes


def etat(implication) -> dict:
    """Où en est la déclaration, commune par commune."""
    de_la_crise = communes_de_la_crise(implication.crise)
    if toute_la_crise(implication):
        return {"toute_la_crise": True, "acceptees": de_la_crise, "refusees": [], "en_attente": []}
    acceptees = [c for c in de_la_crise if c in set(implication.communes or [])]
    refusees = [c for c in de_la_crise if c in set(implication.communes_refusees or [])
                and c not in acceptees]
    decidees = set(acceptees) | set(refusees)
    return {
        "toute_la_crise": False,
        "acceptees": acceptees,
        "refusees": refusees,
        "en_attente": [c for c in de_la_crise if c not in decidees],
    }


def decider(implication, acceptees=(), refusees=(), tout=False) -> dict:
    """Enregistre la décision d'UNE collectivité. Rend ce qui a réellement changé.

    `tout` : l'appelant couvre la crise entière et l'accorde en bloc — on range alors une liste
    vide, qui reste juste si la crise s'étend ensuite à d'autres communes.

    Ne vérifie pas le droit de décider : c'est à l'appelant de n'apporter que des communes sur
    lesquelles le décideur a autorité (voir `zone_scoping.communes_delegables`)."""
    avant = etat(implication)
    etait_tout = avant["toute_la_crise"]

    if tout:
        implication.communes = []
        implication.communes_refusees = []
        implication.statut = StatutImplication.VALIDEE
        implication.save(update_fields=["communes", "communes_refusees", "statut"])
        return {
            "acceptees": sorted(set(avant["refusees"]) | set(avant["en_attente"])),
            "retirees": [], "tout": True,
        }

    acceptees, refusees = set(acceptees), set(refusees) - set(acceptees)
    # « Toute la crise » se déplie en liste dès qu'une commune s'en retire : on ne peut pas
    # dire « partout sauf ici » avec une liste vide.
    accordees = set(avant["acceptees"]) if etait_tout else set(implication.communes or [])
    non = set(implication.communes_refusees or [])

    ajoutees = sorted(acceptees - accordees)
    retirees = sorted(refusees & accordees)
    nouveaux_refus = sorted(refusees - non - accordees)

    accordees = (accordees | acceptees) - refusees
    non = (non | refusees) - acceptees

    if etait_tout and not retirees:
        # Rien ne s'est retiré : l'accord global reste global.
        return {"acceptees": [], "retirees": [], "refus": [], "tout": True}

    implication.communes = sorted(accordees)
    implication.communes_refusees = sorted(non)
    if accordees:
        implication.statut = StatutImplication.VALIDEE
    else:
        restantes = [c for c in communes_de_la_crise(implication.crise) if c not in non]
        # Une crise déclarée au département ne nomme aucune commune : un refus y est entier.
        implication.statut = (
            StatutImplication.EN_ATTENTE if restantes else StatutImplication.REFUSEE
        )
    implication.save(update_fields=["communes", "communes_refusees", "statut"])
    return {"acceptees": ajoutees, "retirees": retirees, "refus": nouveaux_refus, "tout": False}


def a_decider_par(request, implication) -> dict:
    """Ce que l'appelant peut encore décider sur cette déclaration : ses communes, triées
    selon ce qu'il en est. Vide s'il n'a autorité sur aucune commune de la crise."""
    from .zone_scoping import _memo, communes_delegables

    siennes = _memo(
        request, f"delegables:{implication.crise_id}",
        lambda: communes_delegables(request, implication.crise),
    )
    codes = [c["code"] for c in siennes]
    actuel = etat(implication)
    return {
        "communes": siennes,
        "en_attente": [c for c in codes if c in actuel["en_attente"]],
        "acceptees": [c for c in codes if c in actuel["acceptees"]],
        "refusees": [c for c in codes if c in actuel["refusees"]],
    }
