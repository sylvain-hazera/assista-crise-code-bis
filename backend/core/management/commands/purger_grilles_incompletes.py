"""Purge les grilles d'altitude IGN incomplètes encore en cache, et tout ce qui en a été dérivé
(paliers d'inondation, adresses simulées, ruissellement, état des tâches) -- tout sera recalculé
à la prochaine ouverture de la commune, avec les relances IGN et le refus des grilles trouées
(voir inondation.grille_altitude_commune, correctif du 20/10/2026).

Une grille est jugée incomplète si elle contient moins de COUVERTURE_MIN_GRILLE des points
attendus pour la commune (recalculés depuis son contour officiel geo.api.gouv.fr).

    python manage.py purger_grilles_incompletes            # simulation : liste sans rien supprimer
    python manage.py purger_grilles_incompletes --appliquer
"""
import numpy as np
from django.core.management.base import BaseCommand

from core.inondation import COUVERTURE_MIN_GRILLE, _bbox_commune, _grille_points_bbox
from core.models import (
    AdresseSimuleeInondation, GrilleAltimetrieCommune, GrilleRuissellementCommune,
    PalierInondationSimule, TacheSimulationInondation,
)

MODELES_DERIVES = (PalierInondationSimule, AdresseSimuleeInondation, GrilleRuissellementCommune, TacheSimulationInondation)


class Command(BaseCommand):
    help = "Purge les grilles d'altitude incomplètes (et leurs résultats dérivés) pour recalcul."

    def add_arguments(self, parser):
        parser.add_argument("--appliquer", action="store_true", help="Supprime vraiment (sinon simulation).")

    def handle(self, *args, **options):
        appliquer = options["appliquer"]
        bbox_par_commune = {}
        incompletes = 0
        for grille in GrilleAltimetrieCommune.objects.all().order_by("environment", "commune_code"):
            code = grille.commune_code
            if code not in bbox_par_commune:
                bbox_par_commune[code] = _bbox_commune(code)
            bbox = bbox_par_commune[code]
            if bbox is None:
                self.stdout.write(f"  ? {grille.environment} {code} : contour indisponible, ignorée")
                continue
            lons, lats = _grille_points_bbox(bbox, grille.pas_metres)
            attendus = len(np.meshgrid(lons, lats)[0].ravel())
            presents = len(grille.points or [])
            if presents >= attendus * COUVERTURE_MIN_GRILLE:
                continue
            incompletes += 1
            self.stdout.write(f"  - {grille.environment} {code} : {presents}/{attendus} points ({presents * 100 // max(attendus, 1)} %)")
            if appliquer:
                for modele in MODELES_DERIVES:
                    modele.objects.filter(commune_code=code, environment=grille.environment).delete()
                grille.delete()

        verbe = "purgées" if appliquer else "à purger (relancer avec --appliquer)"
        self.stdout.write(self.style.SUCCESS(f"{incompletes} grille(s) incomplète(s) {verbe}."))
