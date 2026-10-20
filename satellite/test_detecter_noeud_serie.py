"""Tests de detecter_noeud_serie.py — sonder_meshcore/sonder_meshtastic sont mockés partout
(aucun matériel réel, ni même les libs meshcore/meshtastic installées, requises pour ces tests :
leurs imports sont différés à l'intérieur des fonctions, jamais évalués tant qu'on ne les
appelle pas pour de vrai). enregistrer_aupres_du_central est vérifié contre un httpx.MockTransport
(aucun vrai réseau)."""
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import detecter_noeud_serie as dns


def test_lister_devices_candidats_ignore_ce_qui_nexiste_pas(tmp_path, monkeypatch):
    monkeypatch.setattr(dns, "MOTIFS_DEVICES", [str(tmp_path / "ttyUSB*")])
    assert dns.lister_devices_candidats() == []

    (tmp_path / "ttyUSB0").touch()
    assert dns.lister_devices_candidats() == [str(tmp_path / "ttyUSB0")]


def test_ecrire_puis_lire_config_persistee(tmp_path):
    fichier = str(tmp_path / "noeud_serie.json")
    dns.ecrire_config_persistee({"device": "/dev/ttyUSB0", "protocole": "meshcore"}, fichier=fichier)

    relu = dns.lire_config_persistee(fichier=fichier)

    assert relu == {"device": "/dev/ttyUSB0", "protocole": "meshcore"}


def test_lire_config_persistee_absente_renvoie_none(tmp_path):
    assert dns.lire_config_persistee(fichier=str(tmp_path / "inexistant.json")) is None


def test_ecrire_config_persistee_ne_laisse_pas_de_tmp(tmp_path):
    fichier = str(tmp_path / "noeud_serie.json")
    dns.ecrire_config_persistee({"device": "/dev/ttyUSB0"}, fichier=fichier)
    assert not (tmp_path / "noeud_serie.json.tmp").exists()


@pytest.mark.asyncio
async def test_identifier_device_meshcore_prioritaire(monkeypatch):
    monkeypatch.setattr(dns, "sonder_meshcore", AsyncMock(return_value={"pubkey_hex": "abc"}))
    monkeypatch.setattr(dns, "sonder_meshtastic", lambda device, timeout=None: (_ for _ in ()).throw(AssertionError("ne doit pas être appelé")))

    resultat = await dns.identifier_device("/dev/ttyUSB0")

    assert resultat == {"protocole": "meshcore", "pubkey_hex": "abc"}


@pytest.mark.asyncio
async def test_identifier_device_bascule_sur_meshtastic(monkeypatch):
    monkeypatch.setattr(dns, "sonder_meshcore", AsyncMock(return_value=None))
    monkeypatch.setattr(dns, "sonder_meshtastic", lambda device, timeout=None: {"node_num": 42})

    resultat = await dns.identifier_device("/dev/ttyACM0")

    assert resultat == {"protocole": "meshtastic", "node_num": 42}


@pytest.mark.asyncio
async def test_identifier_device_rien_ne_repond(monkeypatch):
    monkeypatch.setattr(dns, "sonder_meshcore", AsyncMock(return_value=None))
    monkeypatch.setattr(dns, "sonder_meshtastic", lambda device, timeout=None: None)

    assert await dns.identifier_device("/dev/ttyUSB0") is None


@pytest.mark.asyncio
async def test_decouvrir_et_identifier_renvoie_le_premier_trouve(monkeypatch):
    monkeypatch.setattr(dns, "lister_devices_candidats", lambda: ["/dev/ttyUSB0", "/dev/ttyUSB1"])

    async def fake_identifier(device):
        return {"protocole": "meshcore", "pubkey_hex": "x"} if device == "/dev/ttyUSB1" else None

    monkeypatch.setattr(dns, "identifier_device", fake_identifier)

    resultat = await dns.decouvrir_et_identifier()

    assert resultat == {"device": "/dev/ttyUSB1", "protocole": "meshcore", "pubkey_hex": "x"}


@pytest.mark.asyncio
async def test_config_verifiee_reutilise_si_le_device_repond_encore(tmp_path, monkeypatch):
    fichier = str(tmp_path / "etat.json")
    dns.ecrire_config_persistee({"device": "/dev/ttyUSB0", "protocole": "meshcore", "pubkey_hex": "abc"}, fichier=fichier)
    monkeypatch.setattr(dns, "sonder_meshcore", AsyncMock(return_value={"pubkey_hex": "abc"}))
    decouverte_appelee = AsyncMock(return_value={"device": "/dev/ttyUSB1", "protocole": "meshtastic", "node_num": 1})
    monkeypatch.setattr(dns, "decouvrir_et_identifier", decouverte_appelee)

    resultat = await dns.config_verifiee_ou_redecouverte(fichier_etat=fichier)

    assert resultat["device"] == "/dev/ttyUSB0"
    decouverte_appelee.assert_not_called()


