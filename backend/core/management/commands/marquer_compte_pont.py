"""Marque (ou démarque) un compte de service de pont radio.

Volontairement hors API : un compte qui peut lire tous les secrets radio de l'institution ne
doit pas pouvoir être fabriqué par une requête HTTP (voir core/permissions.py:EstComptePont).

    manage.py marquer_compte_pont pont-meshtastic@exemple.fr
    manage.py marquer_compte_pont pont-meshtastic@exemple.fr --retirer
    manage.py marquer_compte_pont --lister
"""
from django.core.management.base import BaseCommand, CommandError

from core.crypto_fields import blind_index
from core.models import Satellite, StatutEnrolementSatellite, User


class Command(BaseCommand):
    help = "Autorise un compte de service de pont à lire les secrets mesh (mot de passe MQTT, clés)."

    def add_arguments(self, parser):
        parser.add_argument('email', nargs='?', help="Adresse du compte de service du pont.")
        parser.add_argument('--retirer', action='store_true', help="Retire l'autorisation.")
        parser.add_argument('--lister', action='store_true', help="Liste les comptes autorisés.")

    def handle(self, *args, **options):
        if options['lister']:
            return self._lister()

        email = (options['email'] or '').strip()
        if not email:
            raise CommandError("Donner une adresse, ou --lister.")

        # L'email est chiffré au repos : la recherche passe par son index aveugle, pas par un
        # `filter(email=...)` qui ne trouverait jamais rien (Fernet n'est pas déterministe).
        compte = User.objects.filter(email_bidx=blind_index(email)).first()
        if compte is None:
            raise CommandError(
                f"Aucun compte pour {email}. `--lister` montre les comptes déjà autorisés."
            )

        autoriser = not options['retirer']
        if compte.compte_service_pont == autoriser:
            self.stdout.write(
                f"{email} : déjà {'autorisé' if autoriser else 'non autorisé'}, rien à faire."
            )
            return

        compte.compte_service_pont = autoriser
        compte.save(update_fields=['compte_service_pont'])
        self.stdout.write(self.style.SUCCESS(
            f"{email} : {'autorisé à lire les secrets mesh' if autoriser else 'autorisation retirée'}."
        ))

    def _lister(self):
        comptes = User.objects.filter(compte_service_pont=True)
        if comptes:
            self.stdout.write("Comptes de service de pont autorisés :")
            for compte in comptes:
                self.stdout.write(f"  - {compte.email} (type {compte.type})")
        else:
            self.stdout.write(self.style.WARNING(
                "Aucun compte de service de pont autorisé. Les ponts ne pourront pas lire les "
                "secrets mesh (mot de passe MQTT, clés de canal) et le relais radio s'arrêtera."
            ))

        # Les satellites approuvés sont autorisés par leur compte de service, sans marquage :
        # les lister évite de croire qu'il faut les marquer eux aussi.
        satellites = Satellite.objects.filter(
            statut_enrolement=StatutEnrolementSatellite.APPROUVE, compte_service__isnull=False,
        ).select_related('compte_service')
        if satellites:
            self.stdout.write("\nAutorisés d'office par leur enrôlement (aucun marquage requis) :")
            for satellite in satellites:
                self.stdout.write(f"  - satellite « {satellite.nom} » : {satellite.compte_service.email}")
