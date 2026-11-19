"""Impacts de foudre du réseau communautaire Blitzortung, par le relais MQTT qu'utilise
l'intégration Home Assistant « blitzortung » (19/11/2026, décision de Sylvain).

    python manage.py ecouter_blitzortung --service

**À titre indicatif seulement.** Les conditions de Blitzortung.org interdisent l'usage de leurs
données pour l'alerte aux orages, et les réservent à un usage non commercial. Assista-Crise les
AFFICHE (veille du territoire, carte) avec la mention « Informations Blitzortung données à titre
indicatif » ; aucune analyse, aucune cellule orageuse, aucune annonce n'en dépend. La foudre qui
entre dans les analyses est celle du satellite MTG (core/foudre.py).

Contrat relevé dans l'intégration (custom_components/blitzortung, version en service sur le NAS
le 19/11/2026) et vérifié sur le relais :

- broker `blitzortung.ha.sed.pl:1883`, sans compte, MQTT 3.1.1 ;
- un sujet par tuile geohash, un caractère par niveau : `b/1/<c1>/<c2>/…/<c6>` ;
- charge binaire de 16 octets, `<ffq` : latitude, longitude (flottants 32 bits), instant de
  l'impact en nanosecondes depuis 1970.

Mesuré le 19/11/2026 : 31 impacts en trois minutes sur la France, environ 3 secondes de retard.
"""
import datetime
import logging
import struct
import threading
import time

from django.core.management.base import BaseCommand
from django.utils import timezone

logger = logging.getLogger("core.blitzortung")

HOTE, PORT = "blitzortung.ha.sed.pl", 1883
PREFIXE = "b/1"
#: Tuiles geohash de deux caractères qui couvrent la métropole et la Corse.
TUILES = ("ez", "gb", "gc", "sp", "u0", "u1")
FORMAT = struct.Struct("<ffq")
#: Même emprise que la foudre satellite (core/foudre.EMPRISES).
EMPRISE = (-5.8, 41.0, 10.0, 51.6)
DUREE_GARDEE = datetime.timedelta(hours=24)
#: Impacts écrits par lots toutes les dix secondes.
VIDAGE_S = 10


def lire_impact(charge):
    """(instant, latitude, longitude) d'un message, ou None hors emprise ou illisible."""
    if len(charge) != FORMAT.size:
        return None
    latitude, longitude, ns = FORMAT.unpack(charge)
    ouest, sud, est, nord = EMPRISE
    if not (sud <= latitude <= nord and ouest <= longitude <= est):
        return None
    try:
        instant = datetime.datetime.fromtimestamp(ns / 1e9, tz=datetime.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return instant, round(float(latitude), 5), round(float(longitude), 5)


class Command(BaseCommand):
    help = "Écoute les impacts de foudre Blitzortung (à titre indicatif) et les copie en base."

    def add_arguments(self, parseur):
        parseur.add_argument("--service", action="store_true", help="Tourner en continu.")
        parseur.add_argument("--duree", type=int, default=0, help="Secondes avant l'arrêt (essai).")

    def handle(self, *args, **options):
        import paho.mqtt.client as mqtt
        from django.contrib.gis.geos import Point
        from core.models import ImpactBlitzortung, ReleveSourceOuverte

        verrou = threading.Lock()
        tampon, etat = [], {"connecte": False}

        def on_connect(client, userdata, flags, reason_code, properties=None):
            etat["connecte"] = reason_code == 0
            if reason_code == 0:
                for tuile in TUILES:
                    client.subscribe(f"{PREFIXE}/{'/'.join(tuile)}/#")
                logger.info("Connecté au relais Blitzortung, %d tuiles.", len(TUILES))
            else:
                logger.error("Relais Blitzortung : connexion refusée (%s).", reason_code)

        def on_disconnect(client, userdata, flags, reason_code, properties=None):
            etat["connecte"] = False
            logger.warning("Relais Blitzortung : déconnecté (%s).", reason_code)

        def on_message(client, userdata, message):
            impact = lire_impact(message.payload)
            if impact is not None:
                with verrou:
                    tampon.append(impact)

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
        client.connect_async(HOTE, PORT, keepalive=60)
        client.loop_start()
        debut, dernier_menage = time.time(), 0
        try:
            while True:
                time.sleep(VIDAGE_S)
                with verrou:
                    # Le relais renvoie parfois le même impact deux fois : un seul compte.
                    lot, tampon[:] = sorted(set(tampon)), []
                if lot:
                    ImpactBlitzortung.objects.bulk_create([ImpactBlitzortung(
                        instant=instant, location=Point(lon, lat, srid=4326)) for instant, lat, lon in lot])
                # La trace dit « relais joint », pas « il y a des impacts » : par temps calme, il
                # n'en arrive aucun, et ce n'est pas une panne.
                if etat["connecte"]:
                    trace, _ = ReleveSourceOuverte.objects.get_or_create(pk="FOUDRE_BLITZORTUNG")
                    trace.dernier_essai = trace.dernier_succes = timezone.now()
                    trace.lignes, trace.erreur = len(lot), ""
                    trace.save()
                if time.time() - dernier_menage > 600:
                    ImpactBlitzortung.objects.filter(instant__lt=timezone.now() - DUREE_GARDEE).delete()
                    dernier_menage = time.time()
                if not options["service"] and options["duree"] and time.time() - debut >= options["duree"]:
                    return
                if not options["service"] and not options["duree"]:
                    return
        except KeyboardInterrupt:
            return
        finally:
            client.loop_stop()
            client.disconnect()
