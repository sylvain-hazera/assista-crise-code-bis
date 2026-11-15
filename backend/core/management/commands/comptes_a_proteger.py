"""Liste les comptes à pouvoir qui n'ont pas encore de second facteur, avec leur échéance.

    manage.py comptes_a_proteger

À lire avant l'échéance des quinze jours : un compte de cette liste qui est en réalité utilisé
par un programme (pont Matrix, script…) cessera de se connecter à sa date limite. Le marquer :

    manage.py marquer_compte_machine <email>

L'échéance d'un compte n'est posée qu'à sa première connexion après la mise en place : « pas
encore vu » veut dire que ses quinze jours n'ont pas commencé.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core import second_facteur
from core.models import User


class Command(BaseCommand):
    help = "Comptes à pouvoir sans second facteur, et leur date limite."

    def handle(self, *args, **options):
        if not second_facteur.applicable():
            self.stdout.write("Sur un satellite, aucun second facteur n'est demandé.")
            return
        maintenant = timezone.now()
        concernes = [
            compte for compte in User.objects.filter(is_active=True).order_by('date_joined')
            if second_facteur.est_a_pouvoir(compte) and second_facteur.second_facteur_actif(compte) is None
        ]
        proteges = sum(
            1 for compte in User.objects.filter(is_active=True, second_facteur__confirme_le__isnull=False))
        self.stdout.write(f"Comptes protégés par un second facteur : {proteges}")
        self.stdout.write(f"Comptes à pouvoir qui n'en ont pas encore : {len(concernes)}")
        for compte in concernes:
            limite = compte.second_facteur_exige_le
            if limite is None:
                echeance = "pas encore vu (délai non commencé)"
            elif limite <= maintenant:
                echeance = "ÉCHÉANCE PASSÉE : doit activer pour se connecter"
            else:
                echeance = f"jusqu'au {timezone.localtime(limite):%d/%m/%Y} ({(limite - maintenant).days} j)"
            derniere = f"{timezone.localtime(compte.last_login):%d/%m/%Y}" if compte.last_login else "jamais"
            self.stdout.write(
                f"  - {compte.email}  [{compte.type}]  dernière connexion : {derniere}  —  {echeance}")
        if concernes:
            self.stdout.write(
                "\nUn de ces comptes est utilisé par un programme ? "
                "manage.py marquer_compte_machine <email>")
