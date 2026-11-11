"""Envoie les messages retenus pour relecture et jamais relus.

    python manage.py expedier_brouillons_oublies
    python manage.py expedier_brouillons_oublies --heures 48 --compter

**Pourquoi cette commande existe** : l'action qui a produit le message a DÉJÀ eu lieu. Le compte
est validé, le dossier est clôturé, le rattachement est accepté — seul le message attend. Une
relecture oubliée priverait donc quelqu'un de son information sans que rien ne le signale, et un
compte validé dont le titulaire n'est jamais prévenu est pire qu'un texte non relu.

Les messages partis par ce chemin reçoivent le statut `EXPEDIE_AUTO`, distinct d'`ENVOYE` :
c'est ce qui permet de mesurer si la relecture sert vraiment ou si elle est systématiquement
oubliée — auquel cas c'est la fonctionnalité qu'il faut revoir, pas les gens.

À lancer périodiquement (tâche planifiée horaire). Sans elle, les brouillons s'accumulent et
personne n'est prévenu de rien.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.brouillons_envoi import DELAI_RELECTURE_HEURES, envoyer_brouillon
from core.models import BrouillonEnvoi


class Command(BaseCommand):
    help = "Envoie les brouillons à relire dont le délai est dépassé."

    def add_arguments(self, parseur):
        parseur.add_argument('--heures', type=int, default=DELAI_RELECTURE_HEURES,
                             help=f"Délai au-delà duquel un brouillon part quand même "
                                  f"(défaut : {DELAI_RELECTURE_HEURES} h).")
        parseur.add_argument('--compter', action='store_true',
                             help="Ne rien envoyer : dire ce qui partirait.")

    def handle(self, *args, **options):
        limite = timezone.now() - timezone.timedelta(hours=options['heures'])
        oublies = BrouillonEnvoi.objects.filter(
            statut=BrouillonEnvoi.Statut.A_RELIRE, date_creation__lt=limite,
        ).select_related('institution')

        envoyes = echecs = 0
        for brouillon in oublies:
            if options['compter']:
                self.stdout.write(
                    f"  partirait : « {brouillon.sujet[:60]} » "
                    f"({brouillon.institution.nom}, créé le "
                    f"{brouillon.date_creation:%d/%m %H:%M})"
                )
                envoyes += 1
                continue
            # `request=None` : aucun humain, donc pas de capture en brouillon (le garde de
            # `doit_etre_relu` l'assure) — sinon on recréerait un brouillon à chaque passage.
            ok, motif = envoyer_brouillon(
                None, brouillon,
                statut_final=BrouillonEnvoi.Statut.EXPEDIE_SANS_RELECTURE,
            )
            if ok:
                envoyes += 1
            else:
                echecs += 1
                self.stderr.write(self.style.WARNING(
                    f"  échec sur {brouillon.id} : {motif}"))

        self.stdout.write("")
        self.stdout.write(f"  délai                : {options['heures']} h")
        if options['compter']:
            self.stdout.write(f"  partiraient          : {envoyes}")
            self.stdout.write(self.style.WARNING("  (--compter : rien n'a été envoyé)"))
        else:
            self.stdout.write(f"  envoyés sans relecture : {envoyes}")
            self.stdout.write(f"  échecs                 : {echecs}")
            if envoyes:
                self.stdout.write(
                    "  Ces messages portent le statut « Expédié sans relecture » : si le "
                    "chiffre reste élevé, c'est la relecture qu'il faut revoir."
                )