@pytest.mark.asyncio
async def test_config_verifiee_relance_une_decouverte_si_le_device_ne_repond_plus(tmp_path, monkeypatch):
    fichier = str(tmp_path / "etat.json")
    dns.ecrire_config_persistee({"device": "/dev/ttyUSB0", "protocole": "meshcore", "pubkey_hex": "abc"}, fichier=fichier)
    monkeypatch.setattr(dns, "sonder_meshcore", AsyncMock(return_value=None))
    nouvelle = {"device": "/dev/ttyUSB1", "protocole": "meshtastic", "node_num": 1}
    monkeypatch.setattr(dns, "decouvrir_et_identifier", AsyncMock(return_value=nouvelle))

    resultat = await dns.config_verifiee_ou_redecouverte(fichier_etat=fichier)

    assert resultat == nouvelle
    assert dns.lire_config_persistee(fichier=fichier) == nouvelle


@pytest.mark.asyncio
async def test_config_verifiee_sans_config_prealable_decouvre(tmp_path, monkeypatch):
    fichier = str(tmp_path / "etat.json")
    nouvelle = {"device": "/dev/ttyUSB0", "protocole": "meshcore", "pubkey_hex": "abc"}
    monkeypatch.setattr(dns, "decouvrir_et_identifier", AsyncMock(return_value=nouvelle))

    resultat = await dns.config_verifiee_ou_redecouverte(fichier_etat=fichier)

    assert resultat == nouvelle
    assert dns.lire_config_persistee(fichier=fichier) == nouvelle


@pytest.mark.asyncio
async def test_config_verifiee_aucun_noeud_trouve_ne_plante_pas(tmp_path, monkeypatch):
    fichier = str(tmp_path / "etat.json")
    monkeypatch.setattr(dns, "decouvrir_et_identifier", AsyncMock(return_value=None))

    resultat = await dns.config_verifiee_ou_redecouverte(fichier_etat=fichier)

    assert resultat is None
    assert dns.lire_config_persistee(fichier=fichier) is None


def _client_mock(reponses_par_url):
    def handler(request):
        for fragment, reponse in reponses_par_url.items():
            if fragment in str(request.url):
                return reponse
        raise AssertionError(f"URL inattendue : {request.url}")
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_enregistrer_aupres_du_central_meshcore():
    client = _client_mock({
        "/token/": httpx.Response(200, json={"access": "jwt-test"}),
        "/compagnons-meshcore/enregistrer-depuis-satellite/": httpx.Response(201, json={"id": "compagnon-1", "cree": True}),
    })
    identite = {"protocole": "meshcore", "pubkey_hex": "abc", "device": "/dev/ttyUSB0"}

    compagnon_id = await dns.enregistrer_aupres_du_central(identite, "https://assista-crise.fr/api", "x@x.fr", "pw", client=client)

    assert compagnon_id == "compagnon-1"


@pytest.mark.asyncio
async def test_enregistrer_aupres_du_central_meshtastic():
    client = _client_mock({
        "/token/": httpx.Response(200, json={"access": "jwt-test"}),
        "/compagnons-meshtastic/enregistrer-depuis-satellite/": httpx.Response(200, json={"id": "compagnon-2", "cree": False}),
    })
    identite = {"protocole": "meshtastic", "node_num": 42, "device": "/dev/ttyACM0"}

    compagnon_id = await dns.enregistrer_aupres_du_central(identite, "https://assista-crise.fr/api", "x@x.fr", "pw", client=client)

    assert compagnon_id == "compagnon-2"


@pytest.mark.asyncio
async def test_decouvrir_identifier_et_enregistrer_persiste_le_compagnon_id(tmp_path, monkeypatch):
    fichier = str(tmp_path / "etat.json")
    identite = {"device": "/dev/ttyUSB0", "protocole": "meshcore", "pubkey_hex": "abc"}
    monkeypatch.setattr(dns, "config_verifiee_ou_redecouverte", AsyncMock(return_value=dict(identite)))
    monkeypatch.setattr(dns, "enregistrer_aupres_du_central", AsyncMock(return_value="compagnon-1"))

    resultat = await dns.decouvrir_identifier_et_enregistrer("https://assista-crise.fr/api", "x@x.fr", "pw", fichier_etat=fichier)

    assert resultat["compagnon_id"] == "compagnon-1"
    assert dns.lire_config_persistee(fichier=fichier)["compagnon_id"] == "compagnon-1"


@pytest.mark.asyncio
async def test_decouvrir_identifier_et_enregistrer_central_injoignable_garde_la_detection(tmp_path, monkeypatch):
    fichier = str(tmp_path / "etat.json")
    identite = {"device": "/dev/ttyUSB0", "protocole": "meshcore", "pubkey_hex": "abc"}
    monkeypatch.setattr(dns, "config_verifiee_ou_redecouverte", AsyncMock(return_value=dict(identite)))
    monkeypatch.setattr(dns, "enregistrer_aupres_du_central", AsyncMock(side_effect=httpx.ConnectError("hors ligne")))

    resultat = await dns.decouvrir_identifier_et_enregistrer("https://assista-crise.fr/api", "x@x.fr", "pw", fichier_etat=fichier)

    assert resultat["device"] == "/dev/ttyUSB0"
    assert "compagnon_id" not in resultat


