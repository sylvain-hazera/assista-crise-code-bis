"""Abonnement aux brokers d'observateurs MeshCore, et ingestion de ce qu'ils publient.

    python manage.py ingerer_observateurs_meshcore

Processus LONG : il garde une connexion MQTT par source déclarée
(`SourceObservateurMeshCore`) et écrit en base au fil de l'eau. À lancer comme un service, ou
à la main pour un essai.

**Pourquoi une commande Django et pas une boucle du pont MeshCore** : l'ingestion n'a aucun
rapport avec notre companion — elle consomme un broker tiers et écrit des liaisons. La faire
passer par le pont imposerait un aller-retour HTTP par paquet vers l'API, soit des centaines
par minute sur un broker régional, pour le seul plaisir de la loger ailleurs. Ici, le décodage
et l'écriture sont dans le même processus que les modèles.

**Un seul exemplaire à la fois.** Deux processus abonnés au même broker compteraient chaque
observation deux fois. Les liaisons étant agrégées (`get_or_create` + `nombre`), le dégât se
limite à un compteur gonflé — mais le compteur sert à juger de la régularité d'une liaison,
donc ce n'est pas anodin.
"""
import logging
import threading
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.ingestion_observateurs_meshcore import ingerer_paquet, lire_message
from core.models import Environment, SourceObservateurMeshCore

logger = logging.getLogger("core.observateurs")

# Au-delà, on considère la connexion perdue et paho retente seul.
KEEPALIVE_S = 60


class Command(BaseCommand):
    help = "Abonne aux brokers d'observateurs MeshCore et ingère les trames publiées."

    def add_arguments(self, parseur):
        parseur.add_argument(
            '--environment', default=Environment.PROD,
            help="Zone dans laquelle écrire les observations (PROD par défaut).",
        )
        parseur.add_argument(
            '--duree', type=int, default=0,
            help="Secondes avant de s'arrêter. 0 = sans fin (défaut). Utile pour un essai.",
        )

    def handle(self, *args, **options):
        import paho.mqtt.client as mqtt

        environment = options['environment']
        sources = list(SourceObservateurMeshCore.objects.filter(
            actif=True, environment=environment,
        ))
        if not sources:
            self.stderr.write(
                "Aucune source d'observateurs active. Déclarez-en une dans "
                "/api/sources-observateurs-meshcore/ avant de lancer cette commande."
            )
            return

        compteurs = {}
        clients = []

        for source in sources:
            compteurs[source.id] = {'recus': 0, 'decodes': 0, 'liaisons': 0, 'illisibles': 0}
            clients.append(self._demarrer(mqtt, source, environment, compteurs[source.id]))

        self.stdout.write(f"{len(clients)} source(s) en écoute. Ctrl-C pour arrêter.")
        debut = time.time()
        try:
            while True:
                time.sleep(10)
                self._resumer(sources, compteurs)
                if options['duree'] and time.time() - debut >= options['duree']:
                    break
        except KeyboardInterrupt:
            self.stdout.write("Arrêt demandé.")
        finally:
            for client in clients:
                client.loop_stop()
                client.disconnect()

    def _demarrer(self, mqtt, source, environment, compteur):
        verrou = threading.Lock()

        def on_connect(client, userdata, flags, reason_code, properties=None):
            if reason_code == 0:
                logger.info("[%s] connecté à %s:%s — abonnement à %s.",
                            source.nom, source.broker_host, source.broker_port,
                            source.filtre_topic)
                client.subscribe(source.filtre_topic)
                self._etat(source, "CONNECTE")
            else:
                logger.error("[%s] connexion refusée : %s", source.nom, reason_code)
                self._etat(source, "ERREUR", f"Connexion refusée : {reason_code}")

        def on_subscribe(client, userdata, mid, reason_code_list, properties=None):
            refuses = [c for c in (reason_code_list or []) if getattr(c, "is_failure", False)]
            if refuses:
                # Même angle mort que côté Meshtastic : un abonnement refusé est silencieux si
                # on ne lit pas le SUBACK, et la source reste affichée « connectée ».
                raison = ", ".join(str(c) for c in refuses)
                logger.error("[%s] abonnement REFUSÉ sur %s : %s",
                             source.nom, source.filtre_topic, raison)
                self._etat(source, "ERREUR", f"Abonnement refusé : {raison}")

        def on_disconnect(client, userdata, flags, reason_code, properties=None):
            logger.warning("[%s] déconnecté : %s", source.nom, reason_code)
            self._etat(source, "DECONNECTE")

        def on_message(client, userdata, msg):
            with verrou:
                compteur['recus'] += 1
            try:
                message = lire_message(msg.topic, msg.payload)
                if message is None or message.sorte not in ('packets', 'raw'):
                    return
                decode, liaison = ingerer_paquet(message, environment=environment)
                with verrou:
                    if decode is None:
                        compteur['illisibles'] += 1
                    else:
                        compteur['decodes'] += 1
                    if liaison is not None:
                        compteur['liaisons'] += 1
            except Exception:
                # Une trame hostile ne doit pas arrêter l'ingestion : elle est comptée et on
                # continue.
                logger.exception("[%s] échec de traitement d'un message.", source.nom)
                with verrou:
                    compteur['illisibles'] += 1

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        if source.mqtt_username:
            client.username_pw_set(source.mqtt_username, source.mqtt_password or None)
        if source.mqtt_use_tls:
            client.tls_set()
        client.connect_async(source.broker_host, source.broker_port, keepalive=KEEPALIVE_S)
        client.loop_start()
        return client

    @staticmethod
    def _etat(source, etat, erreur=None):
        SourceObservateurMeshCore.objects.filter(id=source.id).update(
            dernier_etat=etat, derniere_erreur=erreur,
            **({'derniere_connexion': timezone.now()} if etat == "CONNECTE" else {}),
        )

    def _resumer(self, sources, compteurs):
        """Un bilan par fenêtre, **y compris à zéro** : c'est le zéro qui est l'information."""
        for source in sources:
            c = compteurs[source.id]
            if c['recus'] == 0:
                logger.warning("[%s] aucun message reçu sur %s.", source.nom, source.filtre_topic)
            else:
                logger.info("[%s] %d messages : %d trames décodées, %d liaisons, %d illisibles.",
                            source.nom, c['recus'], c['decodes'], c['liaisons'], c['illisibles'])
            c.update(recus=0, decodes=0, liaisons=0, illisibles=0)
