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
import time

import requests
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import Environment, NoeudPublicMeshCore

# Rôles importés. `companion` et `sensor` en sont absents EXPRÈS.
ROLES = ("repeater", "room")

TAILLE_PAGE = 200
PAUSE_ENTRE_PAGES_S = 0.3

# Un opérateur qui ne veut pas être affiché renomme son nœud avec l'un de ces préfixes. Les
# instances CoreScope les retirent déjà de leurs réponses ; on le refait, parce qu'une instance
# mal configurée ne doit pas nous faire republier ce que quelqu'un a demandé à cacher.
PREFIXES_MASQUES = ("🚫",)


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
        instance = options['instance'].rstrip('/')
        maintenant = timezone.now()
        bilan = {'lus': 0, 'sans_position': 0, 'masques': 0, 'crees': 0, 'majs': 0}
        hashs = {}

        with requests.Session() as client:
            # Agent générique : on n'envoie aucune information sur qui interroge.
            client.headers.update({'User-Agent': 'curl'})
            for role in ROLES:
                for noeud in self._pages(client, instance, role, options['region']):
                    bilan['lus'] += 1
                    self._traiter(noeud, instance, options, maintenant, bilan, hashs)

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
            detail = ", ".join(f"{n} octet(s) : {c} ({100 * c // total} %)"
                               for n, c in sorted(hashs.items()))
            self.stdout.write(f"  taille de hash       : {detail}")
            self.stdout.write(
                "  Un préfixe d'un octet n'a que 256 valeurs : les sauts de ces nœuds ne "
                "peuvent pas servir de preuve de topologie."
            )

    def _pages(self, client, instance, role, region):
        """Parcourt /api/nodes page par page. `has_more` fait foi, pas `total` — l'instance
        renvoie la taille de la PAGE dans `total`, pas le total filtré."""
        offset = 0
        while True:
            params = {'role': role, 'limit': TAILLE_PAGE, 'offset': offset}
            if region:
                params['region'] = region
            try:
                reponse = client.get(f"{instance}/api/nodes", params=params, timeout=30)
                reponse.raise_for_status()
                charge = reponse.json()
            except (requests.RequestException, ValueError) as erreur:
                raise CommandError(f"Échec de lecture de {instance} : {erreur}") from erreur

            noeuds = charge.get('nodes') or []
            for noeud in noeuds:
                yield noeud
            if not charge.get('has_more') or not noeuds:
                return
            offset += len(noeuds)
            time.sleep(PAUSE_ENTRE_PAGES_S)

    def _traiter(self, noeud, instance, options, maintenant, bilan, hashs):
        cle = (noeud.get('public_key') or '').strip().lower()
        if len(cle) != 64:
            return
        nom = (noeud.get('name') or '').strip()
        if any(nom.startswith(p) for p in PREFIXES_MASQUES):
            bilan['masques'] += 1
            return

        lat, lon = noeud.get('lat'), noeud.get('lon')
        if lat is None or lon is None:
            # Sans position, le nœud n'apporte rien à une cartographie — et l'importer gonflerait
            # la table de lignes qu'aucune carte ne montrera.
            bilan['sans_position'] += 1
            return

        taille = noeud.get('hash_size')
        if isinstance(taille, int) and taille > 0:
            hashs[taille] = hashs.get(taille, 0) + 1

        if options['compter']:
            return

        _, cree = NoeudPublicMeshCore.objects.update_or_create(
            instance=instance, pubkey_hex=cle, environment=options['environment'],
            defaults={
                'nom': nom[:100],
                'role': (noeud.get('role') or '')[:20],
                'location': Point(float(lon), float(lat), srid=4326),
                'premier_vu': parse_datetime(noeud.get('first_seen') or '') or None,
                'dernier_vu': parse_datetime(noeud.get('last_seen') or '') or None,
                'relais_actif': bool(noeud.get('relay_active')),
                'relais_24h': int(noeud.get('relay_count_24h') or 0),
                'score_couverture': noeud.get('coverage_score'),
                'score_redondance': noeud.get('redundancy_score'),
                'score_pont': noeud.get('bridge_score'),
                'score_utilite': noeud.get('usefulness_score'),
                'note_utilite': (noeud.get('usefulness_grade') or '')[:4],
                'taille_hash': taille if isinstance(taille, int) else None,
                'date_import': maintenant,
            },
        )
        bilan['crees' if cree else 'majs'] += 1
