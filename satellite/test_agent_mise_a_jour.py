"""Tests de l'agent de mise à jour.

Ce qui est RÉEL ici : git (deux dépôts temporaires, un « origin » et sa copie sur le
satellite) et les signatures (`ssh-keygen` signe et vérifie pour de vrai, avec des clés
créées pour le test). Ce qui est simulé : Docker, `installer.sh` et le central.

Ce que ces tests tiennent, par ordre d'importance :

1. **Sans signature valide, RIEN ne bouge** — ni le code, ni Docker.
2. **Pas de retour en arrière**, même vers une version correctement signée.
3. **On construit avant de remplacer** : une construction ratée remet le code d'avant.
4. **Un ordre annulé n'est pas exécuté.**
5. **Le compte rendu final n'est jamais perdu**, même central injoignable.
"""
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest

import agent_mise_a_jour as agent


def _git(depot, *arguments):
    resultat = subprocess.run(
        ["git", "-C", str(depot), "-c", "user.name=Essai", "-c", "user.email=essai@exemple.test",
         "-c", "commit.gpgsign=false", *arguments],
        capture_output=True, check=True)
    return resultat.stdout.decode().strip()


def _commit(depot, fichier, contenu):
    (Path(depot) / fichier).write_text(contenu, encoding="utf-8")
    _git(depot, "add", fichier)
    _git(depot, "commit", "-q", "-m", f"modifie {fichier}")
    return _git(depot, "rev-parse", "HEAD")


def _signer(cle, commit, espace=agent.ESPACE_DE_NOMS):
    return subprocess.run(
        ["ssh-keygen", "-Y", "sign", "-f", str(cle), "-n", espace],
        input=agent.message_a_signer(commit), capture_output=True, check=True).stdout.decode()


@pytest.fixture
def cles(tmp_path):
    """La clé du responsable, et celle de quelqu'un d'autre."""
    for nom in ("responsable", "intrus"):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", nom,
                        "-f", str(tmp_path / nom)], check=True)
    return tmp_path / "responsable", tmp_path / "intrus"


@pytest.fixture
def depots(tmp_path):
    """`origin` avec trois versions ; le satellite est installé sur la deuxième."""
    origine = tmp_path / "origine"
    origine.mkdir()
    _git(origine, "init", "-q", "-b", "main")
    (origine / "satellite").mkdir()
    v1 = _commit(origine, "satellite/version.txt", "1")
    v2 = _commit(origine, "satellite/version.txt", "2")
    local = tmp_path / "satellite-installe"
    subprocess.run(["git", "clone", "-q", str(origine), str(local)], check=True)
    v3 = _commit(origine, "satellite/version.txt", "3")
    (local / "satellite" / ".profil").write_text("full", encoding="utf-8")
    return {"origine": origine, "local": local, "v1": v1, "v2": v2, "v3": v3}


class CentralFactice:
    def __init__(self, accepte=True, en_panne=False):
        self.rapports = []
        self.accepte = accepte
        self.en_panne = en_panne
        self.ordre_a_rendre = None

    def ordre(self, version_installee):
        self.version_vue = version_installee
        return self.ordre_a_rendre

    def rapport(self, ordre_id, statut, etape, journal="", version=""):
        if self.en_panne:
            raise urllib.error.URLError("central injoignable")
        self.rapports.append((statut, etape, version))
        return self.accepte


class MachineFactice(agent.Machine):
    """Git réel ; Docker, installer.sh, sauvegarde et santé simulés."""

    def __init__(self, repertoire, construction=0, demarrage=0, sante=(True, "")):
        super().__init__(repertoire)
        self.codes = {"build": construction, "demarrer": demarrage}
        self.sante = sante
        self.appels = []

    def lancer(self, commande, cwd=None, delai=600, entree=None):
        commande = [str(c) for c in commande]
        if commande[0] == "docker":
            self.appels.append("docker " + commande[-1])
            return self.codes["build"], "sortie de construction"
        if commande[0].endswith("installer.sh"):
            self.appels.append("installer.sh " + commande[1])
            return self.codes["demarrer"], ""
        return super().lancer(commande, cwd, delai, entree)

    def sauvegarder_la_base(self, env, commit):
        self.appels.append("sauvegarde")
        return self.satellite / "sauvegardes" / "essai.sql.gz"

    def en_bonne_sante(self, env, attente=0, pause=None):
        return self.sante

    def espace_libre_go(self):
        return 50


