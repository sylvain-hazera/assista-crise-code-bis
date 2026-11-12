"""Tours de garde : découper une période et proposer qui tient quel créneau.

Demande de Sylvain du 11/11/2026 : « prévoir des rotations pour pas que les membres restent
mobilisés trop longtemps ».

**La règle de répartition, puisqu'elle devait être tranchée.** Elle est ordonnée, et chaque
niveau répond à une objection précise :

1. **Seulement ceux qui se sont déclarés disponibles sur ce créneau.** Jamais d'affectation
   d'office : une garde armée avec quelqu'un qui n'a rien promis n'est pas armée.
2. **Le moins de jours consécutifs déjà posés**, dans la limite de `duree_rotation_jours` et en
   respectant `repos_min_jours`. C'est la raison d'être des rotations : sans ce critère, le
   planificateur reprendrait les mêmes personnes du premier au dernier jour.
3. **Le moins de créneaux déjà posés dans la campagne**, pour l'équité. Deux personnes
   également disponibles ne doivent pas être sollicitées dans un rapport de dix à un.
4. **Le plus proche de la crise**, quand la campagne en nomme une : à égalité par ailleurs,
   celui qui habite à dix minutes arrive avant celui qui met deux heures.
5. **L'ordre alphabétique**, pour que deux exécutions donnent le même plan. Un planificateur
   qui rebrasse les noms à chaque recalcul est un planificateur qu'on ne relit pas.

**Rien n'est jamais confirmé par le calcul.** Tout sort en `PROPOSEE` : le planificateur ignore
les trajets réels, les brouilles, ce qui s'est dit au téléphone et ce qu'une personne vient
d'annoncer. L'encadrement confirme, et une régénération **garde** les lignes confirmées — sinon
chaque recalcul détruirait les décisions prises.

**Le sous-effectif est rendu, pas masqué.** Si un créneau ne trouve que deux personnes sur six,
la rotation est créée avec deux noms et le manque est dit. Une grille qui paraît complète parce
qu'on a caché les trous est pire que pas de grille.
"""
import datetime
from collections import defaultdict


def _tranches(campagne):
    """Découpe la période en tranches de `duree_rotation_jours`.

    La dernière peut être plus courte : une période de dix jours en tranches de trois donne
    3 + 3 + 3 + 1, et refuser le dernier jour laisserait un trou de garde."""
    duree = max(1, campagne.duree_rotation_jours)
    tranches = []
    debut = campagne.periode_debut
    numero = 1
    while debut <= campagne.periode_fin:
        fin = min(debut + datetime.timedelta(days=duree - 1), campagne.periode_fin)
        tranches.append((numero, debut, fin))
        debut = fin + datetime.timedelta(days=1)
        numero += 1
    return tranches


def _jours(debut, fin):
    return [debut + datetime.timedelta(days=i) for i in range((fin - debut).days + 1)]


def _declarations_par_personne(campagne):
    """`{utilisateur_id: {(date, creneau)}}` — ce que les bénévoles ont déclaré DANS la période.

    Une requête pour toute la campagne : une par rotation et par créneau ferait des dizaines
    d'allers-retours pour un calcul qui tient en mémoire."""
    from .models import CibleCampagne, DisponibiliteOffre

    ressources = dict(
        CibleCampagne.objects.filter(campagne=campagne, ressource__isnull=False)
        .values_list("ressource_id", "utilisateur_id")
    )
    if not ressources:
        return {}

    par_personne = defaultdict(set)
    for offre_id, date_jour, creneau in DisponibiliteOffre.objects.filter(
        offer_id__in=ressources.keys(),
        date__gte=campagne.periode_debut, date__lte=campagne.periode_fin,
    ).values_list("offer_id", "date", "creneau"):
        par_personne[ressources[offre_id]].add((date_jour, creneau))
    return par_personne


