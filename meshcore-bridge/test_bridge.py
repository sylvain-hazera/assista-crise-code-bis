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
