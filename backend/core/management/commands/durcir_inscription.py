"""Durcit, pour un temps, le calcul demandé à la création de compte.

À utiliser pendant une vague de faux comptes : tout le monde paie alors un calcul plus long,
quels que soient son adresse et son navigateur (voir core/defi_inscription.py).

    python manage.py durcir_inscription                  # l'état actuel
    python manage.py durcir_inscription ELEVE            # une à deux secondes sur un téléphone, 2 h
    python manage.py durcir_inscription FORT --heures 6  # dix à vingt secondes, 6 h
    python manage.py durcir_inscription NORMAL           # retour à la normale tout de suite

Le réglage s'efface tout seul à l'échéance : il ne peut pas être oublié.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand

from core import defi_inscription


class Command(BaseCommand):
    help = "Durcit pour un temps le calcul anti-robot de la création de compte."

    def add_arguments(self, parser):
        parser.add_argument("niveau", nargs="?", choices=defi_inscription.ORDRE)
        parser.add_argument("--heures", type=float, default=2.0)

    def handle(self, *args, **options):
        niveau = options["niveau"]
        if niveau:
            defi_inscription.imposer_niveau(niveau, timedelta(hours=options["heures"]))
        actuel = defi_inscription.niveau_impose()
        if actuel == defi_inscription.NORMAL:
            self.stdout.write("Niveau imposé : aucun (le calcul suit les compteurs).")
        else:
            self.stdout.write(f"Niveau imposé : {actuel}"
                              + (f", pour {options['heures']:g} h." if niveau else "."))
        self.stdout.write(f"Compteurs échus effacés : {defi_inscription.purger()}.")
