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

from core import sources_ouvertes


class Command(BaseCommand):
    help = "Relève les sources ouvertes de la veille et annonce la vigilance aux institutions abonnées."

    def add_arguments(self, parser):
        parser.add_argument("--source", choices=sorted(sources_ouvertes.SOURCES),
                            help="Ne relever que cette source.")
        parser.add_argument("--forcer", action="store_true",
                            help="Relever même si l'intervalle n'est pas écoulé.")
        parser.add_argument("--departement", action="append", default=[],
                            help="Points d'eau OSM : relever ce département maintenant (répétable), "
                                 "hors de la rotation.")

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
        if options["departement"]:
            from core import points_eau_osm
            for code in options["departement"]:
                try:
                    nombre = points_eau_osm.relever(departement=code.upper())
                    self.stdout.write(f"Points d'eau OSM : département {code.upper()}, {nombre} points.")
                except Exception as erreur:   # noqa: BLE001 - on dit l'échec et on passe au suivant
                    self.stdout.write(f"Points d'eau OSM : département {code.upper()} en échec ({erreur}).")
            return
        codes = [options["source"]] if options["source"] else [
            code for code in sources_ouvertes.SOURCES if code not in sources_ouvertes.SOURCES_EN_CONTINU]
        from core import alertes_naturelles

        resultats, alertes = {}, []
        for code in codes:
            resultats[code] = sources_ouvertes.relever_source(code, forcer=options["forcer"])
            # Les alertes automatiques des collectivités (24/11/2026) partent AUSSITÔT la source
            # relevée, sans attendre les autres : certaines sont longues (35 bulletins
            # d'avalanche, 80 Mo d'arrêtés) et une vigilance orange n'a pas à patienter derrière
            # elles. Seulement après un relevé RÉUSSI : sur une copie non rafraîchie il n'y a
            # rien de neuf. Les phénomènes rapides passent toutes les deux minutes
            # (verifier_alertes_sismiques).
            phenomenes = alertes_naturelles.phenomenes_de_source(code)
            if phenomenes and resultats[code] == "réussi":
                alertes += alertes_naturelles.evaluer(phenomenes)

        detail = ", ".join(f"{code} {resultat}" for code, resultat in resultats.items())
        self.stdout.write(f"Veille : {detail} ; {len(alertes)} alerte(s) automatique(s).")
