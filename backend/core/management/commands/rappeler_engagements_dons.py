from django.core.management.base import BaseCommand
from django.utils import timezone

from core import appels_dons, notifications_dons
from core.models import EngagementDon, StatutEngagementDon


class Command(BaseCommand):
    help = (
        "Appels aux dons (core/appels_dons.py) : rappelle aux institutions les engagements qui seront "
        "rendus aux autres dans deux jours faute d'envoi annoncé, puis relâche ceux dont le délai est "
        "passé et les en prévient. À planifier (toutes les heures suffit)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Dit ce qui serait fait, sans rien envoyer ni relâcher.")

    def handle(self, *args, **options):
        maintenant = timezone.now()
        rappels = list(appels_dons.a_rappeler(maintenant))
        retards = list(EngagementDon.objects.filter(statut=StatutEngagementDon.PROMIS, expire_le__lt=maintenant).select_related(
            "besoin__appel__institution", "institution", "cree_par"))
        if options["dry_run"]:
            self.stdout.write(f"{len(rappels)} rappel(s) à envoyer, {len(retards)} engagement(s) à relâcher.")
            return
        for engagement in rappels:
            appel = engagement.besoin.appel
            notifications_dons.prevenir(
                de=appel.institution, vers=engagement.institution, personnes=[engagement.cree_par], crise=appel.crise,
                environment=appel.environment, titre=f"Votre engagement pour « {appel.titre} » attend son envoi",
                corps=f"Vous vous êtes engagés à fournir {engagement.quantite} pièce(s) : {appels_dons.libelle(engagement.besoin)}.\n"
                      f"Sans envoi annoncé d'ici le {timezone.localtime(engagement.expire_le):%d/%m/%Y à %H:%M}, cette part sera rendue aux "
                      "autres institutions. Annoncez votre envoi, ou renoncez si la collecte n'aboutit pas.")
            engagement.rappel_envoye_le = maintenant
            engagement.save(update_fields=["rappel_envoye_le"])
        for engagement in retards:
            appel = engagement.besoin.appel
            engagement.statut = StatutEngagementDon.RELACHE
            engagement.save(update_fields=["statut"])
            notifications_dons.prevenir(
                de=appel.institution, vers=engagement.institution, personnes=[engagement.cree_par], crise=appel.crise,
                environment=appel.environment, titre=f"Votre engagement pour « {appel.titre} » a été rendu aux autres",
                corps=f"Aucun envoi n'a été annoncé dans le délai pour {engagement.quantite} pièce(s) : {appels_dons.libelle(engagement.besoin)}.\n"
                      "Cette part est de nouveau à couvrir. Si votre collecte est prête, engagez-vous à nouveau puis annoncez l'envoi.")
        self.stdout.write(f"{len(rappels)} rappel(s) envoyé(s), {len(retards)} engagement(s) relâché(s).")
