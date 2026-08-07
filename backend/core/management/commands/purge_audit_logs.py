from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from core.models import AuditLog


class Command(BaseCommand):
    help = (
        "Purge les entrées de la main courante (AuditLog) plus anciennes que "
        "AUDIT_LOG_RETENTION_DAYS (principe de minimisation RGPD). "
        "À planifier régulièrement via cron/celery-beat."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="N'affiche que le nombre de lignes qui seraient supprimées, sans les supprimer.",
        )

    def handle(self, *args, **options):
        retention_days = settings.AUDIT_LOG_RETENTION_DAYS
        limit_date = timezone.now() - timedelta(days=retention_days)

        expired = AuditLog.objects.filter(date_action__lt=limit_date)
        count = expired.count()

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] {count} entrée(s) de main courante antérieure(s) au "
                f"{limit_date.isoformat()} (rétention : {retention_days} jours) seraient supprimées."
            )
            return

        if count == 0:
            self.stdout.write("Aucune entrée de main courante à purger.")
            return

        deleted, _ = expired.delete()
        self.stdout.write(self.style.SUCCESS(
            f"Purge terminée : {deleted} entrée(s) de main courante supprimée(s) "
            f"(antérieures au {limit_date.isoformat()}, rétention : {retention_days} jours)."
        ))
