from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.db import transaction

from core.models import Crise, Demande, Offre, Information

class Command(BaseCommand):

    def handle(self, *args, **kwargs):
        limit_date = timezone.now() - timedelta(days=30)
        
        self.stdout.write(f"Recherche des crises terminées avant le {limit_date}...")

        expired_crises = Crise.objects.filter(
            date_fin__lt=limit_date, 
            date_fin__isnull=False
        )
        
        count_crises = expired_crises.count()

        if count_crises == 0:
            self.stdout.write("Aucune crise expirée à nettoyer.")
            return

        self.stdout.write(f"Trouvé {count_crises} crise(s) à purger.")


        # Suppression manuelle (à cause du SET_NULL)
        with transaction.atomic():
            total_demandes = 0
            total_offres = 0
            total_infos = 0

            for crise in expired_crises:
                self.stdout.write(f" - Nettoyage de la crise : {crise.nom}")

                del_d, _ = Demande.objects.filter(crise=crise).delete()
                total_demandes += del_d

                del_o, _ = Offre.objects.filter(crise=crise).delete()
                total_offres += del_o

                del_i, _ = Information.objects.filter(crise=crise).delete()
                total_infos += del_i

                crise.delete()

        self.stdout.write(self.style.SUCCESS(
            f"NETTOYAGE TERMINÉ :\n"
            f" - Crises supprimées : {count_crises}\n"
            f" - Demandes supprimées : {total_demandes}\n"
            f" - Offres supprimées : {total_offres}\n"
            f" - Infos supprimées : {total_infos}"
        ))