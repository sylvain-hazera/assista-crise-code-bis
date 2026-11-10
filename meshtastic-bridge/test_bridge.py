"""Tests de bridge.py — l'ingestion MQTT, et rien d'autre.

    docker run --rm -v "$PWD/meshtastic-bridge":/src -w /src \
      --entrypoint python assista-crise-meshtastic-bridge:prod -m unittest -v test_bridge

`bridge.py` n'avait AUCUN test jusqu'au 10/11/2026, et ça s'est payé : `_observer_liaison_rf`
appelait `HasField("hop_start")` sur un scalaire proto3 sans présence, ce qui lève `ValueError`.
Comme la fonction est appelée en tête de `on_message`, **tout paquet relayé était abandonné en
entier** — ni message, ni position, ni contact, ni liaison. 1 201 fois en production, sans que
rien ne le dise à l'écran : le pont paraissait fonctionner parce que les paquets dont la
passerelle est l'émetteur lui-même sortent à la garde précédente.

Leçon encodée ici : ces tests construisent de **vrais** messages protobuf, jamais des faux
objets avec un `HasField` complaisant. Un faux aurait laissé passer exactement ce défaut.

Importer `bridge` exige les variables d'environnement de l'API (lues au chargement du module).
"""
import os
import unittest

os.environ.setdefault("DJANGO_API_URL", "http://exemple.invalide/api")
os.environ.setdefault("DJANGO_BRIDGE_EMAIL", "pont@exemple.invalide")
os.environ.setdefault("DJANGO_BRIDGE_PASSWORD", "x")

from meshtastic.protobuf import mesh_pb2, mqtt_pb2, portnums_pb2  # noqa: E402

import bridge  # noqa: E402


EMETTEUR = 0x1111
PASSERELLE = 0x22222222


class TamponEspion:
    def __init__(self):
        self.observations = []

    def observer(self, emetteur, recepteur, source, snr=None, rssi=None):
        self.observations.append((emetteur, recepteur, source, snr))


def _paquet(hop_start=None, hop_limit=None, snr=5.0):
    """Vrai MeshPacket. `hop_start=None` laisse le champ à son défaut (0), ce qui est ce qu'un
    firmware ancien produit — et le cas qui faisait lever `HasField`."""
    paquet = mesh_pb2.MeshPacket()
    if hop_start is not None:
        paquet.hop_start = hop_start
    if hop_limit is not None:
        paquet.hop_limit = hop_limit
    paquet.rx_snr = snr
    setattr(paquet, "from", EMETTEUR)
    return paquet


def _enveloppe(gateway_id=f"!{PASSERELLE:08x}"):
    enveloppe = mqtt_pb2.ServiceEnvelope()
    enveloppe.gateway_id = gateway_id
    return enveloppe


