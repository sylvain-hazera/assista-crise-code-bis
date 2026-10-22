"""Tests d'etat_connectivite.py — httpx mocké via un transport factice (aucune vraie requête
réseau), fichier d'état écrit dans un répertoire temporaire (jamais le vrai
/var/run/satellite/)."""
import json

import httpx
import pytest

import etat_connectivite as ec


def _client_toujours_en_ligne():
    def handler(request):
        return httpx.Response(200, json={"ok": True})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _client_toujours_hors_ligne():
    def handler(request):
        raise httpx.ConnectError("réseau injoignable (test)")
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _client_erreur_5xx():
    # Une réponse 5xx applicative prouve qu'on a bien atteint assista-crise.fr — ça compte
    # comme "en ligne" au sens de ce détecteur (voir docstring de verifier_une_fois), seule
    # une vraie erreur réseau doit compter comme hors-ligne.
    def handler(request):
        return httpx.Response(503)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_verifier_une_fois_en_ligne():
    async with _client_toujours_en_ligne() as client:
        assert await ec.verifier_une_fois(client) is True


@pytest.mark.asyncio
async def test_verifier_une_fois_hors_ligne_sur_erreur_reseau():
    async with _client_toujours_hors_ligne() as client:
        assert await ec.verifier_une_fois(client) is False


@pytest.mark.asyncio
async def test_verifier_une_fois_5xx_compte_comme_en_ligne():
    async with _client_erreur_5xx() as client:
        assert await ec.verifier_une_fois(client) is True


def test_ecrire_etat_produit_un_json_valide_et_complet(tmp_path):
    fichier = str(tmp_path / "sous-dossier" / "etat.json")
    ec.ecrire_etat(True, depuis=1234.5, fichier=fichier)

    with open(fichier, encoding="utf-8") as f:
        data = json.load(f)
    assert data["en_ligne"] is True
    assert data["depuis"] == 1234.5
    assert "derniere_verification" in data
    assert data["central_url"] == ec.CENTRAL_URL


def test_ecrire_etat_ne_laisse_pas_de_fichier_temporaire(tmp_path):
    fichier = str(tmp_path / "etat.json")
    ec.ecrire_etat(False, depuis=1.0, fichier=fichier)
    assert not (tmp_path / "etat.json.tmp").exists()


@pytest.mark.asyncio
async def test_boucle_une_iteration_ecrit_letat_en_ligne(tmp_path):
    fichier = str(tmp_path / "etat.json")
    async with _client_toujours_en_ligne() as client:
        resultat = await ec.boucle(client=client, fichier_etat=fichier, une_seule_iteration=True)

    assert resultat is True
    with open(fichier, encoding="utf-8") as f:
        assert json.load(f)["en_ligne"] is True


@pytest.mark.asyncio
async def test_boucle_une_iteration_ecrit_letat_hors_ligne(tmp_path):
    fichier = str(tmp_path / "etat.json")
    async with _client_toujours_hors_ligne() as client:
        resultat = await ec.boucle(client=client, fichier_etat=fichier, une_seule_iteration=True)

    assert resultat is False
    with open(fichier, encoding="utf-8") as f:
        assert json.load(f)["en_ligne"] is False


@pytest.mark.asyncio
async def test_signal_de_vie_envoye_quand_en_ligne(tmp_path, monkeypatch):
    monkeypatch.setattr(ec, "SATELLITE_ID", "sat-1")
    monkeypatch.setattr(ec, "SATELLITE_EMAIL", "satellite-1@service.assista-crise.local")
    monkeypatch.setattr(ec, "SATELLITE_PASSWORD", "secret")
    monkeypatch.setattr(ec, "VERSION_LOGICIELLE", "abc123")
    appels = []

    def handler(request):
        appels.append((request.method, request.url.path, request.headers.get("authorization"), request.content))
        if request.url.path == "/api/token/":
            return httpx.Response(200, json={"access": "jeton-test"})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await ec.boucle(client=client, fichier_etat=str(tmp_path / "etat.json"), une_seule_iteration=True)

    contact = [a for a in appels if a[1] == "/api/satellites/sat-1/contact/"]
    assert contact and contact[0][0] == "POST" and contact[0][2] == "Bearer jeton-test"
    assert b"abc123" in contact[0][3]


@pytest.mark.asyncio
async def test_pas_de_signal_de_vie_sans_identifiants(tmp_path, monkeypatch):
    monkeypatch.setattr(ec, "SATELLITE_ID", "")
    appels = []

    def handler(request):
        appels.append(request.url.path)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await ec.boucle(client=client, fichier_etat=str(tmp_path / "etat.json"), une_seule_iteration=True)
    assert all("contact" not in p for p in appels)


@pytest.mark.asyncio
async def test_signal_de_vie_refuse_ne_casse_pas_la_boucle(tmp_path, monkeypatch):
    monkeypatch.setattr(ec, "SATELLITE_ID", "sat-1")
    monkeypatch.setattr(ec, "SATELLITE_EMAIL", "x")
    monkeypatch.setattr(ec, "SATELLITE_PASSWORD", "y")

    def handler(request):
        if request.url.path == "/api/token/":
            return httpx.Response(401)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await ec.boucle(client=client, fichier_etat=str(tmp_path / "etat.json"), une_seule_iteration=True) is True


@pytest.mark.asyncio
async def test_sonde_identifiee_aupres_du_central(monkeypatch):
    # Le central trace l'appel comme « Vérification de fonctionnement » de CE satellite
    # (SondeView) au lieu d'une consultation anonyme en échec de /api/.
    vus = []

    def handler(request):
        vus.append((request.url.path, request.headers.get("X-Sonde-Source")))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(ec, "SATELLITE_ID", "5d45e235-574c-4e7f-8e2c-fd8a3a00be28")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await ec.verifier_une_fois(client) is True
    assert vus == [("/api/sonde/", "satellite:5d45e235-574c-4e7f-8e2c-fd8a3a00be28")]


@pytest.mark.asyncio
async def test_ancien_central_sans_sonde_reste_en_ligne():
    # Central pas encore à jour : /api/sonde/ répond 404, ce qui prouve quand même qu'il est
    # joignable -- le satellite ne doit pas se croire hors ligne pour autant.
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))) as client:
        assert await ec.verifier_une_fois(client) is True
