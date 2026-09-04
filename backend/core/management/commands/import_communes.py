import json
import urllib.parse
import urllib.request

from django.core.management.base import BaseCommand, CommandError

from core.models import Commune

GEO_API = "https://geo.api.gouv.fr"


class Command(BaseCommand):
    help = (
        "Charge en masse le référentiel Commune (nom/population/EPCI/département/centroïde) "
        "pour un ou plusieurs départements, via un appel groupé par département plutôt que le "
        "résolveur commune-par-commune de geo_lookup.py (bien trop lent pour ~35000 communes). "
        "Nécessaire avant de générer des données réparties par population de commune."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "departements", nargs="+",
            help="Codes département à charger (ex: 38 73 69), ou 'all' pour les 101.",
        )

    def handle(self, *args, **options):
        deps = options["departements"]
        if deps == ["all"]:
            deps = self._all_departement_codes()

        total = 0
        for dep in deps:
            total += self._import_departement(dep)
        self.stdout.write(self.style.SUCCESS(f"Total : {total} communes chargées/mises à jour."))

    def _all_departement_codes(self):
        data = self._fetch(f"{GEO_API}/departements?fields=code")
        if not data:
            raise CommandError("Impossible de récupérer la liste des départements.")
        return [d["code"] for d in data]

    def _import_departement(self, dep_code):
        url = (
            f"{GEO_API}/departements/{urllib.parse.quote(dep_code)}/communes"
            "?fields=nom,code,population,codeDepartement,codeEpci,codeRegion,centre&format=json"
        )
        data = self._fetch(url)
        if not data:
            self.stdout.write(self.style.WARNING(f"  {dep_code}: aucune donnée (département invalide ?)"))
            return 0

        objs = []
        for c in data:
            centre = (c.get("centre") or {}).get("coordinates")
            lon, lat = (centre[0], centre[1]) if isinstance(centre, list) and len(centre) == 2 else (None, None)
            objs.append(Commune(
                code=c["code"],
                nom=c.get("nom"),
                population=c.get("population"),
                departement_code=c.get("codeDepartement"),
                epci_code=c.get("codeEpci"),
                region_code=c.get("codeRegion"),
                centre_longitude=lon,
                centre_latitude=lat,
            ))

        Commune.objects.bulk_create(
            objs,
            update_conflicts=True,
            unique_fields=["code"],
            update_fields=["nom", "population", "departement_code", "epci_code", "region_code", "centre_longitude", "centre_latitude"],
        )
        self.stdout.write(f"  {dep_code}: {len(objs)} communes")
        return len(objs)

    def _fetch(self, url):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            self.stdout.write(self.style.ERROR(f"  erreur réseau ({url}): {exc}"))
            return None
