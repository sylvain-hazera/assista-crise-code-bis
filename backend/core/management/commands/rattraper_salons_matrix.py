"""Crée les salons Matrix qui manquent à l'existant : institutions, équipes, missions.

Depuis le 16/11/2026 tout objet naît avec ses salons (voir core/salons_matrix.py). Cette
commande rattrape ce qui existait avant, et reprend ce qu'un incident aurait fait manquer. Elle
ne crée que des lignes ; le pont matrix-bridge crée les salons côté Synapse à son passage
suivant. Idempotente : la relancer ne crée rien de plus.

    manage.py rattraper_salons_matrix              # crée ce qui manque
    manage.py rattraper_salons_matrix --simulation # dit ce qui manque, sans rien créer
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core import salons_matrix


class Command(BaseCommand):
    help = "Crée les salons Matrix manquants des institutions, équipes et missions existantes."

    def add_arguments(self, parser):
        parser.add_argument("--simulation", action="store_true",
                            help="Compte ce qui serait créé, sans rien écrire.")

    def handle(self, *args, **options):
        if options["simulation"]:
            with transaction.atomic():
                bilan = salons_matrix.rattraper()
                transaction.set_rollback(True)
            verbe = "à créer"
        else:
            bilan = salons_matrix.rattraper()
            verbe = "créés"
        self.stdout.write(
            f"Salons Matrix {verbe} : {bilan['institutions']} d'institution, "
            f"{bilan['equipes']} d'équipe, {bilan['missions']} de mission.")
