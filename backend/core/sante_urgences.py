"""Recours aux urgences par département : relevé des indicateurs de Santé publique France.

SOURCE
Odissé (https://odisse.santepubliquefrance.fr), le portail de données de Santé publique France,
Licence Ouverte 2.0. Aucune clé. Les indicateurs du réseau de surveillance SurSaUD : part des
passages aux urgences (réseau OSCOUR) et des actes SOS Médecins attribués à une pathologie, par
département et par semaine. Publiés chaque semaine, avec une dizaine de jours de recul.

CE QU'ON EN GARDE
Quatre pathologies qui disent si le système de soins d'un département est sous tension :
grippe, Covid-19, gastro-entérite, et bronchiolite chez les moins d'un an. Pour chacune, la
dernière semaine publiée et la précédente, toutes classes d'âge confondues.

CE QUE CE CHIFFRE VEUT DIRE
Un taux pour 100 000 passages aux urgences : sur 100 000 personnes venues aux urgences cette
semaine-là, combien venaient pour cette pathologie. Ce n'est NI un nombre de malades NI un taux
dans la population. Il sert à voir une tendance, pas à compter. L'écran doit le dire.

Un appel national par pathologie, une fois par jour (les données sont hebdomadaires). Même règle
que le reste de la veille : seul le serveur appelle, pour la France entière.
"""
import datetime
import logging

import requests
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

PORTAIL = "https://odisse.santepubliquefrance.fr/api/explore/v2.1/catalog/datasets"
DELAI_REPONSE_S = 60
SUFFIXE = "passages-aux-urgences-et-actes-sos-medecins-departement"
# code -> (libellé, jeu de données, abréviation dans les noms de champs, classe d'âge)
PATHOLOGIES = {
    "GRIPPE": ("Grippe", f"grippe-{SUFFIXE}", "grippe", "Tous âges"),
    "COVID": ("Covid-19", f"covid-19-{SUFFIXE}", "covid", "Tous âges"),
    "GASTRO": ("Gastro-entérite", f"gastro-enterite-aigue-{SUFFIXE}", "gastro", "Tous âges"),
    "BRONCHIOLITE": ("Bronchiolite (moins d'un an)", f"bronchiolite-{SUFFIXE}", "bronchio", "0 an"),
}
# Cinq semaines en arrière : de quoi tenir la dernière semaine publiée et la précédente, même
# quand la publication a du retard.
RECUL = datetime.timedelta(days=42)
MINIMUM_PLAUSIBLE = 80


def telecharger(code, maintenant=None):
    _libelle, jeu, champ, classe = PATHOLOGIES[code]
    depuis = ((maintenant or timezone.now()) - RECUL).date().isoformat()
    reponse = requests.get(f"{PORTAIL}/{jeu}/exports/json", timeout=DELAI_REPONSE_S, params={
        "where": f"sursaud_cl_age_gene=\"{classe}\" and date_complet >= date'{depuis}'",
        "select": f"dep,semaine,date_complet,taux_passages_{champ}_sau,taux_actes_{champ}_sos",
    })
    reponse.raise_for_status()
    donnees = reponse.json()
    if not isinstance(donnees, list):
        raise ValueError("réponse du portail sans liste d'enregistrements")
    return donnees


def _nombre(valeur):
    return round(float(valeur), 1) if isinstance(valeur, (int, float)) and not isinstance(valeur, bool) else None


def analyser(code, enregistrements):
    """Enregistrements du portail -> {département: dictionnaire prêt pour IndicateurSante} : la
    dernière semaine publiée de chaque département, et le taux de celle d'avant."""
    champ = PATHOLOGIES[code][2]
    par_departement = {}
    for brut in enregistrements:
        departement = str(brut.get("dep") or "").strip()
        try:
            debut = datetime.date.fromisoformat(str(brut.get("date_complet"))[:10])
        except ValueError:
            continue
        if not 2 <= len(departement) <= 3:
            continue
        par_departement.setdefault(departement, []).append((debut, brut))

    indicateurs = {}
    for departement, semaines in par_departement.items():
        semaines.sort(key=lambda s: s[0], reverse=True)
        debut, derniere = semaines[0]
        precedente = semaines[1][1] if len(semaines) > 1 else {}
        indicateurs[departement] = {
            "pathologie": code,
            "departement_code": departement,
            "semaine": str(derniere.get("semaine") or "")[:10],
            "debut_semaine": debut,
            "taux_urgences": _nombre(derniere.get(f"taux_passages_{champ}_sau")),
            "taux_urgences_precedent": _nombre(precedente.get(f"taux_passages_{champ}_sau")),
            "taux_sos": _nombre(derniere.get(f"taux_actes_{champ}_sos")),
        }
    return indicateurs


def tendance(actuel, precedent):
    """« hausse », « baisse », « stable », ou chaîne vide si l'une des deux valeurs manque. Un
    écart de moins de 20 % est dans le bruit d'une semaine à l'autre."""
    if actuel is None or precedent is None:
        return ""
    if precedent == 0:
        return "hausse" if actuel > 0 else "stable"
    if actuel > precedent * 1.2:
        return "hausse"
    if actuel < precedent * 0.8:
        return "baisse"
    return "stable"


def relever(maintenant=None):
    """Relève les quatre pathologies. Une pathologie en panne n'empêche pas les autres ; le
    relevé n'échoue que si aucune n'a pu être lue."""
    from .models import IndicateurSante

    maintenant = maintenant or timezone.now()
    lignes, lues = [], 0
    for code in PATHOLOGIES:
        try:
            indicateurs = analyser(code, telecharger(code, maintenant))
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Santé : %s non relevée (%s).", code, exc)
            continue
        if len(indicateurs) < MINIMUM_PLAUSIBLE:
            logger.warning("Santé : %s ne rend que %s départements, copie précédente gardée.", code, len(indicateurs))
            continue
        lues += 1
        lignes.extend(IndicateurSante(releve_le=maintenant, **i) for i in indicateurs.values())
    if not lues:
        raise ValueError("aucune pathologie n'a pu être relevée")
    with transaction.atomic():
        IndicateurSante.objects.bulk_create(
            lignes, batch_size=500, update_conflicts=True,
            unique_fields=["pathologie", "departement_code"],
            update_fields=["semaine", "debut_semaine", "taux_urgences", "taux_urgences_precedent",
                           "taux_sos", "releve_le"])
    return len(lignes)