def _distances(campagne):
    """`{utilisateur_id: mètres}` jusqu'au point de la crise, vide s'il n'y en a pas."""
    from django.contrib.gis.db.models.functions import Distance

    from .models import CibleCampagne

    if campagne.crise is None or campagne.crise.location is None:
        return {}
    lignes = (
        CibleCampagne.objects.filter(campagne=campagne, ressource__isnull=False)
        .annotate(d=Distance("ressource__location", campagne.crise.location))
        .values_list("utilisateur_id", "d")
    )
    return {uid: (d.m if d is not None else float("inf")) for uid, d in lignes}


def generer_rotations(campagne):
    """Crée les tours de garde et propose les affectations. Idempotent.

    Renvoie un bilan : `{"rotations": n, "proposees": n, "conservees": n, "manques": [...]}`.
    Les manques nomment le créneau et ce qui lui reste à trouver — c'est l'information dont
    l'encadrement a besoin pour décider s'il élargit ses critères ou s'il relance.
    """
    from django.db import transaction

    from .models import (
        AffectationRotation, RotationCampagne, StatutAffectationRotation,
    )

    if not campagne.tours_de_garde:
        # Option désactivée : on ne laisse pas traîner des tours d'une activation précédente.
        # Une grille de garde orpheline, que plus rien n'alimente, est pire qu'aucune grille :
        # quelqu'un la lira un jour en croyant qu'elle vaut encore.
        supprimees = RotationCampagne.objects.filter(campagne=campagne).delete()[0]
        return {"rotations": 0, "proposees": 0, "conservees": 0, "manques": [],
                "desactive": True, "supprimees": supprimees}

    creneaux = campagne.creneaux_effectifs
    cible = campagne.effectif_cible
    declarations = _declarations_par_personne(campagne)
    distances = _distances(campagne)
    noms = _noms(campagne)

    bilan = {"rotations": 0, "proposees": 0, "conservees": 0, "manques": [],
             "desactive": False}

    with transaction.atomic():
        # Les PROPOSÉES sont effacées, les CONFIRMÉES gardées : un recalcul ne doit pas
        # détruire ce que l'encadrement a tranché.
        confirmees = list(
            AffectationRotation.objects.filter(
                rotation__campagne=campagne,
                statut=StatutAffectationRotation.CONFIRMEE,
            ).values_list("rotation__numero", "utilisateur_id", "creneau")
        )
        bilan["conservees"] = len(confirmees)
        AffectationRotation.objects.filter(
            rotation__campagne=campagne,
        ).exclude(statut=StatutAffectationRotation.CONFIRMEE).delete()

        deja_confirme = defaultdict(set)
        for numero, utilisateur_id, creneau in confirmees:
            deja_confirme[(numero, creneau)].add(utilisateur_id)

        # Charge déjà posée, pour l'équité et pour le repos. Les confirmées comptent : elles
        # occupent réellement la personne.
        creneaux_poses = defaultdict(int)
        jours_poses = defaultdict(set)

        tranches = _tranches(campagne)
        rotations_par_numero = {}
        for numero, debut, fin in tranches:
            rotation, _ = RotationCampagne.objects.update_or_create(
                campagne=campagne, numero=numero,
                defaults={"date_debut": debut, "date_fin": fin,
                          "environment": campagne.environment},
            )
            rotations_par_numero[numero] = rotation
            bilan["rotations"] += 1

        # Les confirmées d'abord, pour que la charge soit juste avant la première proposition.
        for numero, utilisateur_id, creneau in confirmees:
            _, debut, fin = next(t for t in tranches if t[0] == numero)
            creneaux_poses[utilisateur_id] += 1
            jours_poses[utilisateur_id].update(_jours(debut, fin))

        # Rotations supprimées si la période a été raccourcie entre deux calculs.
        RotationCampagne.objects.filter(campagne=campagne).exclude(
            numero__in=list(rotations_par_numero)
        ).delete()

        if cible <= 0:
            # Tours de garde activés mais effectif laissé à zéro : les tranches sont créées —
            # elles donnent le découpage que le message annonce aux bénévoles — et personne
            # n'est affecté. Le sérialiseur refuse normalement cette combinaison ; on la tient
            # quand même, parce qu'une campagne créée par script ou par l'admin Django ne
            # passe pas par lui.
            return bilan

        for numero, debut, fin in tranches:
            rotation = rotations_par_numero[numero]
            jours_de_la_tranche = _jours(debut, fin)
            for creneau in creneaux:
                deja = deja_confirme.get((numero, creneau), set())
                manque = cible - len(deja)
                if manque <= 0:
                    continue

                candidats = []
                for utilisateur_id, declares in declarations.items():
                    if utilisateur_id in deja:
                        continue
                    # 1. Déclaré disponible sur AU MOINS un jour de la tranche, ce créneau.
                    jours_dispo = [j for j in jours_de_la_tranche
                                   if (j, creneau) in declares]
                    if not jours_dispo:
                        continue
                    # 2. Repos : pas de tour collé au précédent sous le minimum.
                    if not _repos_respecte(jours_poses[utilisateur_id], jours_de_la_tranche,
                                           campagne.repos_min_jours):
                        continue
                    candidats.append((
                        len(jours_poses[utilisateur_id]),           # 2. le moins mobilisé
                        creneaux_poses[utilisateur_id],             # 3. équité
                        distances.get(utilisateur_id, 0),           # 4. proximité
                        noms.get(utilisateur_id, ""),               # 5. déterminisme
                        utilisateur_id,
                    ))

                candidats.sort()
                retenus = candidats[:manque]
                for _j, _c, _d, _n, utilisateur_id in retenus:
                    AffectationRotation.objects.create(
                        rotation=rotation, utilisateur_id=utilisateur_id, creneau=creneau,
                        statut=StatutAffectationRotation.PROPOSEE,
                        motif=_motif(jours_poses[utilisateur_id], distances, utilisateur_id),
                        environment=campagne.environment,
                    )
                    creneaux_poses[utilisateur_id] += 1
                    jours_poses[utilisateur_id].update(
                        j for j in jours_de_la_tranche if (j, creneau) in declarations[utilisateur_id]
                    )
                    bilan["proposees"] += 1

                if len(retenus) < manque:
                    # Dit, jamais masqué : une grille qui paraît complète parce qu'on a caché
                    # les trous est pire que pas de grille.
                    bilan["manques"].append({
                        "rotation": numero, "creneau": creneau,
                        "attendus": cible,
                        "trouves": len(deja) + len(retenus),
                    })

    return bilan


