"""Marque (ou démarque) un compte utilisé par un programme et non par une personne.

Un compte marqué n'est jamais tenu d'avoir un second facteur : une machine n'a pas de
téléphone. Le marquage n'ouvre aucun droit. Les ponts radio (`marquer_compte_pont`) et les
comptes de service des satellites sont déjà reconnus comme des machines ; cette commande sert
aux autres — le pont Matrix, un script d'export…

Volontairement hors API : dispenser un compte de second facteur ne doit pas pouvoir se faire
par une requête HTTP.

    manage.py marquer_compte_machine pont-matrix@exemple.fr
    manage.py marquer_compte_machine pont-matrix@exemple.fr --retirer
    manage.py marquer_compte_machine --lister
"""
from django.core.management.base import BaseCommand, CommandError

from core import second_facteur
from core.crypto_fields import blind_index
from core.models import User


class Command(BaseCommand):
    help = "Dispense de second facteur un compte utilisé par un programme."

    def add_arguments(self, parser):
        parser.add_argument('email', nargs='?', help="Adresse du compte.")
        parser.add_argument('--retirer', action='store_true', help="Retire le marquage.")
        parser.add_argument('--lister', action='store_true', help="Liste les comptes marqués.")

    def handle(self, *args, **options):
        if options['lister']:
            comptes = User.objects.filter(compte_machine=True)
            if not comptes:
                self.stdout.write("Aucun compte marqué « machine ».")
            for compte in comptes:
                self.stdout.write(f"  - {compte.email} (type {compte.type})")
            return

        email = (options['email'] or '').strip()
        if not email:
            raise CommandError("Donner une adresse, ou --lister.")
        # L'email est chiffré au repos : la recherche passe par son index aveugle.
        compte = User.objects.filter(email_bidx=blind_index(email)).first()
        if compte is None:
            raise CommandError(f"Aucun compte pour {email}.")

        marquer = not options['retirer']
        if marquer and second_facteur.second_facteur_actif(compte) is not None:
            raise CommandError(
                f"{email} a un second facteur actif : c'est donc une personne. Rien n'a été changé.")
        compte.compte_machine = marquer
        compte.save(update_fields=['compte_machine'])
        if marquer:
            # L'échéance éventuellement déjà posée n'a plus lieu d'être.
            User.objects.filter(pk=compte.pk).update(second_facteur_exige_le=None)
        self.stdout.write(self.style.SUCCESS(
            f"{email} : {'marqué « machine », dispensé de second facteur' if marquer else 'marquage retiré'}."))
