"""Essais du pont MeshCore (bridge.py)."""
import os
import unittest

os.environ.setdefault("DJANGO_API_URL", "http://localhost:8000/api")
os.environ.setdefault("COMPAGNON_ID", "00000000-0000-0000-0000-000000000000")
os.environ.setdefault("DJANGO_BRIDGE_EMAIL", "pont-essai@example.invalid")
os.environ.setdefault("DJANGO_BRIDGE_PASSWORD", "valeur-d-essai")

import bridge  # noqa: E402


class TestObservations(unittest.TestCase):
    """19/11/2026 : chaque trame entendue est gardée pour le serveur, avec SNR et RSSI."""

    def test_trame_gardee_sans_les_octets_du_firmware(self):
        obs = []
        bridge.noter_observation(obs, {"raw_hex": "1cc81100", "payload": "1100", "snr": 7.0, "rssi": -56,
                                       "recv_time": 1700000000})
        self.assertEqual(obs, [{"raw": "1100", "snr": 7.0, "rssi": -56, "t": 1700000000}])

    def test_sans_trame_rien(self):
        obs = []
        bridge.noter_observation(obs, {"snr": 1})
        bridge.noter_observation(obs, None)
        self.assertEqual(obs, [])

    def test_plafond(self):
        obs = [{}] * bridge.OBSERVATIONS_MAX
        bridge.noter_observation(obs, {"payload": "11"})
        self.assertEqual(len(obs), bridge.OBSERVATIONS_MAX)


class TestCentralSeulement(unittest.TestCase):
    def test_une_mesure_ne_part_pas_vers_le_local(self):
        import asyncio
        client = bridge.DjangoClient.__new__(bridge.DjangoClient)
        client._central, client._local = object(), object()
        client._cible_actuelle = lambda: client._local
        with self.assertRaises(bridge.CentralInjoignable):
            asyncio.run(client._request_central("POST", "/x/"))


class TestDoublonsRadio(unittest.TestCase):
    """Un message entendu par plusieurs relais ne part qu'une fois au serveur (24/11/2026)."""

    def test_l_identite_ne_depend_que_de_l_horodatage_et_du_texte(self):
        a = bridge.cle_radio(1764000000, "Léa: route coupée")
        self.assertEqual(a, bridge.cle_radio("1764000000", "Léa: route coupée"))
        self.assertNotEqual(a, bridge.cle_radio(1764000001, "Léa: route coupée"))
        self.assertTrue(a.startswith("1764000000:"))
        self.assertIsNone(bridge.cle_radio(None, "x"))

    def test_les_copies_sont_ecartees_puis_oubliees(self):
        temps = [0.0]
        vus = bridge.DejaVus(duree_s=60, horloge=lambda: temps[0])
        self.assertTrue(vus.nouveau(("canal", "k")))
        self.assertFalse(vus.nouveau(("canal", "k")))      # même message par un autre relais
        self.assertTrue(vus.nouveau(("autre", "k")))       # autre canal : autre message
        temps[0] = 61
        self.assertTrue(vus.nouveau(("canal", "k")))

    def test_le_decodage_logiciel_ne_transmet_qu_une_copie(self):
        import asyncio

        envoyes = []

        class Django:
            async def logger_message_canal_entrant(self, canal_id, contenu, cle_radio=None):
                envoyes.append((canal_id, contenu, cle_radio))

        ecouteurs = {}

        class Meshcore:
            def subscribe(self, genre, fonction):
                ecouteurs[genre] = fonction

        class Evenement:
            def __init__(self, chemin):
                self.payload = {"chan_hash": "ab", "message": "Léa: route coupée", "sender_timestamp": 1764000000,
                                "path": chemin}
                self.attributes = {"payload_type": 5}

        bridge.enregistrer_ecouteurs(Meshcore(), Django(), "c1", asyncio.Event(), {}, {}, {"ab": "canal-1"})
        for chemin in ("", "a1", "a1b2"):                       # trois relais, un seul message
            asyncio.run(ecouteurs[bridge.EventType.RX_LOG_DATA](Evenement(chemin)))
        self.assertEqual(len(envoyes), 1)
        self.assertEqual(envoyes[0][2], bridge.cle_radio(1764000000, "Léa: route coupée"))
