"""Relevé planifié des sources ouvertes copiées en base : la « veille du territoire ».

Seize sources aujourd'hui -- vigilance, mesures des stations, pluie prévue, météo des forêts et
risque d'avalanche (Météo-France), vigilance crues (Vigicrues), restrictions d'eau (VigiEau),
foyers actifs (NASA FIRMS) et surfaces brûlées (EFFIS), événements routiers (Bison Futé), arrêtés de circulation (DiaLog),
recours aux urgences (Santé publique France), radioactivité ambiante (Téléray), séismes
(BCSF-Rénass), défibrillateurs (Géo'DAE), stations de carburant. Toutes obéissent à la même règle (15/11/2026) :

1. Seul le serveur appelle, depuis la tâche planifiée, et toujours pour la France ENTIÈRE.
   Aucun navigateur n'interroge ces services, aucune requête d'utilisateur ne déclenche d'appel
   sortant, et rien de ce qui part ne désigne une personne, une commune ou une institution.
2. La réponse est copiée en base ; les écrans et les alertes lisent la copie.
3. Chaque relevé laisse une trace (`ReleveSourceOuverte`) : c'est elle qui dit si un relevé est
   dû, et qui permet à la supervision de signaler une source qui ne se rafraîchit plus.

Ajouter une source = écrire son module (une fonction `relever()` qui rend un nombre de lignes
et lève une exception en cas d'échec) et l'inscrire dans SOURCES.

Sur un satellite ou un poste de développement sans accès aux sources, tout cela se tait : les
relevés échouent, la trace le dit, les écrans affichent « aucun relevé ».
"""
import datetime
import logging
from collections import namedtuple

from django.utils import timezone

from . import (
    arretes_circulation, avalanche, carburants, defibrillateurs, feux_satellite, foyers_actifs, meteo_forets, meteo_france, observations_meteo, pluie,
    radioactivite, restrictions_eau, sante_urgences, seismes, trafic_routier, vigilance_crues,
)

logger = logging.getLogger(__name__)

# `intervalle` : délai minimal entre deux relevés réussis. `perime_apres` : âge au-delà duquel
# la copie ne doit plus être présentée comme actuelle (écrans et supervision).
Source = namedtuple("Source", "code libelle relever intervalle perime_apres attribution")