def _repos_respecte(jours_deja_poses, jours_de_la_tranche, repos_min):
    """Vrai si affecter cette tranche laisse au moins `repos_min` jours depuis le dernier tour.

    Sans ce garde-fou, le critère « le moins mobilisé » suffirait à étaler la charge mais pas à
    empêcher deux tours collés — or c'est précisément ce que Sylvain veut éviter."""
    if not jours_deja_poses or repos_min <= 0:
        return True
    dernier = max(jours_deja_poses)
    premier_de_la_tranche = min(jours_de_la_tranche)
    if premier_de_la_tranche <= dernier:
        # Chevauchement : la personne est déjà prise sur ces jours.
        return False
    return (premier_de_la_tranche - dernier).days > repos_min


def _motif(jours_poses, distances, utilisateur_id):
    """Pourquoi cette personne a été retenue, en une phrase lisible.

    Une proposition qu'on ne peut pas expliquer ne se relit pas, elle se subit — et
    l'encadrement doit pouvoir dire « non, pas lui » en sachant sur quoi le calcul s'est
    appuyé."""
    morceaux = [f"{len(jours_poses)} jour(s) déjà posé(s)"]
    distance = distances.get(utilisateur_id)
    if distance not in (None, 0):
        morceaux.append(f"à {round(distance / 1000)} km de la crise")
    return "Disponible, " + ", ".join(morceaux) + "."


def _noms(campagne):
    """`{utilisateur_id: clé de tri}` — pour que deux exécutions donnent le même plan."""
    from .models import CibleCampagne

    return {
        uid: f"{(nom or '').lower()} {(prenom or '').lower()}"
        for uid, nom, prenom in CibleCampagne.objects.filter(campagne=campagne).values_list(
            "utilisateur_id", "utilisateur__last_name", "utilisateur__first_name")
    }
