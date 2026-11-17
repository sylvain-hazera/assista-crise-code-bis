from django.core.management.base import BaseCommand
from django.utils import timezone

from core import cloture_crise
from core.audit import audit_log
from core.models import Notification, ContactInstitution, ImplicationInstitution


class Command(BaseCommand):
    help = (
        "Clôt les crises dont la clôture a été proposée et dont l'échéance (sept jours) est passée "
        "(core/cloture_crise.py) : date de fin, purge des demandes/offres/signalements déjà désactivés, "
        "effacement des rapports gardés et des liens de remise. Jamais une crise d'essai. À planifier "
        "(toutes les heures suffit)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Dit ce qui serait clos, sans rien faire.")

    def handle(self, *args, **options):
        crises = list(cloture_crise.a_cloturer())
        if not crises:
            self.stdout.write("Aucune crise à clore.")
            return
        for crise in crises:
            echeance = timezone.localtime(crise.fermeture_prevue_le).strftime("%d/%m/%Y %H:%M")
            if options["dry_run"]:
                self.stdout.write(f"Serait close : {crise.name} (échéance {echeance})")
                continue
            bilan = cloture_crise.cloturer(crise)
            audit_log(
                request=None, action_code="CLOTURE", objet_type="Crisis", objet_id=crise.id, crise=crise,
                ancien_etat="OUVERTE", nouvel_etat="CLOTUREE",
                commentaire=f"Crise {crise.name} close à l'échéance de sa proposition de clôture ({echeance}) ; "
                            f"{bilan['rapports_effaces']} rapport(s) gardé(s) effacé(s)",
            )
            institutions = ImplicationInstitution.objects.filter(crise=crise, actif=True).values_list("institution_id", flat=True).distinct()
            for contact in ContactInstitution.objects.filter(institution_id__in=institutions, actif=True):
                Notification.objects.create(
                    utilisateur=contact.utilisateur, titre=f"Crise clôturée : {crise.name}",
                    message=f"La crise « {crise.name} » a été close à l'échéance de sa proposition de clôture.",
                    environment=crise.environment, crise=crise)
            self.stdout.write(self.style.SUCCESS(f"Close : {crise.name}"))
