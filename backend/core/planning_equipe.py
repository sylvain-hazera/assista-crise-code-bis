"""Planning d'équipe : qui tient quel créneau, et ce qui cloche quand on l'écrit.

Demande de Sylvain du 12/11/2026 : « vas-y, prévois le planning d'équipe et tout le
nécessaire ». Jusque-là, pointer un créneau à la main dans la grille de l'association ne
laissait qu'une ligne au journal d'audit hors campagne — aucune table ne savait dire « cette
équipe tient le soir du 14 ».

**Ce module ne décide pas, il avertit.** Trois écarts sont détectés à chaque écriture, et
aucun n'est bloquant — sauf le dernier, qui ne peut pas l'être :

1. **Double engagement** : la même personne, le même créneau, dans une AUTRE équipe. Ce n'est
   pas un oubli de saisie, c'est quelqu'un qu'on attend à deux endroits. Signalé, nommé, mais
   pas refusé : il existe des cas réels (une personne qui passe d'un poste à l'autre dans la
   même demi-journée, deux équipes du même site). C'est au chef d'équipe de trancher, pas au
   serveur — mais il doit le SAVOIR.
2. **Hors disponibilité déclarée** : la personne n'a pas coché ce créneau. Un chef d'équipe a
   le droit d'appeler ; l'interdire supposerait que la grille déclarée est exhaustive, ce
   qu'elle n'est pas. Signalé pour qu'on sache qu'il faudra un coup de fil.
3. **Pas membre de l'équipe** : refusé, lui. Un planning qui affecte des gens qui ne sont pas
   dans l'équipe ne décrit plus rien.

**L'effectif d'un créneau ne compte ni les annulés ni les absents.** C'est la seule définition
qui rende le chiffre utilisable : compter une ligne annulée ferait croire une garde armée.
"""
import datetime

from django.utils import timezone

#: Fenêtre par défaut d'un planning. Quatorze jours : deux semaines se tiennent à l'écran et
#: couvrent le cycle d'une garde, là où un mois force à défiler pour rien.
JOURS_PLANNING = 14
#: Plafond. Au-delà, ce n'est plus un planning qu'on lit, c'est un export.
PLAFOND_JOURS_PLANNING = 62


def _creneaux_ordonnes():
    from .grille_disponibilites import CRENEAUX_ORDONNES

    return list(CRENEAUX_ORDONNES)


def doubles_engagements(equipe, demandes, request=None):
    """Les créneaux déjà tenus par ces personnes DANS UNE AUTRE ÉQUIPE.

    `demandes` : itérable de `(utilisateur_id, date, creneau)`. Rend une liste de dictionnaires
    nommant la personne, le créneau et l'équipe concurrente — jamais un simple compteur : « 3
    conflits » n'a jamais permis à personne de décider quoi que ce soit.

    `request` n'est pas facultative en pratique : sans elle, `nom_affichable` rend le VRAI nom
    même en zone de démonstration (voir sa docstring), et ces listes afficheraient les noms de
    vraies personnes dans la démo."""
    from .models import CreneauEquipe, StatutCreneauEquipe
    from .permissions import nom_affichable

    demandes = list(demandes)
    if not demandes:
        return []

    dates = {jour for _, jour, _ in demandes}
    utilisateurs = {str(u) for u, _, _ in demandes}
    cherches = {(str(u), jour, creneau) for u, jour, creneau in demandes}

    conflits = []
    existants = CreneauEquipe.objects.filter(
        utilisateur_id__in=utilisateurs, date__in=dates,
    ).exclude(
        equipe_id=equipe.id,
    ).exclude(
        statut__in=[StatutCreneauEquipe.ANNULE, StatutCreneauEquipe.ABSENT],
    ).select_related("equipe", "utilisateur")

    for ligne in existants:
        cle = (str(ligne.utilisateur_id), ligne.date, ligne.creneau)
        if cle not in cherches:
            continue
        conflits.append({
            "utilisateur": str(ligne.utilisateur_id),
            "nom": nom_affichable(ligne.utilisateur, request) or ligne.utilisateur.email,
            "date": ligne.date.isoformat(),
            "creneau": ligne.creneau,
            "equipe": str(ligne.equipe_id),
            "equipe_nom": ligne.equipe.name,
            "motif": f"Déjà engagé sur ce créneau dans l'équipe « {ligne.equipe.name} ».",
        })
    return conflits


def hors_disponibilite(institution, demandes, environnement, request=None):
    """Les créneaux affectés que la personne n'a PAS déclarés.

    Lus sur le moteur unique (`DisponibiliteOffre`, porté par la ressource du bénévole), le
    même que la grille et la constitution d'équipe. Ce n'est pas une erreur — c'est un coup de
    téléphone à passer, et le taire reviendrait à faire partir une garde sur une présence que
    personne n'a confirmée."""
    from .fiches_benevoles import TYPE_OFFRE_BENEVOLE
    from .models import DisponibiliteOffre, Offer
    from .permissions import nom_affichable
    from .models import User

    demandes = list(demandes)
    if not demandes or institution is None:
        return []

    utilisateurs = {str(u) for u, _, _ in demandes}
    dates = {jour for _, jour, _ in demandes}

    ressources = dict(
        Offer.objects.filter(
            author_id__in=utilisateurs, institution=institution,
            offer_type__type=TYPE_OFFRE_BENEVOLE, environment=environnement,
        ).values_list("id", "author_id")
    )
    declares = set()
    for jour, creneau, offre_id in DisponibiliteOffre.objects.filter(
            offer_id__in=ressources.keys(), date__in=dates,
    ).values_list("date", "creneau", "offer_id"):
        auteur = ressources.get(offre_id)
        if auteur is not None:
            declares.add((str(auteur), jour, creneau))

    noms = {
        str(u.id): nom_affichable(u, request) or u.email
        for u in User.objects.filter(id__in=utilisateurs)
    }
    ecarts = []
    for utilisateur, jour, creneau in demandes:
        if (str(utilisateur), jour, creneau) in declares:
            continue
        ecarts.append({
            "utilisateur": str(utilisateur),
            "nom": noms.get(str(utilisateur), str(utilisateur)),
            "date": jour.isoformat(),
            "creneau": creneau,
            "motif": "N'a pas déclaré ce créneau : à confirmer avec la personne.",
        })
    return ecarts


