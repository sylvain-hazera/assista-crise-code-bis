"""Suivi du relogement des familles sinistrées, et les chiffres qu'on en tire.

Demande de Sylvain du 12/11/2026 : « comme on a fait une page suivi hébergement des équipes,
il me faudra une page, suivi hébergement des familles nécessitant un relogement [...] À terme,
on devra pouvoir éditer des rapports à différents moments de la crise et pouvoir dire, par
exemple, tant de familles relogées, tant de manières pérennes. »

**La synthèse est calculée ici, pas dans le navigateur, et c'est le point important.** Un
rapport remis à une préfecture ou lu en réunion de crise n'est pas un affichage : c'est un
chiffre dont quelqu'un répond. Compté côté client, il ne porte que sur les lignes chargées
(une liste paginée en donne une partie), il change avec les filtres à l'écran, et deux
personnes regardant la même crise annoncent deux totaux différents. Ici le compte porte sur
toute la crise, toujours.

**Ce qu'on compte, et ce qu'on refuse de confondre :**

- une FAMILLE n'est pas une PERSONNE. « 12 familles » et « 31 personnes » sont deux réponses à
  deux questions, et les deux sont demandées ;
- « relogée » n'est pas « relogée durablement ». Un foyer à l'hôtel depuis trois semaines est
  hébergé, pas relogé — l'annoncer comme relogé ferait écrire un bilan faux. C'est
  `TypeSolutionRelogement` qui tranche, et seul `DEFINITIVE` compte comme pérenne ;
- un foyer SANS solution courante est le chiffre le plus important de la page, et il doit être
  impossible à manquer : ce sont des gens qui dorment on ne sait où ce soir.
"""
from django.utils import timezone

#: Fenêtre de l'alerte « arrive à son terme ». Trente jours : le délai en dessous duquel une
#: collectivité n'a plus le temps de trouver autre chose sans rupture d'hébergement.
JOURS_ALERTE_TERME = 30


def dossiers_de_la_crise(crise, environnement):
    from .models import DossierRelogement

    return DossierRelogement.objects.filter(
        crise=crise, environment=environnement,
    ).prefetch_related("solutions")


def synthese(crise, environnement, aujourdhui=None):
    """Les chiffres du rapport, pour une crise.

    Rendue telle quelle à l'écran ET exploitable comme base d'un document : c'est la même
    source, pour qu'un bilan écrit ne puisse pas diverger de ce que la page affiche."""
    from .models import StatutDossierRelogement, TypeSolutionRelogement

    aujourdhui = aujourdhui or timezone.localdate()
    dossiers = list(dossiers_de_la_crise(crise, environnement))

    par_statut = {valeur: 0 for valeur, _ in StatutDossierRelogement.choices}
    par_type_courant = {valeur: 0 for valeur, _ in TypeSolutionRelogement.choices}
    sans_solution, arrivent_a_terme, termes_depasses = [], [], []
    adultes = enfants = 0
    foyers_vulnerables = 0

    for dossier in dossiers:
        par_statut[dossier.statut] = par_statut.get(dossier.statut, 0) + 1
        adultes += dossier.nombre_adultes or 0
        enfants += dossier.nombre_enfants or 0
        if dossier.personnes_vulnerables:
            foyers_vulnerables += 1

        courante = dossier.solution_courante
        if courante is None:
            # Clos : la famille est sortie du dispositif, elle n'est pas « sans solution ».
            if dossier.statut in (StatutDossierRelogement.EN_RECHERCHE,
                                  StatutDossierRelogement.HEBERGE):
                sans_solution.append(dossier.id)
            continue

        par_type_courant[courante.type_solution] = \
            par_type_courant.get(courante.type_solution, 0) + 1
        if courante.date_fin_prevue is not None:
            restants = (courante.date_fin_prevue - aujourdhui).days
            if restants < 0:
                termes_depasses.append(dossier.id)
            elif restants <= JOURS_ALERTE_TERME:
                arrivent_a_terme.append(dossier.id)

    return {
        "crise": crise.id,
        "crise_nom": crise.name,
        "date_arrete": aujourdhui,
        "foyers": len(dossiers),
        "personnes": adultes + enfants,
        "adultes": adultes,
        "enfants": enfants,
        "foyers_avec_personnes_vulnerables": foyers_vulnerables,
        "par_statut": par_statut,
        # La ventilation par type de la solution EN COURS : c'est elle qui permet d'écrire
        # « tant de familles relogées de manière pérenne » sans mentir.
        "par_type_solution_courante": par_type_courant,
        "relogees_durablement": par_type_courant.get(TypeSolutionRelogement.DEFINITIVE, 0),
        "sans_solution": len(sans_solution),
        "sans_solution_ids": [str(i) for i in sans_solution],
        "arrivent_a_terme": len(arrivent_a_terme),
        "arrivent_a_terme_ids": [str(i) for i in arrivent_a_terme],
        # Terme prévu dépassé sans sortie enregistrée : le cas le plus urgent de tous, parce
        # que personne ne sait où en est cette famille.
        "termes_depasses": len(termes_depasses),
        "termes_depasses_ids": [str(i) for i in termes_depasses],
        "jours_alerte_terme": JOURS_ALERTE_TERME,
    }