@pytest.mark.asyncio
async def test_decouvrir_identifier_et_enregistrer_ne_reappelle_pas_si_deja_enregistre(monkeypatch):
    identite = {"device": "/dev/ttyUSB0", "protocole": "meshcore", "pubkey_hex": "abc", "compagnon_id": "deja-la"}
    monkeypatch.setattr(dns, "config_verifiee_ou_redecouverte", AsyncMock(return_value=dict(identite)))
    appel = AsyncMock()
    monkeypatch.setattr(dns, "enregistrer_aupres_du_central", appel)

    resultat = await dns.decouvrir_identifier_et_enregistrer("https://assista-crise.fr/api", "x@x.fr", "pw")

    assert resultat["compagnon_id"] == "deja-la"
    appel.assert_not_called()


@pytest.mark.asyncio
async def test_boucle_une_iteration_sans_identifiants_central_fait_juste_la_detection_locale(monkeypatch):
    locale = AsyncMock(return_value={"device": "/dev/ttyUSB0", "protocole": "meshcore", "pubkey_hex": "abc"})
    monkeypatch.setattr(dns, "config_verifiee_ou_redecouverte", locale)
    centrale = AsyncMock()
    monkeypatch.setattr(dns, "decouvrir_identifier_et_enregistrer", centrale)

    resultat = await dns.boucle(une_seule_iteration=True)

    assert resultat["device"] == "/dev/ttyUSB0"
    locale.assert_called_once()
    centrale.assert_not_called()


@pytest.mark.asyncio
async def test_boucle_une_iteration_avec_identifiants_tente_lenregistrement_central(monkeypatch):
    centrale = AsyncMock(return_value={"device": "/dev/ttyUSB0", "protocole": "meshcore", "compagnon_id": "c1"})
    monkeypatch.setattr(dns, "decouvrir_identifier_et_enregistrer", centrale)
    locale = AsyncMock()
    monkeypatch.setattr(dns, "config_verifiee_ou_redecouverte", locale)

    resultat = await dns.boucle("https://assista-crise.fr/api", "x@x.fr", "pw", une_seule_iteration=True)

    assert resultat["compagnon_id"] == "c1"
    centrale.assert_called_once()
    locale.assert_not_called()


@pytest.mark.asyncio
async def test_boucle_sans_une_seule_iteration_repasse_apres_le_sleep(monkeypatch):
    # Vérifie que la boucle appelle bien asyncio.sleep entre deux passages (pas juste une seule
    # fois) -- s'arrête au 2e passage en levant une exception depuis le mock de sleep, seul
    # moyen de sortir d'un `while True` dans un test sans attendre pour de vrai.
    appels = AsyncMock(side_effect=[
        {"device": "/dev/ttyUSB0", "protocole": "meshcore"},
        {"device": "/dev/ttyUSB0", "protocole": "meshcore"},
    ])
    monkeypatch.setattr(dns, "config_verifiee_ou_redecouverte", appels)
    sleep_appele = AsyncMock(side_effect=[None, StopAsyncIteration])
    monkeypatch.setattr(dns.asyncio, "sleep", sleep_appele)

    with pytest.raises(StopAsyncIteration):
        await dns.boucle()

    assert appels.call_count == 2
    assert sleep_appele.call_count == 2


def test_detecter_et_enregistrer_toutes_les_radios(monkeypatch):
    # Installation automatique : MeshCore ET Meshtastic branchées -> les deux remontées et
    # enregistrées (decouvrir_et_identifier, lui, s'arrête à la première).
    import asyncio
    import detecter_noeud_serie as d

    monkeypatch.setattr(d, "lister_devices_candidats", lambda: ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyUSB1"])

    async def identifier(device):
        return {"/dev/ttyUSB0": {"protocole": "meshcore", "pubkey_hex": "ab"},
                "/dev/ttyACM0": {"protocole": "meshtastic", "node_num": 42}}.get(device)

    async def enregistrer(identite, *args, **kwargs):
        return f"id-{identite['protocole']}"

    monkeypatch.setattr(d, "identifier_device", identifier)
    monkeypatch.setattr(d, "enregistrer_aupres_du_central", enregistrer)
    radios = asyncio.run(d.detecter_et_enregistrer_toutes("https://central/api", "e", "p"))

    assert [(r["device"], r["protocole"], r["compagnon_id"]) for r in radios] == [
        ("/dev/ttyUSB0", "meshcore", "id-meshcore"), ("/dev/ttyACM0", "meshtastic", "id-meshtastic"),
    ]
