"""Rattrapage des comptes rattachés « sur le papier » seulement.

« Dans quelle institution est cet utilisateur » a deux réponses en base : `ContactInstitution`,
la relation faisant autorité, et le raccourci `User.institution`, que lisent les vues
territoriales (`zone_scoping._institution_commune_or_400`). Le chemin « ajouter un contact » de
l'administration — le plus utilisé — créait la ligne sans poser le raccourci (corrigé dans
`ContactInstitutionViewSet._ouvrir_les_droits`). Les comptes rattachés avant cette correction
utilisent donc normalement l'application SAUF les sept vues `*-vue-mairie` / `*-vue-secteur`,
qui leur répondent « Aucune commune associée à votre institution : contactez un
administrateur » — alors que l'administrateur les a bel et bien rattachés, et que son geste n'y
changeait rien.

Mesuré en production le 27/10/2026 : 4 comptes actifs dans cet état, dont un agent qui a
accumulé 75 échecs sur quatre sessions avant de cesser de revenir.

Idempotent : `grant_institution_and_demo_access` ne pose `User.institution` que s'il est vide,
donc relancer la commande ne détourne jamais un profil déjà rattaché ailleurs.
"""
from django.core.management.base import BaseCommand

from core.models import ContactInstitution, User


class Command(BaseCommand):
    help = (
        "Pose User.institution pour les comptes qui ont un ContactInstitution actif sans "
        "raccourci — et, par la même occasion, les ajoute à l'équipe de leur institution et "
        "leur ouvre la zone de démonstration, comme tout autre rattachement. --dry-run "
        "d'abord."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Liste les comptes concernés et l'institution retenue, sans rien modifier.")

    def handle(self, *args, **options):
        from core.institution_attachment import grant_institution_and_demo_access

        a_blanc = options["dry_run"]
        concernes = []
        for user in User.objects.filter(institution__isnull=True):
            contact = self._contact_de_reference(user)
            if contact is not None:
                concernes.append((user, contact))

        if not concernes:
            self.stdout.write("Aucun compte à rattraper : tout ContactInstitution actif a son "
                              "User.institution.")
            return

        self.stdout.write(
            f"{'[dry-run] ' if a_blanc else ''}{len(concernes)} compte(s) à rattacher :")
        for user, contact in concernes:
            etat = "actif" if (user.is_active and user.enabled) else "désactivé"
            self.stdout.write(
                f"  - {user.last_name or user.username} ({user.type}, {etat}) "
                f"→ {contact.institution.nom} [{contact.fonction or 'sans fonction'}]")
            if not a_blanc:
                grant_institution_and_demo_access(user, contact.institution)

        if a_blanc:
            self.stdout.write(self.style.WARNING(
                "Rien n'a été modifié. Relancez sans --dry-run."))
        else:
            self.stdout.write(self.style.SUCCESS(f"{len(concernes)} compte(s) rattaché(s)."))

    def _contact_de_reference(self, user):
        """Parmi ses rattachements actifs, celui qui doit devenir son contexte « Ma
        Collectivité ».

        Une personne peut être contact de plusieurs institutions. L'ordre reprend celui que
        l'application applique déjà ailleurs (`_resolve_institution_or_400` prend le premier
        rattachement actif), en préférant d'abord une institution encore en service, puis le
        rattachement où la personne est contact principal : ces deux critères désignent le
        rattachement « vivant » plutôt qu'un vestige."""
        contacts = list(
            ContactInstitution.objects.filter(utilisateur=user, actif=True)
            .select_related("institution")
        )
        if not contacts:
            return None
        contacts.sort(key=lambda c: (not c.institution.actif, not c.contact_principal))
        return contacts[0]
