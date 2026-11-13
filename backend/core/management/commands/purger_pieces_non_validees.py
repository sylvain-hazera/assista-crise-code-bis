"""Détruit les justificatifs restés sans décision au-delà du délai, et prévient avant.

Demande de Sylvain du 13/11/2026 : « une destruction à 30 jours s'il n'est pas validé ».

**Mode simulation par défaut.** Une purge ne se lance pas à l'aveugle : sans `--appliquer`, la
commande liste ce qu'elle détruirait et sort. C'est la même convention que
`normaliser_telephones`, et elle a déjà servi.

À planifier une fois par nuit. Deux choses se font dans le même passage, et dans cet ordre :
le rappel à sept jours de l'échéance, puis la destruction de ce qui a dépassé trente jours.
Prévenir après avoir détruit n'aurait évidemment aucun sens.
"""
from django.core.management.base import BaseCommand

from core.conservation_pieces import JOURS_AVANT_PURGE_NON_VALIDEE, JOURS_AVANT_RAPPEL_PURGE
from core.pieces_conformite import purger, rappeler


class Command(BaseCommand):
    help = ("Détruit les justificatifs déposés il y a plus de "
            f"{JOURS_AVANT_PURGE_NON_VALIDEE} jours que personne n'a instruits.")

    def add_arguments(self, parseur):
        parseur.add_argument(
            "--appliquer", action="store_true",
            help="Détruit réellement. Sans ce drapeau, la commande se contente de lister.",
        )
        parseur.add_argument(
            "--sans-rappel", action="store_true",
            help="N'envoie pas les rappels à "
                 f"{JOURS_AVANT_RAPPEL_PURGE} jours de l'échéance.",
        )

    def handle(self, *args, **options):
        appliquer = options["appliquer"]

        if not options["sans_rappel"]:
            rappels = rappeler(appliquer=appliquer)
            for ligne in rappels:
                self.stdout.write(
                    f"rappel  {ligne.utilisateur} — {ligne.qualification} "
                    f"(déposé le {ligne.justificatif_depose_le:%d/%m/%Y})"
                )
            self.stdout.write(self.style.NOTICE(
                f"{len(rappels)} rappel(s) à {JOURS_AVANT_RAPPEL_PURGE} jours de l'échéance."
            ))

        purgees = purger(appliquer=appliquer)
        for ligne in purgees:
            self.stdout.write(
                f"purge   {ligne.utilisateur} — {ligne.qualification} "
                f"(déposé le {ligne.justificatif_depose_le:%d/%m/%Y})"
            )

        if appliquer:
            self.stdout.write(self.style.SUCCESS(
                f"{len(purgees)} justificatif(s) détruit(s). Les titres et leurs dates sont "
                f"conservés : seuls les fichiers ont disparu."
            ))
        else:
            self.stdout.write(self.style.WARNING(
                f"Simulation : {len(purgees)} justificatif(s) seraient détruits. "
                f"Relancer avec --appliquer."
            ))
