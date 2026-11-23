"""Test minimal d'annoncer_backend_local.py — la boucle d'annonce elle-même (annoncer()) est une
boucle infinie qui parle réellement à zeroconf, vérifiée par smoke test manuel (voir la session
du 2026-09-17 sur meshcore-bridge/proxy.py, même technique) plutôt que par un test automatisé
qui ne testerait qu'un mock."""
import annoncer_backend_local as abl


def test_ip_locale_annoncable_renvoie_une_chaine_ou_none():
    resultat = abl._ip_locale_annoncable()
    assert resultat is None or isinstance(resultat, str)


def test_le_site_est_annonce_sous_le_nom_generique_et_le_backend_garde_le_sien():
    """23/11/2026 : les téléphones joignent http://assista-crise.local/ sans connaître l'IP."""
    if abl.ServiceInfo is None:
        import pytest
        pytest.skip("zeroconf absent")
    backend, site = abl.services("192.168.1.20")
    assert site.type == "_http._tcp.local." and site.server == "assista-crise.local." and site.port == abl.PORT_WEB
    assert backend.server == f"{abl.NOM_INSTANCE}.local." and backend.port == abl.PORT_BACKEND
    assert site.properties[b"role"] == b"site-local"


def test_les_adresses_locales_sont_ecrites_pour_le_signal_de_vie(tmp_path):
    import json
    fichier = tmp_path / "sous" / "adresses_locales.json"
    abl.ecrire_adresses("192.168.1.20", fichier=str(fichier))
    contenu = json.loads(fichier.read_text())
    assert contenu["ips"] == ["192.168.1.20"] and contenu["port_web"] == abl.PORT_WEB
    assert "assista-crise.local" in contenu["noms"]