@pytest.fixture
def poste(depots, cles, tmp_path):
    """Le satellite prêt : machine, clé publique gardée sur place, fabrique d'ordres."""
    cle_gardee = tmp_path / "cle-gardee.pub"
    cle_gardee.write_text(Path(str(cles[0]) + ".pub").read_text(), encoding="utf-8")

    def ordre(commit, cle=cles[0], **surcharge):
        return {"id": "ordre-1", "commit": commit, "signature": _signer(cle, commit),
                **surcharge}

    return {"dossier": depots["local"] / "satellite", "cle": cle_gardee, "ordre": ordre,
            **depots}


def _appliquer(poste, ordre, central=None, **machine):
    central = central or CentralFactice()
    m = MachineFactice(poste["dossier"], **machine)
    return agent.appliquer(ordre, central, m, {}, poste["cle"]), central, m


class TestLaSignatureAvantTout:

    def test_une_version_signee_est_installee(self, poste):
        resultat, central, machine = _appliquer(poste, poste["ordre"](poste["v3"]))
        assert resultat == ("REUSSIE", "Mise à jour terminée.", poste["v3"])
        assert machine.commit_installe() == poste["v3"]
        # L'ordre des gestes : sauvegarde, construction, PUIS redémarrage.
        assert machine.appels == ["sauvegarde", "docker build", "installer.sh demarrer"]
        assert central.rapports[0][0] == "EN_COURS"

    def test_une_signature_d_une_autre_cle_ne_change_rien(self, poste, cles):
        resultat, central, machine = _appliquer(
            poste, poste["ordre"](poste["v3"], cle=cles[1]))
        assert resultat[0] == "ECHOUEE" and "Signature refusée" in resultat[1]
        assert machine.commit_installe() == poste["v2"]
        assert machine.appels == []
        # Le central n'a même pas été informé d'une prise en charge.
        assert central.rapports == []

    def test_la_signature_d_un_autre_commit_ne_vaut_pas_pour_celui_ci(self, poste):
        ordre = poste["ordre"](poste["v2"])
        ordre["commit"] = poste["v3"]
        resultat, _central, machine = _appliquer(poste, ordre)
        assert resultat[0] == "ECHOUEE"
        assert machine.commit_installe() == poste["v2"] and machine.appels == []

    def test_une_signature_faite_pour_un_autre_usage_est_refusee(self, poste, cles):
        ordre = {"id": "o", "commit": poste["v3"],
                 "signature": _signer(cles[0], poste["v3"], espace="git")}
        resultat, _c, machine = _appliquer(poste, ordre)
        assert resultat[0] == "ECHOUEE" and machine.appels == []

    def test_sans_cle_gardee_le_satellite_n_accepte_rien(self, poste, tmp_path):
        poste["cle"] = tmp_path / "absente.pub"
        resultat, _c, machine = _appliquer(poste, poste["ordre"](poste["v3"]))
        assert resultat[0] == "ECHOUEE" and "clé de signature" in resultat[1]
        assert machine.appels == []

    @pytest.mark.parametrize("commit", ["", "abc1234", "HEAD", "main; rm -rf /", "A" * 40])
    def test_seul_un_commit_complet_est_accepte(self, poste, commit):
        """Le central ne transmet qu'un numéro : tout le reste est refusé avant usage."""
        resultat, _c, machine = _appliquer(
            poste, {"id": "o", "commit": commit, "signature": "x"})
        assert resultat[0] == "ECHOUEE" and machine.appels == []


