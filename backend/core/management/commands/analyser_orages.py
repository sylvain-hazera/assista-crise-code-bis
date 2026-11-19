"""Analyse des orages selon les relevés radar de Météo-France (core/orages.py).

    python manage.py analyser_orages              # une analyse, si une image nouvelle est parue
    python manage.py analyser_orages --service    # en continu : regarde chaque minute

Le radar produit une image toutes les cinq minutes ; le cron de la veille ne passe que toutes
les dix. D'où ce service à part, qui laisse la même trace que les autres sources
(`ReleveSourceOuverte`, code ORAGES_RADAR) : la page de veille et la supervision disent ainsi
quand l'analyse ne se rafraîchit plus. Un seul exemplaire à la fois (verrou de fichier).
"""
import fcntl
import os
import tempfile
import time

from django.core.management.base import BaseCommand

from core import sources_ouvertes


class Command(BaseCommand):
    help = "Analyse la dernière image radar (orages et pluies intenses)."

    def add_arguments(self, parseur):
        parseur.add_argument("--service", action="store_true", help="Tourner en continu.")

    def handle(self, *args, **options):
        verrou = open(os.path.join(tempfile.gettempdir(), "analyser-orages.verrou"), "w")
        try:
            fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.stdout.write("Une analyse des orages tourne déjà.")
            return
        try:
            while True:
                # La foudre d'abord : les éclairs servent à l'analyse des cellules.
                for code, unite in (("FOUDRE_MTG", "éclair(s) ajouté(s)"), ("ORAGES_RADAR", "cellule(s)"),
                                    ("DOPPLER_RADAR", "cellule(s) examinée(s) au Doppler")):
                    resultat = sources_ouvertes.relever_source(code)
                    if resultat != "ignoré":
                        trace = sources_ouvertes.etat(code)
                        self.stdout.write(f"{code} : {resultat} ({trace.lignes if trace else 0} {unite})"
                                          + (f" -- {trace.erreur}" if trace and trace.erreur else ""))
                if not options["service"]:
                    return
                time.sleep(60)
        finally:
            verrou.close()