def planning(equipe, debut=None, jours=None, environnement=None, request=None):
    """Le planning d'une équipe, prêt à afficher : jours en colonnes, personnes en lignes.

    Construit côté serveur et non dans le navigateur, pour la même raison que la grille de
    disponibilités : les effectifs par créneau sont des chiffres dont quelqu'un répond, et un
    total recalculé sur une liste paginée ou filtrée finirait par diverger de ce qu'il décrit.
    """
    from .models import ContactInstitution, CreneauEquipe, StatutCreneauEquipe
    from .permissions import nom_affichable

    creneaux = _creneaux_ordonnes()
    debut = debut or timezone.localdate()
    try:
        nb_jours = int(jours) if jours else JOURS_PLANNING
    except (TypeError, ValueError):
        nb_jours = JOURS_PLANNING
    nb_jours = max(1, min(nb_jours, PLAFOND_JOURS_PLANNING))
    liste_jours = [debut + datetime.timedelta(days=i) for i in range(nb_jours)]

    lignes = list(
        CreneauEquipe.objects.filter(
            equipe=equipe, date__gte=liste_jours[0], date__lte=liste_jours[-1],
        ).select_related("utilisateur", "point", "mission")
    )

    # Les membres de l'équipe qui ont au moins une ligne, PLUS tous les membres de l'équipe :
    # un planning qui ne montre que les gens déjà placés ne permet pas de voir qui reste.
    par_utilisateur = {}
    for ligne in lignes:
        par_utilisateur.setdefault(ligne.utilisateur_id, []).append(ligne)

    membres = {m.id: m for m in equipe.members.all()}
    for ligne in lignes:
        membres.setdefault(ligne.utilisateur_id, ligne.utilisateur)

    fonctions = {
        c.utilisateur_id: c.fonction
        for c in ContactInstitution.objects.filter(
            institution_id=equipe.institution_id, utilisateur_id__in=membres.keys())
    }

    personnes = []
    for identifiant, utilisateur in membres.items():
        siennes = {
            (l.date, l.creneau): l for l in par_utilisateur.get(identifiant, [])
        }
        personnes.append({
            "utilisateur": identifiant,
            "nom": nom_affichable(utilisateur, request) or utilisateur.email,
            "fonction": fonctions.get(identifiant, ""),
            "creneaux_tenus": sum(
                1 for l in siennes.values() if l.compte_dans_leffectif),
            "jours": [
                {
                    "date": jour,
                    "creneaux": {
                        creneau: (
                            None if (jour, creneau) not in siennes else {
                                "id": siennes[(jour, creneau)].id,
                                "statut": siennes[(jour, creneau)].statut,
                                "statut_libelle":
                                    siennes[(jour, creneau)].get_statut_display(),
                                "role": siennes[(jour, creneau)].role,
                                "point_nom": (siennes[(jour, creneau)].point.nom
                                              if siennes[(jour, creneau)].point_id else None),
                            }
                        )
                        for creneau in creneaux
                    },
                }
                for jour in liste_jours
            ],
        })
    personnes.sort(key=lambda p: p["nom"].lower())

    # Effectif réellement tenu, créneau par créneau : annulés et absents exclus.
    effectifs = {}
    for ligne in lignes:
        if not ligne.compte_dans_leffectif:
            continue
        effectifs.setdefault(ligne.date.isoformat(), {}).setdefault(ligne.creneau, 0)
        effectifs[ligne.date.isoformat()][ligne.creneau] += 1

    return {
        "equipe": equipe.id,
        "equipe_nom": equipe.name,
        "debut": liste_jours[0],
        "fin": liste_jours[-1],
        "jours": liste_jours,
        "creneaux": creneaux,
        "personnes": personnes,
        "effectifs": effectifs,
        "statuts": [
            {"code": valeur, "libelle": libelle}
            for valeur, libelle in StatutCreneauEquipe.choices
        ],
    }


def creneaux_non_couverts(donnees, effectif_cible):
    """Les créneaux où l'effectif tenu est sous la cible.

    Rendu à part et non mélangé au planning : c'est la liste sur laquelle on agit, et la
    chercher à l'œil dans une grille de quatorze colonnes est exactement ce qu'un écran doit
    éviter de faire faire."""
    if not effectif_cible:
        return []
    manques = []
    for jour in donnees["jours"]:
        cle = jour.isoformat() if hasattr(jour, "isoformat") else str(jour)
        for creneau in donnees["creneaux"]:
            tenu = donnees["effectifs"].get(cle, {}).get(creneau, 0)
            if tenu < effectif_cible:
                manques.append({
                    "date": cle, "creneau": creneau,
                    "tenu": tenu, "cible": effectif_cible,
                    "manque": effectif_cible - tenu,
                })
    return manques