class TestCeQuiEstRefuseSansRienModifier:

    def test_pas_de_retour_en_arriere_meme_signe(self, poste):
        """Une vieille version reste correctement signée pour toujours : c'est l'ordre des
        commits, pas la signature, qui interdit de la rejouer."""
        resultat, _c, machine = _appliquer(poste, poste["ordre"](poste["v1"]))
        assert resultat[0] == "ECHOUEE" and "retour en arrière" in resultat[1]
        assert machine.commit_installe() == poste["v2"] and machine.appels == []

    def test_une_version_pas_encore_poussee(self, poste):
        resultat, _c, machine = _appliquer(poste, poste["ordre"]("c" * 40))
        assert resultat[0] == "ECHOUEE" and "n'existe pas" in resultat[1]
        assert machine.appels == []

    def test_des_fichiers_modifies_sur_place(self, poste):
        (poste["dossier"] / "version.txt").write_text("bricolage", encoding="utf-8")
        resultat, _c, machine = _appliquer(poste, poste["ordre"](poste["v3"]))
        assert resultat[0] == "ECHOUEE" and "modifiés sur place" in resultat[1]
        assert (poste["dossier"] / "version.txt").read_text() == "bricolage"
        assert machine.appels == []

    def test_un_ordre_annule_n_est_pas_execute(self, poste):
        resultat, central, machine = _appliquer(
            poste, poste["ordre"](poste["v3"]), central=CentralFactice(accepte=False))
        assert resultat is None
        assert machine.commit_installe() == poste["v2"] and machine.appels == []

    def test_deja_sur_la_version_demandee(self, poste):
        resultat, _c, machine = _appliquer(poste, poste["ordre"](poste["v2"]))
        assert resultat[0] == "REUSSIE" and machine.appels == []


class TestQuandCaSePasseMal:

    def test_une_construction_ratee_remet_le_code_d_avant(self, poste):
        resultat, _c, machine = _appliquer(
            poste, poste["ordre"](poste["v3"]), construction=1)
        assert resultat[0] == "ECHOUEE" and "n'a pas cessé de tourner" in resultat[1]
        assert resultat[2] == poste["v2"]
        assert machine.commit_installe() == poste["v2"]
        # Jamais redémarré : l'ancienne version tourne toujours.
        assert "installer.sh demarrer" not in machine.appels

    def test_un_redemarrage_rate_le_dit_sans_pretendre_etre_revenu(self, poste):
        resultat, _c, machine = _appliquer(
            poste, poste["ordre"](poste["v3"]), demarrage=1)
        assert resultat[0] == "ECHOUEE" and "sauvegarde" in resultat[1]
        # Les migrations ont pu passer : on ne remet pas l'ancien code sur la nouvelle base.
        assert machine.commit_installe() == poste["v3"]

    def test_un_satellite_qui_ne_repond_plus_apres_coup_est_un_echec(self, poste):
        resultat, _c, _m = _appliquer(
            poste, poste["ordre"](poste["v3"]),
            sante=(False, "le site local ne répond pas"))
        assert resultat[0] == "ECHOUEE" and "le site local ne répond pas" in resultat[1]

    def test_le_central_peut_disparaitre_pendant_la_mise_a_jour(self, poste):
        """Il a pris l'ordre, puis le réseau tombe : la mise à jour va au bout."""

        class CentralQuiTombe(CentralFactice):
            def rapport(self, *arguments, **options):
                if self.rapports:
                    raise urllib.error.URLError("coupure")
                return super().rapport(*arguments, **options)

        resultat, _c, machine = _appliquer(
            poste, poste["ordre"](poste["v3"]), central=CentralQuiTombe())
        assert resultat[0] == "REUSSIE" and machine.commit_installe() == poste["v3"]


