"""Retire le second facteur d'un compte, depuis le serveur.

    manage.py reinitialiser_second_facteur <email>

Le dernier recours : pour l'administrateur qui a perdu son téléphone ET ses codes de secours,
et qu'aucun autre administrateur ne peut dépanner depuis le site. Demande un accès au serveur,
ce qui est la garantie voulue. À sa prochaine connexion, le titulaire devra activer un nouveau
second facteur avant d'entrer.
"""
from django.core.management.base import BaseCommand, CommandError

from core import second_facteur
from core.connexion import trouver_utilisateur


class Command(BaseCommand):
    help = "Retire le second facteur de connexion d'un compte (téléphone perdu)."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, email, **options):
        utilisateur = trouver_utilisateur(email)
        if utilisateur is None:
            raise CommandError("Aucun compte actif avec cette adresse.")
        if not second_facteur.retirer(utilisateur, exiger_tout_de_suite=True):
            raise CommandError("Ce compte n'a pas de second facteur.")
        self.stdout.write(self.style.SUCCESS(
            "Second facteur retiré. À sa prochaine connexion, le titulaire devra en activer un nouveau."))
