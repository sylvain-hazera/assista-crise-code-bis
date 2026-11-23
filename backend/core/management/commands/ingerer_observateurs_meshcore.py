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
            '--service', action='store_true',
            help="Mode service (19/11/2026) : attend qu'une source soit déclarée au lieu de "
                 "s'arrêter, et reprend seul les sources ajoutées ou modifiées depuis la page.",
        )
        parseur.add_argument(
            '--duree', type=int, default=0,
            help="Secondes avant de s'arrêter. 0 = sans fin (défaut). Utile pour un essai.",
        )

    @staticmethod
    def _signature(sources):
        """Ce qui, s'il change, impose de rouvrir les connexions."""
        return sorted((str(s.id), s.type_source, s.broker_host, s.broker_port, s.mqtt_username, s.mqtt_password,
                       s.mqtt_use_tls, s.mqtt_transport, s.mqtt_ws_chemin, s.filtre_topic) for s in sources)

    def handle(self, *args, **options):
        import paho.mqtt.client as mqtt

        environment = options['environment']
        debut = time.time()
        while True:
            sources = list(SourceObservateurMeshCore.objects.filter(actif=True, environment=environment))
            if not sources:
                if not options['service']:
                    self.stderr.write(
                        "Aucune source d'observateurs active. Déclarez-en une dans "
                        "/api/sources-observateurs-meshcore/ avant de lancer cette commande."
                    )
                    return
                time.sleep(60)
                continue
            if self._ecouter(mqtt, sources, environment, options, debut) == 'fin':
                return

    def _ecouter(self, mqtt, sources, environment, options, debut):
        """Écoute jusqu'à la fin demandée ('fin') ou un changement des sources ('relire').

        19/11/2026 : les liaisons sont notées dans un tampon par source et écrites toutes les
        30 s, les compteurs de trafic toutes les minutes — un broker national publie une
        dizaine de trames par seconde. Une même observation reçue par deux sources (un broker
        et l'instance CoreScope qu'il alimente) n'est comptée qu'une fois."""
        from core.observations_meshcore import DejaVus, TamponLiaisons

        deja_vus = DejaVus()
        compteurs, tampons, clients = {}, {}, []
        for source in sources:
            compteurs[source.id] = {'recus': 0, 'decodes': 0, 'liaisons': 0, 'illisibles': 0,
                                    'doublons': 0, 'types': {}}
            tampons[source.id] = TamponLiaisons()
            demarrer = self._demarrer_corescope if source.type_source == "CORESCOPE" else self._demarrer
            clients.append(demarrer(mqtt, source, environment, compteurs[source.id], tampons[source.id], deja_vus))

        self.stdout.write(f"{len(clients)} source(s) en écoute. Ctrl-C pour arrêter.")
        signature = self._signature(sources)
        tours = 0
        try:
            while True:
                time.sleep(10)
                tours += 1
                if tours % 3 == 0:
                    for source in sources:
                        try:
                            tampons[source.id].vider()
                        except Exception:
                            logger.exception("[%s] liaisons non écrites.", source.nom)
                if tours % 6 == 0:
                    self._resumer(sources, compteurs, environment)
                if options['duree'] and time.time() - debut >= options['duree']:
                    return 'fin'
                if options['service'] and tours % 6 == 0:
                    actuelles = SourceObservateurMeshCore.objects.filter(actif=True, environment=environment)
                    if self._signature(actuelles) != signature:
                        logger.info("Sources modifiées : connexions rouvertes.")
                        return 'relire'
        except KeyboardInterrupt:
            self.stdout.write("Arrêt demandé.")
            return 'fin'
        finally:
            for client in clients:
                client.loop_stop()
                client.disconnect()
            for source in sources:
                try:
                    tampons[source.id].vider()
                except Exception:
                    logger.exception("[%s] liaisons non écrites à l'arrêt.", source.nom)

    def _traiter(self, source, message, environment, compteur, tampon, deja_vus, verrou):
        """Une observation, d'où qu'elle vienne : décodée, dédoublonnée, notée."""
        if message is not None and message.sorte == 'status':
            # 23/11/2026 : l'état de l'observateur (batterie, bruit de fond…) pour le tableau radio.
            try:
                from core.ingestion_observateurs_meshcore import enregistrer_etat
                enregistrer_etat(message, environment=environment)
            except Exception:
                logger.exception("[%s] état d'observateur non enregistré.", source.nom)
            return
        if message is None or message.sorte not in ('packets', 'raw'):
            return
        if deja_vus.deja_vu(message.observateur, message.donnees.get("raw")):
            with verrou:
                compteur['doublons'] += 1
            return
        avant = tampon.notees
        decode, _liaison = ingerer_paquet(message, environment=environment, tampon=tampon)
        with verrou:
            if decode is None:
                compteur['illisibles'] += 1
            else:
                compteur['decodes'] += 1
                # Nature du trafic par observateur, comme pour nos companions.
                cle = (message.observateur, decode["entete"].get("nom_charge") or "INCONNU")
                compteur['types'][cle] = compteur['types'].get(cle, 0) + 1
            compteur['liaisons'] += tampon.notees - avant

    def _demarrer(self, mqtt, source, environment, compteur, tampon, deja_vus):
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
                self._traiter(source, lire_message(msg.topic, msg.payload), environment, compteur,
                              tampon, deja_vus, verrou)
            except Exception:
                # Une trame hostile ne doit pas arrêter l'ingestion : elle est comptée et on
                # continue.
                logger.exception("[%s] échec de traitement d'un message.", source.nom)
                with verrou:
                    compteur['illisibles'] += 1

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             transport=source.mqtt_transport or "tcp")
        if source.mqtt_transport == "websockets":
            client.ws_set_options(path=source.mqtt_ws_chemin or "/mqtt")
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

    def _demarrer_corescope(self, _mqtt, source, environment, compteur, tampon, deja_vus):
        """Flux temps réel d'une instance CoreScope : le WebSocket que sa propre page web ouvre à
        la racine du site, sans authentification, une observation par message (19/11/2026).
        Reconnexion automatique, comme pour un broker."""
        return ClientCoreScope(self, source, environment, compteur, tampon, deja_vus)

    @staticmethod
    def _etat(source, etat, erreur=None):
        SourceObservateurMeshCore.objects.filter(id=source.id).update(
            dernier_etat=etat, derniere_erreur=erreur,
            **({'derniere_connexion': timezone.now()} if etat == "CONNECTE" else {}),
        )

    def _resumer(self, sources, compteurs, environment=Environment.PROD):
        """Un bilan par minute, **y compris à zéro** : c'est le zéro qui est l'information."""
        from core.views import enregistrer_compteurs_meshcore
        for source in sources:
            c = compteurs[source.id]
            types, c['types'] = c['types'], {}
            par_observateur = {}
            for (observateur, type_paquet), n in types.items():
                par_observateur.setdefault(observateur, {})[type_paquet] = n
            for observateur, comptes in par_observateur.items():
                try:
                    enregistrer_compteurs_meshcore(observateur, comptes, environment, timezone.now())
                except Exception:
                    logger.exception("[%s] compteurs non enregistrés.", source.nom)
            if c['recus'] == 0:
                logger.warning("[%s] aucun message reçu (%s).", source.nom,
                               "flux CoreScope" if source.type_source == "CORESCOPE" else source.filtre_topic)
            else:
                logger.info("[%s] %d messages en une minute : %d trames décodées, %d liaisons notées, "
                            "%d doublons écartés, %d illisibles.", source.nom, c['recus'], c['decodes'],
                            c['liaisons'], c['doublons'], c['illisibles'])
            c.update(recus=0, decodes=0, liaisons=0, illisibles=0, doublons=0)