class TestUnPassage:

    def test_rien_a_faire_annonce_quand_meme_la_version(self, poste, tmp_path):
        central = CentralFactice()
        machine = MachineFactice(poste["dossier"])
        mot = agent.passage(central, machine, {}, poste["cle"], tmp_path / "rapport.json")
        assert mot == "rien à faire" and central.version_vue == poste["v2"]

    def test_le_compte_rendu_garde_part_au_passage_suivant(self, poste, tmp_path):
        rapport = tmp_path / "rapport.json"
        central = CentralFactice()
        central.ordre_a_rendre = poste["ordre"](poste["v3"])

        class PanneALaFin(CentralFactice):
            def rapport(self, ordre_id, statut, *reste, **options):
                if statut != "EN_COURS":
                    raise urllib.error.URLError("coupure")
                return super().rapport(ordre_id, statut, *reste, **options)

        coupe = PanneALaFin()
        coupe.ordre_a_rendre = central.ordre_a_rendre
        with pytest.raises(urllib.error.URLError):
            agent.passage(coupe, MachineFactice(poste["dossier"]), {}, poste["cle"], rapport)
        garde = json.loads(rapport.read_text())
        assert garde["statut"] == "REUSSIE" and garde["version"] == poste["v3"]
        assert oct(rapport.stat().st_mode & 0o777) == "0o600"

        central.ordre_a_rendre = None
        agent.passage(central, MachineFactice(poste["dossier"]), {}, poste["cle"], rapport)
        assert central.rapports == [("REUSSIE", "Mise à jour terminée.", poste["v3"])]
        assert not rapport.exists()


def test_lire_env(tmp_path):
    fichier = tmp_path / ".env"
    fichier.write_text("# commentaire\nCENTRAL_URL=https://exemple.test/\nDB_PASS=a=b\n\n")
    assert agent.lire_env(fichier) == {"CENTRAL_URL": "https://exemple.test/", "DB_PASS": "a=b"}
    assert agent.lire_env(tmp_path / "absent") == {}


def test_le_message_signe_est_celui_du_central():
    """Les deux côtés doivent signer et vérifier EXACTEMENT le même texte."""
    racine = Path(__file__).resolve().parent.parent
    source = (racine / "backend" / "core" / "signature_satellites.py").read_text(encoding="utf-8")
    assert f'ESPACE_DE_NOMS = "{agent.ESPACE_DE_NOMS}"' in source
    assert 'f"{ESPACE_DE_NOMS}/v1\\ncommit={commit}\\n"' in source
    assert agent.message_a_signer("a" * 40) == \
        b"assista-crise-satellite/v1\ncommit=" + b"a" * 40 + b"\n"


class TestLaSauvegarde:
    """Avec un faux `docker` dans le PATH : le vrai `pg_dump` n'est pas testé ici, mais tout
    ce que l'agent fait de sa sortie l'est."""

    def _faux_docker(self, tmp_path, monkeypatch, script):
        dossier = tmp_path / "bin"
        dossier.mkdir()
        faux = dossier / "docker"
        faux.write_text("#!/bin/sh\n" + script, encoding="utf-8")
        faux.chmod(0o755)
        monkeypatch.setenv("PATH", f"{dossier}:/usr/bin:/bin")

    def test_elle_est_compressee_et_lisible_par_son_seul_proprietaire(
            self, tmp_path, monkeypatch):
        import gzip

        self._faux_docker(tmp_path, monkeypatch, 'echo "CREATE TABLE essai();"\n')
        satellite = tmp_path / "satellite"
        satellite.mkdir()
        fichier = agent.Machine(satellite).sauvegarder_la_base({"DB_USER": "assista"}, "a" * 40)

        assert fichier.parent == satellite / "sauvegardes"
        assert oct(fichier.stat().st_mode & 0o777) == "0o600"
        assert oct(fichier.parent.stat().st_mode & 0o777) == "0o700"
        assert gzip.open(fichier).read() == b"CREATE TABLE essai();\n"

    def test_une_sauvegarde_ratee_arrete_tout_et_ne_laisse_pas_de_fichier(
            self, tmp_path, monkeypatch):
        self._faux_docker(tmp_path, monkeypatch, 'echo "base injoignable" >&2\nexit 1\n')
        satellite = tmp_path / "satellite"
        satellite.mkdir()
        with pytest.raises(agent.Echec, match="Rien n'a été modifié"):
            agent.Machine(satellite).sauvegarder_la_base({}, "a" * 40)
        assert list((satellite / "sauvegardes").iterdir()) == []

    def test_une_sauvegarde_vide_est_un_echec(self, tmp_path, monkeypatch):
        """`pg_dump` qui sort sans rien écrire : un fichier vide ne sauvegarde rien."""
        self._faux_docker(tmp_path, monkeypatch, "exit 0\n")
        satellite = tmp_path / "satellite"
        satellite.mkdir()
        with pytest.raises(agent.Echec):
            agent.Machine(satellite).sauvegarder_la_base({}, "a" * 40)

    def test_seules_les_trois_dernieres_sont_gardees(self, tmp_path, monkeypatch):
        import os

        self._faux_docker(tmp_path, monkeypatch, 'echo "SELECT 1;"\n')
        satellite = tmp_path / "satellite"
        (satellite / "sauvegardes").mkdir(parents=True)
        for i in range(4):
            ancien = satellite / "sauvegardes" / f"avant-ancien{i}-2026.sql.gz"
            ancien.write_bytes(b"x")
            os.utime(ancien, (1000 + i, 1000 + i))
        agent.Machine(satellite).sauvegarder_la_base({}, "a" * 40)
        restants = sorted(f.name for f in (satellite / "sauvegardes").iterdir())
        assert len(restants) == agent.SAUVEGARDES_GARDEES
        assert "avant-ancien0-2026.sql.gz" not in restants
        assert "avant-ancien1-2026.sql.gz" not in restants


