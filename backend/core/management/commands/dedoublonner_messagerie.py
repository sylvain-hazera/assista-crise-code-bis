"""Retire de la messagerie les doublons laissés par l'import de l'historique radio (23/11/2026).

Un message écrit sur le site partait sur les DEUX réseaux (MeshCore et Meshtastic) ; l'import
l'a donc repris deux fois, une par protocole (`origine` « meshcore:… » et « meshtastic:… »),
même texte, même auteur, à la même seconde. On garde une copie, on y reporte les « reçu par »
de l'autre, et l'on retire l'autre.

Par défaut, la commande ne fait que LISTER. `--appliquer` supprime (irréversible : sauvegarde
de la base avant)."""
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

ECART = datetime.timedelta(seconds=5)


def doublons_d_import():
    """[(gardé, retiré)] : les paires importées une fois par protocole."""
    from core.models import MessageConversation

    meshcore = list(MessageConversation.objects.filter(origine__startswith="meshcore:").order_by("emis_le"))
    paires, pris = [], set()
    for copie in MessageConversation.objects.filter(origine__startswith="meshtastic:").order_by("emis_le"):
        for garde in meshcore:
            if (garde.pk not in pris and garde.conversation_id == copie.conversation_id
                    and garde.empreinte == copie.empreinte and abs(garde.emis_le - copie.emis_le) <= ECART):
                paires.append((garde, copie))
                pris.add(garde.pk)
                break
    return paires


class Command(BaseCommand):
    help = "Liste (ou retire avec --appliquer) les doublons de l'import de l'historique radio."

    def add_arguments(self, parser):
        parser.add_argument("--appliquer", action="store_true", help="Supprimer les doublons (irréversible).")

    def handle(self, *args, **options):
        paires = doublons_d_import()
        for garde, copie in paires:
            self.stdout.write(f"{copie.emis_le:%d/%m/%Y %H:%M:%S} conversation {copie.conversation_id} : "
                              f"{copie.origine} doublon de {garde.origine}")
        if not options["appliquer"]:
            self.stdout.write(f"{len(paires)} doublon(s). Rien n'est supprimé sans --appliquer.")
            return
        with transaction.atomic():
            for garde, copie in paires:
                manquants = [r for r in (copie.recu_par or []) if r not in (garde.recu_par or [])]
                champs = []
                if manquants:
                    garde.recu_par = list(garde.recu_par or []) + manquants
                    champs.append("recu_par")
                if garde.message_meshtastic_id is None and copie.message_meshtastic_id:
                    garde.message_meshtastic_id = copie.message_meshtastic_id
                    champs.append("message_meshtastic")
                if champs:
                    garde.save(update_fields=champs)
                copie.delete()
        self.stdout.write(f"{len(paires)} doublon(s) retiré(s).")
