"""Importe la cartographie du réseau MeshCore public depuis une instance CoreScope.

    python manage.py importer_cartographie_meshcore --instance https://exemple.invalide
    python manage.py importer_cartographie_meshcore --compter        # ne rien écrire

**Répéteurs et rooms seulement.** Les companions sont volontairement exclus : l'appareil
personnel de quelqu'un, dont la position est souvent son domicile. Voir la docstring de
`NoeudPublicMeshCore` pour le raisonnement complet.

L'import est **idempotent** : une seconde exécution met à jour les lignes existantes, elle n'en
crée pas de doubles. Un nœud que l'instance ne sert plus n'est pas supprimé — il garde sa
dernière date vue, et c'est à l'exploitant de notre côté de décider s'il le purge.

Débit : l'API pagine par `limit`/`offset`. On s'en tient à des pages de 200 et on marque une
pause entre deux : c'est le service de quelqu'un d'autre, et rien ici n'est urgent.
"""
from django.core.management.base import BaseCommand, CommandError

from core.cartographie_meshcore import ImportImpossible, importer
from core.models import Environment


class Command(BaseCommand):
    help = "Importe les répéteurs et rooms MeshCore depuis une instance CoreScope."

    def add_arguments(self, parseur):
        parseur.add_argument('--instance', required=True,
                             help="URL de l'instance, ex. https://meshstats.exemple.fr")
        parseur.add_argument('--environment', default=Environment.PROD)
        parseur.add_argument('--region', default=None,
                             help="Codes IATA séparés par des virgules, pour n'importer qu'une région.")
        parseur.add_argument('--compter', action='store_true',
                             help="Ne rien écrire : dire seulement ce qu'un import contiendrait.")

    def handle(self, *args, **options):
        # La logique vit dans core/cartographie_meshcore.py depuis le 23/11/2026 : la veille du
        # territoire la relève chaque heure ; cette commande reste pour un import à la main.
        try:
            bilan = importer(options['instance'], options['environment'], options['region'], options['compter'])
        except ImportImpossible as erreur:
            raise CommandError(str(erreur)) from erreur
        hashs = bilan.pop("hashs")
        self.stdout.write("")
        self.stdout.write(f"  nœuds lus            : {bilan['lus']}")
        self.stdout.write(f"  sans position        : {bilan['sans_position']} (non importés)")
        self.stdout.write(f"  masqués par leur nom : {bilan['masques']} (non importés)")
        if options['compter']:
            self.stdout.write(self.style.WARNING("  (--compter : rien n'a été écrit)"))
        else:
            self.stdout.write(f"  créés                : {bilan['crees']}")
            self.stdout.write(f"  mis à jour           : {bilan['majs']}")
        if hashs:
            total = sum(hashs.values())
            detail = ", ".join(f"{n} octet(s) : {c} ({100 * c // total} %)" for n, c in sorted(hashs.items()))
            self.stdout.write(f"  taille de hash       : {detail}")
            self.stdout.write(
                "  Un préfixe d'un octet n'a que 256 valeurs : les sauts de ces nœuds ne "
                "peuvent pas servir de preuve de topologie."
            )
