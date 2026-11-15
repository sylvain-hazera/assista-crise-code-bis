"""Relève les sources ouvertes de la veille du territoire (voir la liste dans
core/sources_ouvertes.py, qui porte aussi la règle commune) et annonce la vigilance
Météo-France aux institutions qui l'ont demandée.

Un coup par exécution, lancé par cron toutes les dix minutes (même patron que
verifier_alertes_sismiques : ce projet n'a pas de celery-beat). Chaque source a son propre
rythme : la commande ne relève que celles dont l'intervalle est écoulé.

    manage.py relever_sources_ouvertes                      # ce qui est dû
    manage.py relever_sources_ouvertes --forcer             # tout, tout de suite
    manage.py relever_sources_ouvertes --source CARBURANTS  # une seule source
"""
import fcntl
import os
import tempfile

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
        # Un seul relevé à la fois, quelle que soit la façon dont il est lancé (cron, à la
        # main, script de déploiement). Constaté le 15/11/2026 : deux relevés forcés en même
        # temps doublent les appels à Météo-France, dont le débit est compté. Le verrou est un
        # fichier du conteneur ; il se libère de lui-même si le processus meurt.
        verrou = open(os.path.join(tempfile.gettempdir(), "relever-sources-ouvertes.verrou"), "w")
        try:
            fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            verrou.close()
            self.stdout.write("Veille : un relevé est déjà en cours, celui-ci se retire.")
            return
        try:
            self._relever(options)
        finally:
            verrou.close()

    def _relever(self, options):
        codes = [options["source"]] if options["source"] else list(sources_ouvertes.SOURCES)
        resultats, annonces = {}, []
        for code in codes:
            resultats[code] = sources_ouvertes.relever_source(code, forcer=options["forcer"])
            # L'annonce part AUSSITÔT la vigilance relevée, sans attendre les autres sources :
            # certaines sont longues (35 bulletins d'avalanche, un fichier de 80 Mo pour les
            # arrêtés de circulation) et une vigilance orange n'a pas à patienter derrière elles.
            # Elle ne suit qu'un relevé RÉUSSI à l'instant : sur une copie non rafraîchie il n'y
            # a rien de neuf à annoncer, et diffuser_alertes refuse de toute façon une copie
            # trop ancienne.
            if code == "VIGILANCE_METEO" and resultats[code] == "réussi":
                annonces = meteo_france.diffuser_alertes()

        detail = ", ".join(f"{code} {resultat}" for code, resultat in resultats.items())
        self.stdout.write(f"Veille : {detail} ; {len(annonces)} annonce(s) de vigilance.")
