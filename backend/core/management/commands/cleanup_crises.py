from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from django.db import transaction
import csv
import os
from pathlib import Path

from core.models import Crise, Demande, Offre, Information

class Command(BaseCommand):
    
    def get_archive_path(self):
        """Retourne le chemin du fichier CSV d'archivage"""
        media_root = Path('media')
        archive_dir = media_root / 'archives'
        archive_dir.mkdir(parents=True, exist_ok=True)
        return archive_dir / 'crises_supprimees.csv'

    def export_crise_to_csv(self, crise, demandes, offres, informations):
        """Exporte les données d'une crise supprimée dans le CSV"""
        csv_path = self.get_archive_path()
        file_exists = csv_path.exists()
        
        with open(csv_path, 'a', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'date_suppression', 'crise_id', 'crise_name', 
                'crise_location_lat', 'crise_location_lon',
                'start_date', 'end_date', 'validator_username',
                'nb_demandes', 'nb_offres', 'nb_informations',
                'demandes_details', 'offres_details', 'informations_details'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
            
            # Récupérer les détails
            demandes_list = list(demandes)
            offres_list = list(offres)
            infos_list = list(informations)
            
            # Formater les détails pour le CSV
            demandes_str = ' | '.join([
                f"{d.titre} (statut:{d.statut}, auteur:{d.auteur.username if d.auteur else 'N/A'})"
                for d in demandes_list
            ]) if demandes_list else 'Aucune'
            
            offres_str = ' | '.join([
                f"{o.titre} (statut:{o.statut}, auteur:{o.auteur.username if o.auteur else 'N/A'})"
                for o in offres_list
            ]) if offres_list else 'Aucune'
            
            infos_str = ' | '.join([
                f"{i.titre} (statut:{i.statut}, auteur:{i.auteur.username if i.auteur else 'N/A'})"
                for i in infos_list
            ]) if infos_list else 'Aucune'
            
            writer.writerow({
                'date_suppression': timezone.now().isoformat(),
                'crise_id': str(crise.id),
                'crise_name': crise.name,
                'crise_location_lat': crise.location.y if crise.location else '',
                'crise_location_lon': crise.location.x if crise.location else '',
                'start_date': crise.start_date.isoformat() if crise.start_date else '',
                'end_date': crise.end_date.isoformat() if crise.end_date else '',
                'validator_username': crise.validator.username if crise.validator else 'N/A',
                'nb_demandes': len(demandes_list),
                'nb_offres': len(offres_list),
                'nb_informations': len(infos_list),
                'demandes_details': demandes_str,
                'offres_details': offres_str,
                'informations_details': infos_str
            })
        
        self.stdout.write(f"   → Données archivées dans {csv_path}")

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

                # Récupérer les données AVANT la suppression pour l'archivage
                demandes = Demande.objects.filter(crise=crise)
                offres = Offre.objects.filter(crise=crise)
                informations = Information.objects.filter(crise=crise)
                
                # Exporter dans le CSV
                self.export_crise_to_csv(crise, demandes, offres, informations)

                # Maintenant on peut supprimer
                del_d, _ = demandes.delete()
                total_demandes += del_d

                del_o, _ = offres.delete()
                total_offres += del_o

                del_i, _ = informations.delete()
                total_infos += del_i

                crise.delete()

        csv_path = self.get_archive_path()
        self.stdout.write(self.style.SUCCESS(
            f"NETTOYAGE TERMINÉ :\n"
            f" - Crises supprimées : {count_crises}\n"
            f" - Demandes supprimées : {total_demandes}\n"
            f" - Offres supprimées : {total_offres}\n"
            f" - Infos supprimées : {total_infos}\n"
            f" - Archive CSV : {csv_path}"
        ))