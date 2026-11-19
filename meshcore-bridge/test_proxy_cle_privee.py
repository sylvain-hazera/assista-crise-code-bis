"""Le proxy ne livre la clé privée de la radio qu'aux appareils autorisés (19/11/2026)."""
import asyncio
import os

os.environ.setdefault("MESHCORE_TCP_HOST", "127.0.0.1")
os.environ.setdefault("PROXY_MDNS_ANNONCE", "false")

import proxy  # noqa: E402

EXPORT, IMPORT, BATTERIE = bytes([23]), bytes([24]) + b"\x00" * 64, bytes([20])
NAS = {"172.16.1.124"}


def test_seul_l_appareil_autorise_touche_la_cle_privee():
    assert not proxy.cle_privee_refusee(EXPORT, "172.16.1.124", NAS)
    assert proxy.cle_privee_refusee(EXPORT, "172.16.1.50", NAS)
    assert proxy.cle_privee_refusee(IMPORT, "172.16.1.50", NAS)
    assert proxy.cle_privee_refusee(EXPORT, None, NAS)
    assert proxy.cle_privee_refusee(EXPORT, "172.16.1.124", frozenset())   # liste vide : refusé à tous


def test_les_autres_commandes_passent_pour_tous():
    assert not proxy.cle_privee_refusee(BATTERIE, "172.16.1.50", NAS)
    assert not proxy.cle_privee_refusee(b"", "172.16.1.50", NAS)


class FauxClient:
    def __init__(self, ip):
        self.ip, self.ecrit = ip, b""

    def get_extra_info(self, cle):
        return (self.ip, 4242) if cle == "peername" else None

    def write(self, octets):
        self.ecrit += octets

    async def drain(self):
        pass


def test_un_refus_repond_disabled_et_n_atteint_pas_la_radio(monkeypatch):
    monkeypatch.setattr(proxy, "AUTORISES_CLE_PRIVEE", frozenset(NAS))
    p = proxy.ProxyMeshCore()
    radio = FauxClient("radio")
    p.upstream_writer = radio
    intrus = FauxClient("172.16.1.50")
    asyncio.run(p._envoyer_commande(intrus, EXPORT))
    assert intrus.ecrit == b"\x3e\x01\x00\x0f"          # DISABLED
    assert radio.ecrit == b""                            # rien n'est parti vers la radio