class TestCompteRenduRefuseParLeCentral:
    """17/11/2026 : le pare-feu du central répondait 403 à tout compte rendu qui portait un
    journal. Le compte rendu final restait sur les bras, repartait à chaque passage, et l'agent
    ne revenait plus jamais chercher d'ordre — pendant que trois refus par heure faisaient
    bannir le satellite."""

    def _central(self, reponses):
        """Un vrai `Central`, dont le réseau rend successivement `reponses` (un code HTTP, ou
        None pour un succès). Garde ce qui a été envoyé."""
        envoyes = []

        class Reponse:
            def __enter__(self):
                return self

            def __exit__(self, *arguments):
                return False

            def read(self):
                return b'{"access": "jeton", "statut": "EN_COURS"}'

        def ouvrir(requete, timeout=None):
            if requete.full_url.endswith("/api/token/"):
                return Reponse()
            envoyes.append(json.loads(requete.data.decode()))
            code = reponses.pop(0)
            if code is not None:
                raise urllib.error.HTTPError(requete.full_url, code, "refus", {}, None)
            return Reponse()

        env = {"SATELLITE_ID": "s1", "SATELLITE_EMAIL": "s@x", "SATELLITE_PASSWORD": "p",
               "CENTRAL_URL": "https://central.invalide"}
        return agent.Central(env, ouvrir=ouvrir), envoyes

    def test_un_refus_du_contenu_fait_repartir_le_compte_rendu_sans_son_journal(self):
        central, envoyes = self._central([403, None])

        assert central.rapport("o1", "ECHOUEE", "La construction a échoué.", "$ docker compose build\nERREUR") is True

        assert "docker compose build" in envoyes[0]["journal"]
        # Le second envoi porte l'essentiel, pas le journal — et ne cherche pas à le déguiser.
        assert (envoyes[1]["statut"], envoyes[1]["etape"]) == ("ECHOUEE", "La construction a échoué.")
        assert "docker" not in envoyes[1]["journal"] and "403" in envoyes[1]["journal"]

    def test_un_ordre_annule_reste_un_arret(self):
        central, _ = self._central([409])
        assert central.rapport("o1", "EN_COURS", "Vérification") is False
        central, _ = self._central([403, 409])
        assert central.rapport("o1", "EN_COURS", "Vérification", "journal") is False

    def test_une_panne_du_central_n_est_pas_prise_pour_un_refus(self):
        central, envoyes = self._central([502])
        with pytest.raises(urllib.error.HTTPError):
            central.rapport("o1", "REUSSIE", "Mise à jour terminée.", "journal")
        assert len(envoyes) == 1                       # pas de second envoi : on réessaiera

    def test_si_meme_l_essentiel_est_refuse_on_le_sait(self):
        central, envoyes = self._central([403, 403])
        with pytest.raises(urllib.error.HTTPError):
            central.rapport("o1", "REUSSIE", "Mise à jour terminée.", "journal")
        assert len(envoyes) == 2