class TestObservationDesLiaisons(unittest.TestCase):

    def test_une_reception_directe_est_enregistree(self):
        """hop_start == hop_limit : le paquet n'a pas été relayé, donc `rx_snr` mesure bien la
        liaison entre cet émetteur et cette passerelle."""
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe(), _paquet(3, 3), EMETTEUR)
        self.assertEqual(tampon.observations, [(EMETTEUR, PASSERELLE, "RF", 5.0)])

    def test_un_paquet_relaye_n_est_pas_enregistre(self):
        """`rx_snr` est mesuré sur le DERNIER saut : l'enregistrer fabriquerait une liaison
        directe qui n'existe pas, et enverrait quelqu'un sur un point haut pour rien."""
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe(), _paquet(3, 2), EMETTEUR)
        self.assertEqual(tampon.observations, [])

    def test_un_firmware_sans_hop_start_ne_leve_pas(self):
        """**Le test de non-régression du défaut du 10/11/2026.** `hop_start` absent vaut 0 et
        signifie « ce firmware ne renseigne pas ce champ » : on s'abstient de conclure, sans
        lever -- une exception ici faisait abandonner le paquet entier dans `on_message`."""
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe(), _paquet(hop_limit=3), EMETTEUR)
        self.assertEqual(tampon.observations, [])

    def test_un_hop_start_a_zero_explicite_ne_leve_pas_non_plus(self):
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe(), _paquet(0, 0), EMETTEUR)
        self.assertEqual(tampon.observations, [])

    def test_une_passerelle_qui_est_l_emetteur_n_est_pas_une_liaison(self):
        """Un nœud qui publie son propre paquet ne prouve aucune liaison radio."""
        tampon = TamponEspion()
        bridge._observer_liaison_rf(
            tampon, _enveloppe(f"!{EMETTEUR:08x}"), _paquet(3, 3), EMETTEUR,
        )
        self.assertEqual(tampon.observations, [])

    def test_une_passerelle_illisible_est_ignoree(self):
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe("pas-un-node-id"), _paquet(3, 3), EMETTEUR)
        self.assertEqual(tampon.observations, [])

    def test_un_snr_absent_est_rapporte_comme_inconnu_et_non_comme_zero(self):
        """0 dB est une liaison confortable, « inconnu » n'est pas une valeur : les confondre
        ferait passer un nœud muet pour un nœud correct."""
        tampon = TamponEspion()
        bridge._observer_liaison_rf(tampon, _enveloppe(), _paquet(3, 3, snr=0.0), EMETTEUR)
        self.assertEqual(tampon.observations, [(EMETTEUR, PASSERELLE, "RF", None)])


class FauxDjango:
    def __init__(self):
        self.canal_entrant = []
        self.dm_entrant = []

    def logger_canal_entrant(self, canal_id, node_num, contenu):
        self.canal_entrant.append((canal_id, node_num, contenu))
        return "coroutine-canal"

    def logger_dm_entrant(self, compagnon_id, canal_id, node_num, contenu):
        self.dm_entrant.append((compagnon_id, canal_id, node_num, contenu))
        return "coroutine-dm"


def _texte(contenu="bonjour"):
    data = mesh_pb2.Data()
    data.portnum = portnums_pb2.PortNum.TEXT_MESSAGE_APP
    data.payload = contenu.encode()
    return data.SerializeToString()


class TestMessagesDeCanal(unittest.TestCase):

    COMPAGNON = {"id": "c1", "node_num": 0x9999}

    def _traiter(self, canal_id, to_node=bridge.BROADCAST_NUM):
        django = FauxDjango()
        coro = bridge._traiter_paquet_dechiffre(
            _texte(), EMETTEUR, to_node, canal_id, "Public",
            TamponEspion(), TamponEspion(), django, self.COMPAGNON, boucle=None,
        )
        return django, coro

    def test_un_message_de_canal_connu_est_journalise(self):
        django, coro = self._traiter("canal-1")
        self.assertEqual(coro, "coroutine-canal")
        self.assertEqual(django.canal_entrant, [("canal-1", EMETTEUR, "bonjour")])

    def test_un_message_en_clair_sur_un_canal_inconnu_n_est_pas_journalise(self):
        """Il est lisible, mais il n'appartient à aucun canal de chez nous : le journaliser
        revenait à POSTer `canal: null`, que l'API refuse — 14 erreurs 400 avec trace en
        production. La branche chiffrée avait déjà cette garde, la branche en clair non."""
        django, coro = self._traiter(None)
        self.assertIsNone(coro)
        self.assertEqual(django.canal_entrant, [])

    def test_un_DM_sans_canal_reste_journalise(self):
        """Un DM ne dépend pas d'un canal connu : `canal` est nullable sur MessageMeshtasticLog,
        contrairement à MessageCanalMeshtastic. La garde ne doit donc pas le bloquer."""
        django, coro = self._traiter(None, to_node=self.COMPAGNON["node_num"])
        self.assertEqual(coro, "coroutine-dm")
        self.assertEqual(django.dm_entrant, [("c1", None, EMETTEUR, "bonjour")])


if __name__ == "__main__":
    unittest.main()
