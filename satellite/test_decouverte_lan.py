"""Tests de decouverte_lan.py — aucun matériel MeshCore/Meshtastic réel requis : le scan de
port est vérifié contre un serveur TCP local factice, et la découverte mDNS est vérifiée sur
son repli (zeroconf absent) plutôt que contre un vrai service annoncé (pas reproductible en
CI). Voir la note du cadrage "Chantier B" sur les noms de service mDNS non confirmés."""
import asyncio
import sys

import pytest

import decouverte_lan


async def _demarrer_serveur_local():
    async def _gerer_client(reader, writer):
        writer.close()

    serveur = await asyncio.start_server(_gerer_client, "127.0.0.1", 0)
    port = serveur.sockets[0].getsockname()[1]
    return serveur, port


@pytest.mark.asyncio
async def test_tester_hote_succes_sur_port_ouvert():
    serveur, port = await _demarrer_serveur_local()
    try:
        resultat = await decouverte_lan._tester_hote("127.0.0.1", port, timeout=1.0)
        assert resultat == "127.0.0.1"
    finally:
        serveur.close()
        await serveur.wait_closed()


@pytest.mark.asyncio
async def test_tester_hote_echec_sur_port_ferme():
    # Port lié puis immédiatement fermé : personne n'écoute plus dessus.
    serveur, port = await _demarrer_serveur_local()
    serveur.close()
    await serveur.wait_closed()

    resultat = await decouverte_lan._tester_hote("127.0.0.1", port, timeout=0.5)
    assert resultat is None


@pytest.mark.asyncio
async def test_scanner_port_tcp_trouve_le_serveur_local():
    serveur, port = await _demarrer_serveur_local()
    try:
        resultats = await decouverte_lan.scanner_port_tcp(cidr="127.0.0.1/30", port=port, timeout=1.0)
        assert "127.0.0.1" in resultats
    finally:
        serveur.close()
        await serveur.wait_closed()


@pytest.mark.asyncio
async def test_scanner_port_tcp_sans_cidr_ni_reseau_ne_plante_pas(monkeypatch):
    monkeypatch.setattr(decouverte_lan, "reseau_local_cidr", lambda: None)
    resultats = await decouverte_lan.scanner_port_tcp()
    assert resultats == []


def test_decouvrir_mdns_replie_proprement_sans_zeroconf(monkeypatch):
    monkeypatch.setitem(sys.modules, "zeroconf", None)
    resultats = decouverte_lan.decouvrir_mdns(duree_s=0.1)
    assert resultats == []


@pytest.mark.asyncio
async def test_decouvrir_noeuds_lan_fusionne_et_deduplique(monkeypatch):
    async def fake_scanner_port_tcp(cidr=None, port=decouverte_lan.PORT_MESHCORE_DEFAUT, timeout=0.5, concurrence=64):
        return ["10.0.0.5", "10.0.0.9"]

    def fake_decouvrir_mdns(duree_s=5.0):
        return [{"nom": "noeud-a._meshcore._tcp.local.", "ip": "10.0.0.5", "port": 5000}]

    monkeypatch.setattr(decouverte_lan, "scanner_port_tcp", fake_scanner_port_tcp)
    monkeypatch.setattr(decouverte_lan, "decouvrir_mdns", fake_decouvrir_mdns)

    resultats = await decouverte_lan.decouvrir_noeuds_lan()

    par_ip = {r["ip"]: r for r in resultats}
    assert par_ip["10.0.0.5"]["source"] == "mdns+scan"
    assert par_ip["10.0.0.5"]["nom_mdns"] == "noeud-a._meshcore._tcp.local."
    assert par_ip["10.0.0.9"]["source"] == "scan"
    assert par_ip["10.0.0.9"]["nom_mdns"] is None


def test_reseau_local_cidr_renvoie_un_reseau_slash_24_ou_none():
    resultat = decouverte_lan.reseau_local_cidr()
    assert resultat is None or resultat.endswith("/24")
