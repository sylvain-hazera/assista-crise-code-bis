"""Crée l'arborescence de coordination territoriale d'une association nationale.

    python manage.py creer_arborescence_coordination --institution "Réserve Résilience - Casques Jaunes"
    python manage.py creer_arborescence_coordination --institution "..." --compter

National → zone de défense → régional → départemental, chaque équipe rattachée à la précédente
par `equipe_parente`. Soit, France entière : 1 + 10 zones + 23 régions + 96 départements.

**Idempotente.** Une seconde exécution ne crée pas de doublons : chaque équipe est retrouvée par
(institution, échelon, code de territoire), et seuls son parent et ses libellés sont remis à
jour. C'est ce qui permet de la relancer après un décret, ou pour rattraper une branche.

**Aucun salon Matrix n'est provisionné ici**, et c'est une décision (11/11/2026) : 127 équipes
feraient 254 salons, dont la quasi-totalité vides, tous affichés dans Element. Un salon se crée
quand l'équipe a des membres — voir `TeamViewSet.provisionner_salons_matrix`, idempotent, et le
provisionnement automatique à la première ouverture de la messagerie de l'équipe.

Les équipes départementales renseignent AUSSI `departements` : c'est ce champ, et non
`territoire_code`, que lit le matching d'intervention existant. Les renseigner sépare ce que
l'équipe *représente* de ce sur quoi elle *intervient*, sans que le second cesse de marcher.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import EchelonEquipe, Environment, Institution, Team
from core.zones_defense import (
    ZONES_DEFENSE, ZONES_DEFENSE_OUTRE_MER, verifier_coherence,
)

# Couleurs par échelon : une arborescence se lit d'un coup d'œil quand l'échelon a une couleur,
# et `Team.color` existe déjà pour ça.
COULEURS = {
    EchelonEquipe.NATIONAL: "#1e3a8a",
    EchelonEquipe.ZONE_DEFENSE: "#1d4ed8",
    EchelonEquipe.REGIONAL: "#2563eb",
    EchelonEquipe.DEPARTEMENTAL: "#60a5fa",
}


class Command(BaseCommand):
    help = "Crée l'arborescence Nationale / Zone de défense / Régionale / Départementale."

    def add_arguments(self, parseur):
        parseur.add_argument('--institution', required=True,
                             help="Nom exact de l'institution porteuse.")
        parseur.add_argument('--environment', default=Environment.PROD)
        parseur.add_argument('--sans-outre-mer', action='store_true',
                             help="Métropole seulement (7 zones). À éviter : l'arborescence "
                                  "« nationale » serait alors sans l'outre-mer.")
        parseur.add_argument('--compter', action='store_true',
                             help="Ne rien écrire : dire ce qui serait créé ou mis à jour.")

    def handle(self, *args, **options):
        # La table est recopiée à la main : on la vérifie AVANT d'écrire, sinon on crée une
        # arborescence fausse qui a l'air juste et dont l'erreur ne se verra qu'à l'usage.
        problemes = verifier_coherence()
        if problemes:
            for probleme in problemes:
                self.stderr.write(self.style.ERROR(f"  {probleme}"))
            raise CommandError("Table des zones de défense incohérente : rien n'a été écrit.")

        institution = Institution.objects.filter(nom=options['institution']).first()
        if institution is None:
            proches = Institution.objects.filter(
                nom__icontains=options['institution'].split()[0]
            ).values_list('nom', flat=True)[:5]
            indice = f" Institutions approchantes : {', '.join(proches)}." if proches else ""
            raise CommandError(f"Aucune institution nommée « {options['institution'] } ».{indice}")

        zones = list(ZONES_DEFENSE)
        if not options['sans_outre_mer']:
            zones += ZONES_DEFENSE_OUTRE_MER

        self.bilan = {'crees': 0, 'majs': 0}
        self.options = options
        self.institution = institution

        with transaction.atomic():
            national = self._equipe(
                EchelonEquipe.NATIONAL, "FR", "France",
                "Coordination Nationale", parent=None,
            )
            for code_zone, libelle_zone, siege, regions in zones:
                equipe_zone = self._equipe(
                    EchelonEquipe.ZONE_DEFENSE, code_zone, libelle_zone,
                    f"Coordination Zone de Défense {libelle_zone}", parent=national,
                    description=f"Zone de défense et de sécurité {libelle_zone} — siège : {siege}.",
                )
                for code_region, libelle_region, departements in regions:
                    equipe_region = self._equipe(
                        EchelonEquipe.REGIONAL, code_region, libelle_region,
                        f"Coordination Régionale {libelle_region}", parent=equipe_zone,
                        # Une région sans départements dans la table est un DROM : son
                        # territoire est à la fois région et département, et l'arborescence
                        # s'arrête là plutôt que d'empiler deux équipes pour un seul territoire.
                        departements=[d for d, _l in departements] or None,
                    )
                    for code_dept, libelle_dept in departements:
                        self._equipe(
                            EchelonEquipe.DEPARTEMENTAL, code_dept, libelle_dept,
                            f"Coordination Départementale {libelle_dept} ({code_dept})",
                            parent=equipe_region, departements=[code_dept],
                        )

        self.stdout.write("")
        self.stdout.write(f"  institution          : {institution.nom}")
        self.stdout.write(f"  équipes créées       : {self.bilan['crees']}")
        self.stdout.write(f"  équipes mises à jour : {self.bilan['majs']}")
        if options['compter']:
            self.stdout.write(self.style.WARNING("  (--compter : rien n'a été écrit)"))
        else:
            self.stdout.write(
                "  Aucun salon Matrix n'a été provisionné : un salon se crée quand l'équipe a "
                "des membres (voir la docstring de la commande)."
            )

    def _equipe(self, echelon, code, libelle, nom, parent, description=None,
                departements=None):
        """Retrouvée par (institution, échelon, territoire) — JAMAIS par son nom.

        Le nom est un libellé d'affichage : s'en servir de clé ferait un doublon au premier
        renommage, et « Coordination Régionale Normandie » n'a aucune raison d'être stable."""
        equipe = Team.objects.filter(
            institution=self.institution, echelon=echelon, territoire_code=code,
        ).first()

        valeurs = {
            'name': nom,
            'territoire_libelle': libelle,
            'equipe_parente': parent,
            'color': COULEURS.get(echelon, '#3b82f6'),
        }
        if description:
            valeurs['description'] = description
        if departements is not None:
            valeurs['departements'] = departements

        if equipe is None:
            self.bilan['crees'] += 1
            if self.options['compter']:
                # On ne rend AUCUN objet non sauvegardé : l'affecter en `equipe_parente` d'une
                # équipe déjà existante ferait lever Django (« save() prohibited to prevent data
                # loss due to unsaved related object »). En comptage, les enfants d'une équipe à
                # créer n'ont simplement pas de parent — rien n'étant écrit, cela ne change rien
                # au décompte.
                return None
            return Team.objects.create(
                institution=self.institution, echelon=echelon, territoire_code=code,
                environment=self.options['environment'], **valeurs,
            )

        self.bilan['majs'] += 1
        if self.options['compter']:
            return equipe
        for champ, valeur in valeurs.items():
            setattr(equipe, champ, valeur)
        equipe.save(update_fields=list(valeurs))
        return equipe