SOURCES = {
    source.code: source for source in (
        Source("VIGILANCE_METEO", "Vigilance météorologique", meteo_france.relever,
               datetime.timedelta(minutes=9), meteo_france.FRAICHEUR_MAX, "Météo-France"),
        # Mesures des stations : un paquet toutes les six minutes, relevé à chaque passage.
        Source("OBSERVATIONS_METEO", "Mesures des stations météorologiques",
               observations_meteo.relever, datetime.timedelta(minutes=9),
               datetime.timedelta(hours=1), "Météo-France"),
        # Pluie prévue : douze images par heure quand un nouveau calcul paraît, presque rien
        # entre-temps (les échéances déjà copiées ne sont pas redemandées).
        Source("PLUIE_PREVISION", "Pluie prévue (prévision immédiate)", pluie.relever,
               datetime.timedelta(minutes=9), datetime.timedelta(hours=1), "Météo-France"),
        # Vigicrues publie deux fois par jour et à chaque aggravation : une demi-heure borne
        # le retard sans retélécharger 2 Mo à chaque passage.
        Source("VIGILANCE_CRUES", "Vigilance crues par tronçon", vigilance_crues.relever,
               datetime.timedelta(minutes=29), datetime.timedelta(hours=6),
               "Vigicrues - réseau de prévision des crues"),
        # Les arrêtés de restriction changent au rythme des préfectures : quatre relevés par
        # jour suffisent, et les données du jour ne paraissent que dans la matinée.
        Source("RESTRICTIONS_EAU", "Restrictions d'usage de l'eau", restrictions_eau.relever,
               datetime.timedelta(hours=6), datetime.timedelta(hours=48),
               "VigiEau - ministère de la Transition écologique"),
        # Six passages de satellite par jour, publiés trois heures après : toutes les demi-heures
        # suffit à ne manquer aucun passage.
        Source("FOYERS_ACTIFS", "Foyers d'incendie détectés par satellite", foyers_actifs.relever,
               datetime.timedelta(minutes=29), datetime.timedelta(hours=12), "NASA FIRMS"),
        Source("FEUX_SATELLITE", "Surfaces brûlées repérées par satellite", feux_satellite.relever,
               datetime.timedelta(hours=3), datetime.timedelta(hours=24),
               "© Union européenne, Copernicus EFFIS"),
        # Publiée une fois par jour à 17 h, de juin à septembre. Hors saison le relevé réussit
        # « à vide » : la source n'est donc jamais signalée périmée l'hiver.
        Source("METEO_FORETS", "Météo des forêts (danger de feu)", meteo_forets.relever,
               datetime.timedelta(hours=3), datetime.timedelta(hours=30), "Météo-France"),
        # Un bulletin par jour et par massif, publié vers 16 h : quatre relevés par jour.
        Source("AVALANCHE", "Risque d'avalanche par massif", avalanche.relever,
               datetime.timedelta(hours=6), datetime.timedelta(hours=36), "Météo-France"),
        # Le service ne reçoit les mesures que par paquets, avec du retard : un relevé toutes les
        # vingt minutes n'en perd aucune, et ménage un service qui n'est pas une API publiée.
        Source("RADIOACTIVITE", "Radioactivité ambiante (balises Téléray)", radioactivite.relever,
               datetime.timedelta(minutes=19), datetime.timedelta(hours=3),
               "ASNR - réseau Téléray"),
        # Affichage des trente derniers jours. L'ALERTE sismique, elle, a sa propre commande
        # toutes les deux minutes (verifier_alertes_sismiques) : rien à accélérer ici.
        Source("SEISMES", "Séismes des trente derniers jours", seismes.relever,
               datetime.timedelta(minutes=29), datetime.timedelta(hours=6),
               "BCSF-Rénass (EOST) et observatoires de l'IPGP"),
        Source("TRAFIC_ROUTIER", "Événements routiers", trafic_routier.relever,
               datetime.timedelta(minutes=9), datetime.timedelta(hours=1),
               "Bison Futé - ministère chargé des transports"),
        # Les stations se déclarent au fil de la journée : une demi-heure suffit à voir une
        # pénurie s'installer, et 6 Mo toutes les dix minutes seraient du gaspillage.
        # Un fichier de 80 Mo, qui change au rythme des arrêtés municipaux : une fois par jour.
        Source("ARRETES_CIRCULATION", "Arrêtés de circulation des collectivités",
               arretes_circulation.relever, datetime.timedelta(hours=23),
               datetime.timedelta(hours=72), "DiaLog - ministère chargé des transports"),
        # Données hebdomadaires, publiées avec une dizaine de jours de recul : un relevé par jour
        # suffit, et « périmé » ne veut dire ici que « le relevé ne tourne plus ».
        Source("SANTE_URGENCES", "Recours aux urgences par pathologie", sante_urgences.relever,
               datetime.timedelta(hours=23), datetime.timedelta(hours=72),
               "Santé publique France (réseaux OSCOUR et SOS Médecins)"),
        # 80 Mo à lire en flot, pour une base qui bouge peu : une fois par jour.
        Source("DEFIBRILLATEURS", "Défibrillateurs (base nationale Géo'DAE)", defibrillateurs.relever,
               datetime.timedelta(hours=23), datetime.timedelta(hours=96),
               "Géo'DAE - ministère de la Santé"),
        Source("CARBURANTS", "Stations de carburant", carburants.relever,
               datetime.timedelta(minutes=29), datetime.timedelta(hours=3),
               "Prix des carburants - ministère de l'Économie"),
    )
}


def etat(code):
    from .models import ReleveSourceOuverte

    return ReleveSourceOuverte.objects.filter(pk=code).first()


def est_perime(code, maintenant=None):
    """Vrai si la copie de cette source est trop ancienne (ou n'existe pas)."""
    trace = etat(code)
    if trace is None or trace.dernier_succes is None:
        return True
    return (maintenant or timezone.now()) - trace.dernier_succes > SOURCES[code].perime_apres


def resume(code, maintenant=None):
    """Ce qu'un écran doit savoir de la fraîcheur d'une source."""
    source, trace = SOURCES[code], etat(code)
    return {
        "source": source.attribution,
        "releve_le": trace.dernier_succes if trace else None,
        "perime": est_perime(code, maintenant),
    }


def relever_source(code, forcer=False, maintenant=None):
    """Relève une source si son intervalle est écoulé. Rend « ignoré », « réussi » ou « échec ».

    Jamais d'exception vers l'appelant : une source en panne ne doit pas empêcher le relevé des
    autres, ni faire échouer la tâche planifiée."""
    from .models import ReleveSourceOuverte

    source = SOURCES[code]
    maintenant = maintenant or timezone.now()
    trace, _ = ReleveSourceOuverte.objects.get_or_create(pk=code)
    if not forcer and trace.dernier_succes and maintenant - trace.dernier_succes < source.intervalle:
        return "ignoré"

    trace.dernier_essai = maintenant
    try:
        lignes = source.relever()
    except meteo_france.CleAbsente:
        trace.erreur = "aucune clé sur cette machine"
        trace.save(update_fields=["dernier_essai", "erreur"])
        return "échec"
    except Exception as exc:
        # Tout attraper est voulu ici : réseau, format inattendu, base -- quelle que soit la
        # cause, la trace doit l'enregistrer et les autres sources doivent être relevées.
        logger.warning("Relevé %s impossible : %s", code, exc)
        trace.erreur = f"{type(exc).__name__} : {exc}"[:500]
        trace.save(update_fields=["dernier_essai", "erreur"])
        return "échec"

    trace.dernier_succes = timezone.now()
    trace.lignes = lignes
    trace.erreur = ""
    trace.save()
    return "réussi"
