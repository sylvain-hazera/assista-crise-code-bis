from django.core.management.base import BaseCommand

from core import alertes_stock
from core.models import DepotStock, Environment, Institution


class Command(BaseCommand):
    help = (
        "Stocks (core/alertes_stock.py) : envoie à chaque institution le relevé de ses alertes (seuil "
        "franchi, lot périmé ou bientôt, denrée mal rangée, prêt en retard, facture échue), seulement "
        "s'il a changé depuis le dernier envoi. À planifier une fois par jour."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Dit ce qui partirait, sans rien envoyer.")
        parser.add_argument("--forcer", action="store_true", help="Renvoie le relevé même s'il n'a pas changé.")

    def handle(self, *args, **options):
        # Jamais la zone de démonstration : ses stocks sont factices, ses courriels seraient du bruit.
        institutions = Institution.objects.filter(pk__in=DepotStock.objects.filter(environment=Environment.PROD).values("institution_id"))
        envoyes = 0
        for institution in institutions:
            bilan = alertes_stock.envoyer(institution, Environment.PROD, forcer=options["forcer"], simuler=options["dry_run"])
            if bilan["envoye"] or (options["dry_run"] and bilan["destinataires"]):
                envoyes += 1
                self.stdout.write(f"{bilan['institution']} : {bilan['alertes']} alerte(s), {bilan['destinataires']} destinataire(s)")
        self.stdout.write(f"{envoyes} relevé(s) {'à envoyer' if options['dry_run'] else 'envoyé(s)'}.")
