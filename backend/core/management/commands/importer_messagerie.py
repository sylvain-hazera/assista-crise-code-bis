"""Importe dans la messagerie interne l'historique des salons Matrix et des anciens canaux radio
d'équipe (23/11/2026, décision « on arrête Matrix »). Idempotent : chaque message importé porte
son origine (`matrix:<event>`, `meshtastic:<id>`, `meshcore:<id>`) et n'est jamais importé deux
fois. À lancer une fois au déploiement, puis à nouveau juste avant l'arrêt de Synapse.

    python manage.py importer_messagerie [--sans-matrix] [--limite 1000]
"""
import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Importe l'historique Matrix et des canaux radio d'équipe dans la messagerie interne."

    def add_arguments(self, parser):
        parser.add_argument("--sans-matrix", action="store_true", help="Ne lit pas Synapse.")
        parser.add_argument("--limite", type=int, default=1000, help="Messages lus par salon Matrix.")

    def handle(self, *args, **options):
        from core import conversations as conv
        from core.models import (
            CanalMeshCore, CanalMeshtastic, Conversation, GenreConversation, SalonMatrixEquipe, SalonMatrixInstitution,
            SalonMatrixMission, SourceMessage, TypeSalonEquipe, User,
        )

        bilan = {"matrix": 0, "radio": 0, "salons_en_erreur": 0}

        if not options["sans_matrix"]:
            from core.matrix import lister_messages_salon

            def importer_salon(room_id, conversation):
                try:
                    messages = lister_messages_salon(room_id, limite=options["limite"])
                except Exception as e:  # salon disparu, Synapse arrêté…
                    bilan["salons_en_erreur"] += 1
                    self.stderr.write(f"Salon {room_id} non lu : {e.__class__.__name__}")
                    return
                for m in messages:
                    auteur = User.objects.filter(pk=m["expediteur_id"]).first() if m.get("expediteur_id") else None
                    emis = datetime.datetime.fromtimestamp((m.get("horodatage") or 0) / 1000, tz=datetime.timezone.utc)
                    _, cree = conv.ecrire(conversation, m.get("texte") or "", auteur=auteur,
                                          auteur_libre=None if auteur else "Compte externe",
                                          source=SourceMessage.MATRIX, urgent=bool(m.get("urgent")), emis_le=emis,
                                          origine=f"matrix:{m['event_id']}", dedupliquer=False)
                    bilan["matrix"] += int(cree)

            for salon in SalonMatrixEquipe.objects.exclude(room_id__isnull=True).exclude(room_id="").select_related("equipe"):
                genre = GenreConversation.ENCADREMENT if salon.type == TypeSalonEquipe.ENCADREMENT else GenreConversation.EQUIPE
                importer_salon(salon.room_id, conv.conversation_equipe(salon.equipe, salon.crise, genre, salon.environment))
            for salon in SalonMatrixMission.objects.exclude(room_id__isnull=True).exclude(room_id="").select_related("mission"):
                c = conv._obtenir(salon.environment, genre=GenreConversation.MISSION, mission=salon.mission)
                importer_salon(salon.room_id, c)
            for salon in SalonMatrixInstitution.objects.exclude(room_id__isnull=True).exclude(room_id="").select_related("institution"):
                # `canal_nom` porte ici le type du salon d'institution (PERMANENTS…), pour les distinguer.
                c = conv._obtenir(salon.environment, genre=GenreConversation.INSTITUTION,
                                  institution=salon.institution, canal_nom=salon.type)
                importer_salon(salon.room_id, c)

        for modele_canal, source, prefixe, lien in ((CanalMeshtastic, SourceMessage.MESHTASTIC, "meshtastic", "message_meshtastic"),
                                                     (CanalMeshCore, SourceMessage.MESHCORE, "meshcore", "message_meshcore")):
            for canal in modele_canal.objects.filter(equipe__isnull=False).select_related("equipe"):
                conversation = conv.conversation_du_contexte(canal.equipe, environment=canal.environment)
                from core.views import _sans_echos
                for m in _sans_echos(list(canal.messages.select_related("expediteur").order_by("date_creation"))):
                    _, cree = conv.ecrire(conversation, m.contenu or "", auteur=m.expediteur,
                                          auteur_libre=None if m.expediteur_id else "Par radio",
                                          source=source if m.direction == "ENTRANT" else SourceMessage.SITE,
                                          emis_le=m.date_creation or timezone.now(), origine=f"{prefixe}:{m.id}",
                                          dedupliquer=False, **{lien: m})
                    bilan["radio"] += int(cree)

        self.stdout.write(f"Importés : {bilan['matrix']} message(s) Matrix, {bilan['radio']} message(s) radio d'équipe ; "
                          f"{bilan['salons_en_erreur']} salon(s) non lu(s). Conversations : {Conversation.objects.count()}.")
