"""Pose sur la carte les signalements du public déjà en base (26/11/2026).

Les nouveaux signalements deviennent des marqueurs d'eux-mêmes (core/marqueurs_terrain.py) ;
ceux d'avant ne le sont pas. Cette commande les convertit, à la demande :

    python manage.py marqueurs_des_signalements            # liste ce qui serait posé
    python manage.py marqueurs_des_signalements --poser    # pose (et émet par radio)

Seuls les signalements actifs d'une crise ouverte sont concernés ; un signalement déjà posé
n'est pas reposé.
"""
from django.core.management.base import BaseCommand

from core import marqueurs_terrain as mt
from core.models import Information, MarqueurTerrain


class Command(BaseCommand):
    help = "Pose sur la carte les signalements du public d'avant le 26/11/2026."

    def add_arguments(self, parser):
        parser.add_argument("--poser", action="store_true", help="Poser vraiment (sinon : liste seulement).")

    def handle(self, *args, **options):
        deja = set(MarqueurTerrain.objects.filter(signalement_id__isnull=False).values_list("signalement_id", flat=True))
        poses = candidats = 0
        for info in Information.objects.filter(actif=True).select_related("crisis", "information_type").order_by("created_at"):
            if info.id in deja or info.location is None or mt.crise_du_signalement(info) is None:
                continue
            candidats += 1
            if options["poser"] and mt.signalement_en_marqueur(info) is not None:
                poses += 1
        if options["poser"]:
            self.stdout.write(f"{poses} signalement(s) posé(s) sur la carte, sur {candidats}.")
        else:
            self.stdout.write(f"{candidats} signalement(s) à poser. Relancer avec --poser pour le faire.")
