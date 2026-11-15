"""Relève les sources ouvertes de la veille du territoire (vigilance Météo-France, événements
routiers, stations de carburant) et annonce la vigilance aux institutions qui l'ont demandée --
voir core/sources_ouvertes.py pour la règle commune.

Un coup par exécution, lancé par cron toutes les dix minutes (même patron que
verifier_alertes_sismiques : ce projet n'a pas de celery-beat). Chaque source a son propre
rythme : la commande ne relève que celles dont l'intervalle est écoulé.

    manage.py relever_sources_ouvertes                      # ce qui est dû
    manage.py relever_sources_ouvertes --forcer             # tout, tout de suite
    manage.py relever_sources_ouvertes --source CARBURANTS  # une seule source
"""
from django.core.management.base import BaseCommand

from core import meteo_france, sources_ouvertes


class Command(BaseCommand):
    help = "Relève les sources ouvertes de la veille et annonce la vigilance aux institutions abonnées."

    def add_arguments(self, parser):
        parser.add_argument("--source", choices=sorted(sources_ouvertes.SOURCES),
                            help="Ne relever que cette source.")
        parser.add_argument("--forcer", action="store_true",
                            help="Relever même si l'intervalle n'est pas écoulé.")

    def handle(self, *args, **options):
        codes = [options["source"]] if options["source"] else list(sources_ouvertes.SOURCES)
        resultats = {
            code: sources_ouvertes.relever_source(code, forcer=options["forcer"]) for code in codes
        }

        # L'annonce ne suit qu'un relevé RÉUSSI à l'instant : sur une copie non rafraîchie il
        # n'y a rien de neuf à annoncer, et diffuser_alertes refuse de toute façon une copie
        # trop ancienne.
        annonces = []
        if resultats.get("VIGILANCE_METEO") == "réussi":
            annonces = meteo_france.diffuser_alertes()

        detail = ", ".join(f"{code} {resultat}" for code, resultat in resultats.items())
        self.stdout.write(f"Veille : {detail} ; {len(annonces)} annonce(s) de vigilance.")
