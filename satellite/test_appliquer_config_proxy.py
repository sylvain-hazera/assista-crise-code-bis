"""Tests d'appliquer_config_proxy.py — requests mocké (aucune vraie requête réseau), .env écrit
dans un répertoire temporaire (jamais le vrai satellite/.env), subprocess.run mocké (aucune
vraie invocation docker). Voir sa docstring : jamais testé de bout en bout sur du vrai
matériel — cette suite valide la logique pure, pas l'intégration Docker réelle."""
import pytest

import appliquer_config_proxy as acp


class FakeReponse:
    def __init__(self, data=None, status=200):
        self._data = data or {}
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise acp.requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def _config_defaut(monkeypatch, tmp_path):
    monkeypatch.setattr(acp, "SATELLITE_EMAIL", "sat@example.com")
    monkeypatch.setattr(acp, "SATELLITE_PASSWORD", "secret")
    monkeypatch.setattr(acp, "MESHCORE_COMPAGNON_ID", "compagnon-1")
    monkeypatch.setattr(acp, "FICHIER_ENV", str(tmp_path / ".env"))


def test_lire_env_puis_ecrire_env_round_trip(tmp_path):
    fichier = str(tmp_path / ".env")
    acp.FICHIER_ENV = fichier
    acp.ecrire_env({"MESHCORE_CONNEXION_TYPE": "TCP", "MESHCORE_TCP_HOST": "10.0.0.5"})
    valeurs = acp.lire_env()
    assert valeurs == {"MESHCORE_CONNEXION_TYPE": "TCP", "MESHCORE_TCP_HOST": "10.0.0.5"}


def test_lire_env_absent_renvoie_dict_vide(tmp_path):
    acp.FICHIER_ENV = str(tmp_path / "nexiste-pas.env")
    assert acp.lire_env() == {}


class TestConfigAChange:
    def test_aucun_changement(self):
        env_actuel = {"MESHCORE_CONNEXION_TYPE": "TCP", "MESHCORE_TCP_HOST": "10.0.0.5"}
        config_centrale = {"connexion_type": "TCP", "tcp_host": "10.0.0.5"}
        assert acp.config_a_change(config_centrale, env_actuel) is False

    def test_changement_detecte(self):
        env_actuel = {"MESHCORE_CONNEXION_TYPE": "TCP", "MESHCORE_TCP_HOST": "10.0.0.5"}
        config_centrale = {"connexion_type": "TCP", "tcp_host": "10.0.0.99"}
        assert acp.config_a_change(config_centrale, env_actuel) is True

    def test_valeur_centrale_vide_nignore_pas_un_vrai_changement_ailleurs(self):
        # tcp_host vide côté central (mode SERIE) ne doit pas, à lui seul, déclencher un
        # changement — mais connexion_type différent doit toujours être détecté.
        env_actuel = {"MESHCORE_CONNEXION_TYPE": "TCP", "MESHCORE_TCP_HOST": "10.0.0.5"}
        config_centrale = {"connexion_type": "SERIE", "tcp_host": None, "serie_device": "/dev/ttyUSB0"}
        assert acp.config_a_change(config_centrale, env_actuel) is True


@pytest.mark.usefixtures("_config_defaut")
class TestVerifierUneFois:
    def test_sans_configuration_ne_fait_aucun_appel(self, monkeypatch):
        monkeypatch.setattr(acp, "SATELLITE_EMAIL", "")
        appele = []
        monkeypatch.setattr(acp.requests, "post", lambda *a, **k: appele.append(1))
        acp.verifier_une_fois()
        assert appele == []

    def test_central_injoignable_ne_plante_pas(self, monkeypatch):
        def fake_post(*a, **k):
            raise acp.requests.ConnectionError("injoignable")
        monkeypatch.setattr(acp.requests, "post", fake_post)
        recree = []
        monkeypatch.setattr(acp, "recreer_proxy", lambda: recree.append(1))
        acp.verifier_une_fois()
        assert recree == []

    def test_aucun_changement_ne_declenche_ni_ecriture_ni_recreation(self, monkeypatch, tmp_path):
        acp.ecrire_env({"MESHCORE_CONNEXION_TYPE": "TCP", "MESHCORE_TCP_HOST": "10.0.0.5", "MESHCORE_TCP_PORT": "5000", "MESHCORE_SERIE_DEVICE": "/dev/ttyUSB0"})
        monkeypatch.setattr(acp.requests, "post", lambda *a, **k: FakeReponse({"access": "jeton"}))
        monkeypatch.setattr(acp.requests, "get", lambda *a, **k: FakeReponse({
            "connexion_type": "TCP", "tcp_host": "10.0.0.5", "tcp_port": 5000, "serie_device": "/dev/ttyUSB0",
        }))
        recree = []
        monkeypatch.setattr(acp, "recreer_proxy", lambda: recree.append(1))
        acp.verifier_une_fois()
        assert recree == []

    def test_changement_reecrit_env_et_recree_le_proxy(self, monkeypatch):
        acp.ecrire_env({"MESHCORE_CONNEXION_TYPE": "SERIE", "MESHCORE_SERIE_DEVICE": "/dev/ttyUSB0"})
        monkeypatch.setattr(acp.requests, "post", lambda *a, **k: FakeReponse({"access": "jeton"}))
        monkeypatch.setattr(acp.requests, "get", lambda *a, **k: FakeReponse({
            "connexion_type": "TCP", "tcp_host": "10.0.0.42", "tcp_port": 5000, "serie_device": None,
        }))
        recree = []
        monkeypatch.setattr(acp, "recreer_proxy", lambda: recree.append(1))
        acp.verifier_une_fois()
        assert recree == [1]
        nouvel_env = acp.lire_env()
        assert nouvel_env["MESHCORE_CONNEXION_TYPE"] == "TCP"
        assert nouvel_env["MESHCORE_TCP_HOST"] == "10.0.0.42"


def test_recreer_proxy_invoque_docker_compose_up_no_deps(monkeypatch, tmp_path):
    acp.FICHIER_ENV = str(tmp_path / ".env")
    appels = []

    class FakeResultat:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        appels.append(cmd)
        return FakeResultat()

    monkeypatch.setattr(acp.subprocess, "run", fake_run)
    acp.recreer_proxy()
    assert appels == [["docker", "compose", "up", "-d", "--no-deps", "meshcore-proxy"]]
