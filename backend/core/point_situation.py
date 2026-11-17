"""Le point de situation d'une crise, vu par une collectivité (17/11/2026).

À chaque point avec la préfecture, le maire annonce les mêmes chiffres : combien de personnes
accueillies, combien de demandes en attente, combien de recherches en cours, quels moyens
engagés. **Tous ces chiffres existent déjà** dans l'application — on ne saisit rien de plus,
on les rassemble, sur toute la crise et non sur l'écran qu'on a sous les yeux, pour que deux
personnes n'annoncent pas deux totaux en réunion.

Les moyens engagés (mobilisations, équipes, créneaux tenus) servent aussi après coup : c'est la
base du dossier d'indemnisation, sans tenir de comptabilité.
"""
from django.db.models import Q, Sum
from django.utils import timezone


def construire(crise, institution, environment) -> dict:
    from . import relogement, standard_crise
    from .models import (
        AlertePopulation, CreneauEquipe, DemandeMobilisation, Dossier, Habitation, Information,
        Mission, PointOperationnel, RecherchePersonne, RegistrePresence, Request,
        StatutCreneauEquipe, StatutDemandeMobilisation, TypePersonneAccueillie,
    )

    commune = institution.commune_code or ""
    sur_la_commune = {"commune_code": commune} if commune else {}

    # ── Population ───────────────────────────────────────────────────────────────────────
    points = PointOperationnel.objects.filter(crise=crise, environment=environment)
    presents = RegistrePresence.objects.filter(point__in=points, date_depart__isnull=True)
    accueillis = presents.filter(type_personne=TypePersonneAccueillie.EVACUE).aggregate(n=Sum("nombre"))["n"] or 0
    passes = RegistrePresence.objects.filter(
        point__in=points, type_personne=TypePersonneAccueillie.EVACUE).aggregate(n=Sum("nombre"))["n"] or 0
    par_centre = [
        {"centre": nom, "personnes": nombre}
        for nom, nombre in presents.filter(type_personne=TypePersonneAccueillie.EVACUE)
        .values_list("point__nom").annotate(n=Sum("nombre")).order_by("point__nom")
    ]
    recherches = RecherchePersonne.objects.filter(crise=crise, environment=environment)
    habitations = Habitation.objects.filter(crise=crise, environment=environment, **sur_la_commune)
    try:
        logement = relogement.synthese(crise, environment)
    except Exception:
        logement = {}

    # ── Demandes ─────────────────────────────────────────────────────────────────────────
    a_nous = Q(institution_demandeuse=institution) | Q(equipe__institution=institution)
    if commune:
        a_nous |= Q(demande__commune_code=commune) | Q(information__commune_code=commune)
    dossiers = Dossier.objects.filter(a_nous, crise=crise, environment=environment).distinct()
    resolus = [s for s in ("RESOLU", "CLOTURE", "CLOS") if hasattr(Dossier.Statut, s)]
    ouverts = dossiers.exclude(statut__in=[getattr(Dossier.Statut, s) for s in resolus]) if resolus else dossiers

    # ── Moyens engagés ───────────────────────────────────────────────────────────────────
    missions = Mission.objects.filter(
        Q(institution=institution) | Q(equipes__institution=institution), crise=crise, environment=environment).distinct()
    equipes = set(missions.values_list("equipes__name", flat=True)) - {None}
    mobilisations = DemandeMobilisation.objects.filter(
        crise=crise, institution_emettrice=institution, environment=environment)
    creneaux = CreneauEquipe.objects.filter(crise=crise, equipe__institution=institution)
    tenus = creneaux.filter(statut=StatutCreneauEquipe.REALISE)

    # Le temps réellement passé, d'après ce que chacun a déclaré : « je pars », « je rentre ».
    from .models import EngagementRessource
    engagements = list(
        EngagementRessource.objects.filter(
            offer__crisis=crise, team__institution=institution, environment=environment)
        .exclude(date_transit__isnull=True, date_arrivee__isnull=True)
        .select_related("offer", "team").order_by("date_transit", "date_arrivee")
    )
    releve, secondes, dehors = [], 0, 0
    for engagement in engagements:
        duree = engagement.duree_engagee
        if duree is not None:
            secondes += duree.total_seconds()
        elif engagement.date_retour is None:
            dehors += 1
        releve.append({
            "ressource": engagement.offer.title, "equipe": engagement.team.name,
            "parti_le": engagement.date_transit or engagement.date_arrivee,
            "rentre_le": engagement.date_retour,
            "heures": round(duree.total_seconds() / 3600, 2) if duree is not None else None,
        })
    heures = round(secondes / 3600, 1)

    chiffres = {
        "population": [
            ("Personnes accueillies en ce moment", accueillis),
            ("Personnes passées par un centre depuis le début", passes),
            ("Recherches de personnes en cours", recherches.filter(date_retrouvee__isnull=True).count()),
            ("Personnes retrouvées", recherches.filter(date_retrouvee__isnull=False).count()),
            ("Habitations évaluées", habitations.count()),
        ],
        "demandes": [
            ("Demandes d'aide reçues", Request.objects.filter(crisis=crise, environment=environment, **sur_la_commune).count()),
            ("Signalements reçus", Information.objects.filter(crisis=crise, environment=environment, **sur_la_commune).count()),
            ("Dossiers ouverts", dossiers.count()),
            ("Dossiers encore en cours", ouverts.count()),
        ],
        "moyens": [
            ("Équipes engagées", len(equipes)),
            ("Missions conduites", missions.count()),
            ("Mobilisations demandées", mobilisations.count()),
            ("Mobilisations en cours", mobilisations.filter(statut=StatutDemandeMobilisation.ACTIVE).count()),
            ("Engagements déclarés (« je pars »)", len(engagements)),
            ("Encore sur le terrain (pas de « je rentre »)", dehors),
            ("Heures engagées déclarées", heures),
            ("Créneaux d'équipe tenus", tenus.count()),
            ("Personnes ayant tenu un créneau", tenus.values("utilisateur").distinct().count()),
            ("Alertes diffusées aux habitants", AlertePopulation.objects.filter(
                institution=institution, crise=crise, environment=environment).count()),
        ],
    }
    appels = standard_crise.synthese(institution, environment, crise)
    chiffres["standard"] = [("Appels reçus au standard", appels["total"]), ("Appels à traiter", appels["a_traiter"])]
    if logement:
        chiffres["relogement"] = [
            (libelle, logement[cle]) for cle, libelle in (
                ("foyers", "Foyers suivis pour un relogement"),
                ("sans_solution", "Foyers sans solution"),
            ) if isinstance(logement.get(cle), int)
        ]

    maintenant = timezone.localtime()
    return {
        "crise": crise.name, "collectivite": institution.nom, "etabli_le": maintenant,
        "chiffres": {famille: [{"libelle": l, "valeur": v} for l, v in lignes] for famille, lignes in chiffres.items()},
        "par_centre": par_centre,
        "equipes": sorted(equipes),
        # Engagement par engagement, pour le dossier d'indemnisation : qui, quand, combien.
        "releve_engagements": releve,
        "texte": _en_texte(crise, institution, maintenant, chiffres, par_centre, sorted(equipes)),
    }


TITRES = {
    "population": "Population", "demandes": "Demandes et dossiers", "moyens": "Moyens engagés",
    "standard": "Standard de crise", "relogement": "Relogement",
}


def _en_texte(crise, institution, maintenant, chiffres, par_centre, equipes) -> str:
    """Le même point, en texte brut : prêt à coller dans un courriel ou à lire au téléphone."""
    lignes = [
        f"POINT DE SITUATION — {crise.name}",
        f"{institution.nom}, le {maintenant.strftime('%d/%m/%Y à %H:%M')}",
    ]
    for famille, titre in TITRES.items():
        if famille not in chiffres or not chiffres[famille]:
            continue
        lignes += ["", titre.upper()]
        lignes += [f"- {libelle} : {valeur}" for libelle, valeur in chiffres[famille]]
        if famille == "population" and par_centre:
            lignes += [f"    · {c['centre']} : {c['personnes']}" for c in par_centre]
        if famille == "moyens" and equipes:
            lignes.append("    · " + ", ".join(equipes))
    return "\n".join(lignes)
