from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
import csv
from pathlib import Path

from core.models import Crisis, Request, Offer, Information

class Command(BaseCommand):
    help = (
        "Purge les demandes, offres et signalements des habitants pour les crises closes "
        "depuis plus de 30 jours (principe de minimisation RGPD) — archive un résumé (jamais "
        "les coordonnées) dans un CSV avant suppression. Planifiée par cron "
        "(scripts/114/purger-crises-closes.sh).\n\n"
        "LA CRISE N'EST PAS SUPPRIMÉE (17/11/2026). Elle l'était, à une époque où elle ne "
        "portait que ces trois listes. Sa suppression emporterait aujourd'hui en cascade la "
        "main courante, les rapports conservés, le référencement des dégâts, les biens "
        "sinistrés et les dossiers de relogement — tout le suivi « post-critique », qui dure "
        "des mois. Leur durée de conservation est une décision à part, pas un effet de bord."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="N'affiche que ce qui serait purgé, sans rien supprimer ni archiver.",
        )

    def get_archive_path(self):
        """Retourne le chemin du fichier CSV d'archivage"""
        media_root = Path('media')
        archive_dir = media_root / 'archives'
        archive_dir.mkdir(parents=True, exist_ok=True)
        return archive_dir / 'crises_supprimees.csv'

    def export_crise_to_csv(self, crise, demandes, offres, informations):
        """Exporte un résumé (jamais les coordonnées des personnes) de la crise supprimée."""
        csv_path = self.get_archive_path()
        file_exists = csv_path.exists()

        with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'date_suppression', 'crise_id', 'crise_name',
                'crise_location_lat', 'crise_location_lon',
                'start_date', 'end_date', 'validator_username',
                'nb_demandes', 'nb_offres', 'nb_informations',
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()

            writer.writerow({
                'date_suppression': timezone.now().isoformat(),
                'crise_id': str(crise.id),
                'crise_name': crise.name,
                'crise_location_lat': crise.location.y if crise.location else '',
                'crise_location_lon': crise.location.x if crise.location else '',
                'start_date': crise.start_date.isoformat() if crise.start_date else '',
                'end_date': crise.end_date.isoformat() if crise.end_date else '',
                'validator_username': crise.validator.username if crise.validator else 'N/A',
                'nb_demandes': demandes.count(),
                'nb_offres': offres.count(),
                'nb_informations': informations.count(),
            })

        self.stdout.write(f"   → Résumé archivé dans {csv_path}")

    def handle(self, *args, **options):
        limit_date = timezone.now() - timedelta(days=30)

        self.stdout.write(f"Recherche des crises terminées avant le {limit_date}...")

        expired_crises = Crisis.objects.filter(
            end_date__lt=limit_date,
            end_date__isnull=False,
            donnees_habitants_purgees_le__isnull=True,
        )

        count_crises = expired_crises.count()

        if count_crises == 0:
            self.stdout.write("Aucune crise close à purger.")
            return

        self.stdout.write(f"Trouvé {count_crises} crise(s) à purger.")

        if options["dry_run"]:
            for crise in expired_crises:
                self.stdout.write(
                    f" - [dry-run] {crise.name} ({Request.objects.filter(crisis=crise).count()} demande(s), "
                    f"{Offer.objects.filter(crisis=crise).count()} offre(s), "
                    f"{Information.objects.filter(crisis=crise).count()} signalement(s))"
                )
            return

        total_demandes = 0
        total_offres = 0
        total_infos = 0

        for crise in expired_crises:
            # Une transaction par crise : un échec sur l'une ne défait pas les autres.
            with transaction.atomic():
                self.stdout.write(f" - Purge des données d'habitants de la crise : {crise.name}")

                demandes = Request.objects.filter(crisis=crise)
                offres = Offer.objects.filter(crisis=crise)
                informations = Information.objects.filter(crisis=crise)

                self.export_crise_to_csv(crise, demandes, offres, informations)

                del_d, _ = demandes.delete()
                total_demandes += del_d

                del_o, _ = offres.delete()
                total_offres += del_o

                del_i, _ = informations.delete()
                total_infos += del_i

                crise.donnees_habitants_purgees_le = timezone.now()
                crise.save(update_fields=["donnees_habitants_purgees_le"])

        csv_path = self.get_archive_path()
        self.stdout.write(self.style.SUCCESS(
            f"PURGE TERMINÉE :\n"
            f" - Crises traitées (conservées) : {count_crises}\n"
            f" - Demandes supprimées : {total_demandes}\n"
            f" - Offres supprimées : {total_offres}\n"
            f" - Signalements supprimés : {total_infos}\n"
            f" - Archive CSV : {csv_path}"
        ))