class ClientCoreScope:
    """Client du flux WebSocket d'une instance CoreScope, dans son propre fil. Même interface
    d'arrêt qu'un client MQTT (`loop_stop`, `disconnect`)."""

    def __init__(self, commande, source, environment, compteur, tampon, deja_vus):
        self.commande, self.source = commande, source
        self.environment, self.compteur, self.tampon, self.deja_vus = environment, compteur, tampon, deja_vus
        self.verrou = threading.Lock()
        self.arret = threading.Event()
        self.fil = threading.Thread(target=self._executer, name=f"corescope-{source.nom}", daemon=True)
        self.fil.start()

    @property
    def url(self):
        hote = self.source.broker_host.strip().removeprefix("https://").removeprefix("wss://").rstrip("/")
        schema = "wss" if self.source.mqtt_use_tls or self.source.broker_port == 443 else "ws"
        port = "" if self.source.broker_port in (443, 80) else f":{self.source.broker_port}"
        return f"{schema}://{hote}{port}{self.source.mqtt_ws_chemin or '/'}"

    def _executer(self):
        import asyncio
        asyncio.run(self._boucle())

    async def _boucle(self):
        import asyncio
        import websockets
        from core.ingestion_observateurs_meshcore import lire_message_corescope

        while not self.arret.is_set():
            try:
                # Agent générique : l'instance n'a pas à savoir qui l'écoute.
                async with websockets.connect(self.url, user_agent_header="curl", max_size=2 ** 22,
                                              open_timeout=30, ping_interval=30) as ws:
                    logger.info("[%s] connecté au flux %s.", self.source.nom, self.url)
                    await asyncio.to_thread(self.commande._etat, self.source, "CONNECTE")
                    while not self.arret.is_set():
                        try:
                            texte = await asyncio.wait_for(ws.recv(), timeout=5)
                        except asyncio.TimeoutError:
                            continue
                        with self.verrou:
                            self.compteur['recus'] += 1
                        try:
                            message = lire_message_corescope(texte)
                            await asyncio.to_thread(self.commande._traiter, self.source, message, self.environment,
                                                    self.compteur, self.tampon, self.deja_vus, self.verrou)
                        except Exception:
                            logger.exception("[%s] échec de traitement d'un message.", self.source.nom)
                            with self.verrou:
                                self.compteur['illisibles'] += 1
            except Exception as erreur:
                if self.arret.is_set():
                    break
                logger.warning("[%s] flux interrompu : %s", self.source.nom, erreur)
                await asyncio.to_thread(self.commande._etat, self.source, "ERREUR", f"{type(erreur).__name__} : {erreur}"[:300])
                await asyncio.sleep(15)

    def loop_stop(self):
        self.arret.set()
        self.fil.join(timeout=10)

    def disconnect(self):
        pass
