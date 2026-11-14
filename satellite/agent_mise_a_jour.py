#!/usr/bin/env python3
"""Agent de mise à jour du satellite : applique les mises à jour ordonnées par le central.

Demande de Sylvain du 14/11/2026. Lancé toutes les deux minutes par systemd
(`assista-satellite-maj.timer`, installé par `installer.sh`), SUR LA MACHINE et non dans un
conteneur : une mise à jour reconstruit et remplace les conteneurs, et un conteneur qui se
mettrait à jour lui-même se couperait au milieu du travail.

**Il ne sait faire qu'une chose** : amener le dépôt à un commit précis, reconstruire,
redémarrer. Le central ne lui transmet aucune commande — seulement un numéro de commit et sa
signature. Avant de toucher à quoi que ce soit, il vérifie que :

1. la signature est bien celle de ce commit, par la clé publique gardée ICI à l'installation
   (`.cle-signature.pub`) — jamais par une clé venue du central ou du dépôt mis à jour ;
2. le commit est une SUITE de la version installée (pas de retour en arrière, donc pas de
   rejeu d'une vieille version signée pour rouvrir une faille corrigée) ;
3. le central a bien enregistré sa prise en charge (un ordre annulé s'arrête là).

Puis, dans cet ordre : sauvegarde de la base (profil complet), récupération du code,
CONSTRUCTION — et seulement si elle réussit, redémarrage. Tant que la construction n'a pas
abouti, l'ancienne version continue de tourner.

Bibliothèque standard uniquement : la machine d'un satellite n'a que `python3`, et un agent
de mise à jour qui dépendrait d'un paquet à installer serait le premier à casser.
"""
import fcntl
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPERTOIRE = Path(__file__).resolve().parent
#: Doit rester identique à `ESPACE_DE_NOMS` de backend/core/signature_satellites.py.
ESPACE_DE_NOMS = "assista-crise-satellite"
IDENTITE = "signature-satellites"

#: Place libre exigée avant de commencer : une construction qui remplit le disque laisse une
#: machine qu'on ne peut plus ni mettre à jour ni même démarrer.
ESPACE_LIBRE_MIN_GO = 3
DUREE_MAX_CONSTRUCTION_S = 3 * 3600
DUREE_MAX_DEMARRAGE_S = 3600
ATTENTE_SANTE_S = 600
SAUVEGARDES_GARDEES = 3
#: Ce qu'on garde de la sortie des commandes, par rapport envoyé. La FIN : l'erreur y est.
TAILLE_JOURNAL = 30_000


class Echec(Exception):
    """La mise à jour s'arrête. Le message est celui qu'on lira sur la page Satellites."""


def lire_env(fichier):
    """Les `CLE=valeur` d'un fichier .env. Pas de guillemets ni d'échappements : c'est le
    format qu'écrit `installer.sh`."""
    valeurs = {}
    try:
        lignes = Path(fichier).read_text(encoding="utf-8").splitlines()
    except OSError:
        return valeurs
    for ligne in lignes:
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            valeurs[cle.strip()] = valeur.strip()
    return valeurs


def message_a_signer(commit):
    """Identique à `signature_satellites.message_a_signer` côté central."""
    return f"{ESPACE_DE_NOMS}/v1\ncommit={commit}\n".encode()


def commit_valide(commit):
    return (isinstance(commit, str) and len(commit) == 40
            and all(c in "0123456789abcdef" for c in commit))


def verifier_signature(commit, signature, fichier_cle):
    """Lève `Echec` si la signature n'est pas celle de ce commit par une clé gardée ici.

    `ssh-keygen -Y verify` : présent sur toute machine Linux, rien à installer."""
    if not commit_valide(commit):
        raise Echec("Numéro de version invalide : refusé sans rien faire.")
    try:
        cles = [ligne.strip() for ligne in Path(fichier_cle).read_text(encoding="utf-8").splitlines()
                if ligne.strip().startswith("ssh-ed25519 ")]
    except OSError:
        cles = []
    if not cles:
        raise Echec(
            "Ce satellite n'a pas de clé de signature (.cle-signature.pub) : il n'accepte "
            "aucune mise à jour à distance. Sur place : ./installer.sh mettre-a-jour")
    if shutil.which("ssh-keygen") is None:
        raise Echec("ssh-keygen est absent de cette machine : sudo apt install -y openssh-client")

    with tempfile.TemporaryDirectory() as dossier:
        autorises = Path(dossier) / "autorises"
        autorises.write_text("".join(
            f'{IDENTITE} namespaces="{ESPACE_DE_NOMS}" {" ".join(cle.split()[:2])}\n'
            for cle in cles), encoding="utf-8")
        bloc = Path(dossier) / "signature"
        bloc.write_text((signature or "").strip() + "\n", encoding="utf-8")
        resultat = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(autorises), "-I", IDENTITE,
             "-n", ESPACE_DE_NOMS, "-s", str(bloc)],
            input=message_a_signer(commit), capture_output=True, timeout=30, check=False)
    if resultat.returncode != 0:
        raise Echec("Signature refusée : cette version n'est pas signée par la clé que ce "
                    "satellite connaît. Rien n'a été modifié.")


class Central:
    """Les trois appels que l'agent fait au central, avec le compte de service du satellite."""

    def __init__(self, env, ouvrir=urllib.request.urlopen):
        self.url = (env.get("CENTRAL_URL") or "https://assista-crise.fr").rstrip("/")
        self.satellite = env.get("SATELLITE_ID", "")
        self.email = env.get("SATELLITE_EMAIL", "")
        self.mot_de_passe = env.get("SATELLITE_PASSWORD", "")
        self._ouvrir = ouvrir
        self._jeton = None

    @property
    def configure(self):
        return bool(self.satellite and self.email and self.mot_de_passe)

    def _appel(self, methode, chemin, corps=None, authentifie=True):
        entetes = {"Content-Type": "application/json", "User-Agent": "satellite-agent-maj"}
        if authentifie:
            entetes["Authorization"] = f"Bearer {self._jeton_d_acces()}"
        requete = urllib.request.Request(
            self.url + chemin, method=methode, headers=entetes,
            data=json.dumps(corps).encode() if corps is not None else None)
        with self._ouvrir(requete, timeout=30) as reponse:
            return json.loads(reponse.read().decode() or "{}")

    def _jeton_d_acces(self):
        if self._jeton is None:
            self._jeton = self._appel(
                "POST", "/api/token/",
                {"email": self.email, "password": self.mot_de_passe},
                authentifie=False)["access"]
        return self._jeton

    def ordre(self, version_installee):
        chemin = f"/api/satellites/{self.satellite}/ordre-mise-a-jour/"
        if version_installee:
            chemin += f"?version={version_installee}"
        return self._appel("GET", chemin).get("ordre")

    def rapport(self, ordre_id, statut, etape, journal="", version=""):
        """Vrai si le central a pris le rapport, faux s'il dit d'arrêter (ordre annulé).
        Lève en cas de panne réseau : l'appelant décide alors de garder le rapport."""
        try:
            self._appel("POST", f"/api/satellites/{self.satellite}/rapport-mise-a-jour/", {
                "ordre": ordre_id, "statut": statut, "etape": etape,
                "journal": journal[-TAILLE_JOURNAL:], "version": version,
            })
            return True
        except urllib.error.HTTPError as erreur:
            if erreur.code in (404, 409):
                return False
            raise


class Machine:
    """Tout ce que l'agent fait SUR la machine. À part pour être remplacé dans les tests."""

    def __init__(self, repertoire=REPERTOIRE):
        self.satellite = Path(repertoire)
        self.journal = []

    # ── exécution ──────────────────────────────────────────────────────────────────────────
    def lancer(self, commande, cwd=None, delai=600, entree=None):
        """Lance une commande, garde sa sortie dans le journal, renvoie `(code, sortie)`."""
        self.journal.append("$ " + " ".join(str(c) for c in commande))
        try:
            resultat = subprocess.run(
                [str(c) for c in commande], cwd=str(cwd or self.satellite),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=delai,
                stdin=subprocess.DEVNULL if entree is None else None, input=entree,
                check=False)
            sortie = resultat.stdout.decode(errors="replace")
            code = resultat.returncode
        except subprocess.TimeoutExpired:
            sortie, code = f"(arrêtée après {delai} s sans avoir fini)", 124
        except OSError as erreur:
            sortie, code = str(erreur), 127
        if sortie.strip():
            self.journal.append(sortie.strip()[-6000:])
        return code, sortie

    def texte_du_journal(self):
        return "\n".join(self.journal)[-TAILLE_JOURNAL:]

    # ── dépôt ──────────────────────────────────────────────────────────────────────────────
    def git(self, *arguments, delai=600):
        return self.lancer(["git", "-C", self.depot, *arguments], delai=delai)

    @property
    def depot(self):
        return self.satellite.parent

    def commit_installe(self):
        resultat = subprocess.run(
            ["git", "-C", str(self.depot), "rev-parse", "HEAD"],
            capture_output=True, check=False)
        return resultat.stdout.decode().strip() if resultat.returncode == 0 else ""

    def profil(self):
        try:
            return (self.satellite / ".profil").read_text(encoding="utf-8").strip() or "gw"
        except OSError:
            return "gw"

    def espace_libre_go(self):
        return shutil.disk_usage(str(self.satellite)).free / 1024 ** 3

    def compose(self, *arguments, delai=600):
        return self.lancer(["docker", "compose", "--profile", self.profil(), *arguments],
                           delai=delai)

    # ── sauvegarde ─────────────────────────────────────────────────────────────────────────
    def sauvegarder_la_base(self, env, commit):
        """`pg_dump` compressé de la base locale, lisible par le seul propriétaire.

        Une migration ne se défait pas : c'est cette sauvegarde, et elle seule, qui permet de
        revenir en arrière. Elle n'est pas plus exposée que la base elle-même — même disque,
        mêmes champs sensibles déjà chiffrés par l'application."""
        dossier = self.satellite / "sauvegardes"
        dossier.mkdir(mode=0o700, exist_ok=True)
        cible = dossier / f"avant-{commit[:10]}-{time.strftime('%Y%m%d-%H%M%S')}.sql.gz"
        self.journal.append(f"$ pg_dump de la base locale vers {cible.name}")
        try:
            processus = subprocess.Popen(
                ["docker", "compose", "--profile", "full", "exec", "-T", "db",
                 "pg_dump", "-U", env.get("DB_USER", "assista"), "assista-db"],
                cwd=str(self.satellite), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL)
        except OSError as erreur:
            raise Echec(f"Sauvegarde impossible ({erreur}). Rien n'a été modifié.") from None
        descripteur = os.open(str(cible), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        taille = 0
        with os.fdopen(descripteur, "wb") as brut, gzip.GzipFile(fileobj=brut, mode="wb") as sortie:
            for bloc in iter(lambda: processus.stdout.read(1 << 20), b""):
                sortie.write(bloc)
                taille += len(bloc)
        erreurs = processus.stderr.read().decode(errors="replace")
        if processus.wait() != 0 or taille == 0:
            cible.unlink(missing_ok=True)
            self.journal.append(erreurs.strip()[-2000:])
            raise Echec("La sauvegarde de la base a échoué : la mise à jour n'est pas "
                        "lancée. Rien n'a été modifié.")
        anciennes = sorted(dossier.glob("avant-*.sql.gz"), key=lambda f: f.stat().st_mtime)
        for fichier in anciennes[:-SAUVEGARDES_GARDEES]:
            fichier.unlink(missing_ok=True)
        return cible

    # ── santé ──────────────────────────────────────────────────────────────────────────────
    def services_en_boucle(self):
        """Les conteneurs qui redémarrent sans arrêt. Hors journal : appelé toutes les quinze
        secondes pendant l'attente, il le noierait."""
        try:
            resultat = subprocess.run(
                ["docker", "compose", "--profile", self.profil(), "ps",
                 "--status", "restarting", "-q"],
                cwd=str(self.satellite), capture_output=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return bool(resultat.stdout.strip())

    def site_local_repond(self, env):
        """`(vrai, "")` si le site local répond, sinon `(faux, pourquoi)`. Un refus (403 hors
        réseau privé, 401…) prouve qu'il répond : seule une erreur 5xx ou un silence compte."""
        port = env.get("WEB_PORT") or "80"
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/sonde/", timeout=10) as reponse:
                return reponse.status < 500, f"le site local répond {reponse.status}"
        except urllib.error.HTTPError as erreur:
            return erreur.code < 500, f"le site local répond {erreur.code}"
        except (urllib.error.URLError, OSError) as erreur:
            return False, f"le site local ne répond pas ({erreur})"

    def en_bonne_sante(self, env, attente=ATTENTE_SANTE_S, pause=time.sleep):
        """Après le redémarrage : aucun service en boucle de redémarrage, et — profil complet —
        le site local qui répond. Renvoie `(ok, explication)`."""
        fin = time.time() + attente
        while True:
            if self.services_en_boucle():
                explication = "un service redémarre en boucle"
            elif self.profil() != "full":
                return True, ""
            else:
                ok, explication = self.site_local_repond(env)
                if ok:
                    return True, ""
            if time.time() >= fin:
                return False, explication
            pause(15)


def appliquer(ordre, central, machine, env, fichier_cle):
    """Exécute un ordre. Renvoie `(statut, etape, version)` — ne lève jamais.

    Chaque refus dit s'il reste quelque chose de modifié : c'est la première question qu'on
    se pose en lisant un échec depuis le central."""
    commit, identifiant = ordre.get("commit", ""), ordre.get("id", "")

    def etape(texte):
        machine.journal.append(f"── {texte}")
        try:
            central.rapport(identifiant, "EN_COURS", texte, machine.texte_du_journal())
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            pass   # le central peut être injoignable pendant le redémarrage : on continue

    avant = machine.commit_installe()
    try:
        # 1. La signature, AVANT tout — y compris avant de dire au central qu'on s'en occupe.
        verifier_signature(commit, ordre.get("signature", ""), fichier_cle)

        # 2. Prise en charge. Un refus = ordre annulé entre-temps : on ne fait rien.
        machine.journal.append("── Vérification")
        if not central.rapport(identifiant, "EN_COURS", "Vérification"):
            return None

        if avant == commit:
            return "REUSSIE", "Déjà sur cette version.", commit

        code, modifies = machine.git("status", "--porcelain", "--untracked-files=no")
        if code != 0:
            raise Echec("Dépôt illisible (git status). Rien n'a été modifié.")
        if modifies.strip():
            raise Echec("Des fichiers du dépôt ont été modifiés sur place : la mise à jour "
                        "les écraserait. Rien n'a été modifié. Sur place : git status")
        if machine.espace_libre_go() < ESPACE_LIBRE_MIN_GO:
            raise Echec(f"Moins de {ESPACE_LIBRE_MIN_GO} Go libres sur le disque : la "
                        "construction risquerait de le remplir. Rien n'a été modifié.")

        etape("Récupération du code")
        if machine.git("fetch", "--quiet", "origin")[0] != 0:
            raise Echec("Récupération du code impossible (git fetch). Rien n'a été modifié.")
        if machine.git("cat-file", "-e", f"{commit}^{{commit}}")[0] != 0:
            raise Echec("Cette version n'existe pas dans le dépôt (pas encore poussée ?). "
                        "Rien n'a été modifié.")
        if machine.git("merge-base", "--is-ancestor", "HEAD", commit)[0] != 0:
            raise Echec("Cette version n'est pas une suite de celle installée : retour en "
                        "arrière refusé. Rien n'a été modifié.")

        if machine.profil() == "full":
            etape("Sauvegarde de la base")
            sauvegarde = machine.sauvegarder_la_base(env, commit)
            machine.journal.append(f"Sauvegarde : {sauvegarde}")

        if machine.git("merge", "--ff-only", commit)[0] != 0:
            raise Echec("Le code n'a pas pu être avancé (git merge --ff-only). "
                        "Rien n'a été modifié.")

        etape("Construction (peut prendre longtemps)")
        if machine.compose("build", delai=DUREE_MAX_CONSTRUCTION_S)[0] != 0:
            # L'arbre était propre (vérifié plus haut) : revenir au commit d'avant ne perd rien.
            machine.git("reset", "--hard", avant)
            raise Echec("La construction a échoué. Le code a été remis à la version "
                        "précédente, qui n'a pas cessé de tourner.")

        etape("Redémarrage")
        code, _ = machine.lancer([machine.satellite / "installer.sh", "demarrer"],
                                 delai=DUREE_MAX_DEMARRAGE_S)
        if code != 0:
            raise Echec("Le redémarrage a échoué APRÈS la construction : le satellite peut "
                        "être en partie sur la nouvelle version. À voir sur place "
                        "(./installer.sh demarrer). La sauvegarde de la base est dans "
                        "satellite/sauvegardes/.")

        etape("Vérification du redémarrage")
        ok, explication = machine.en_bonne_sante(lire_env(machine.satellite / ".env"))
        if not ok:
            raise Echec(f"Le satellite a redémarré mais ne va pas bien : {explication}. "
                        "À voir sur place. La sauvegarde de la base est dans "
                        "satellite/sauvegardes/.")
        return "REUSSIE", "Mise à jour terminée.", commit
    except Echec as echec:
        machine.journal.append(f"ÉCHEC : {echec}")
        return "ECHOUEE", str(echec), machine.commit_installe() or avant
    except Exception as erreur:  # noqa: BLE001 — un agent qui meurt sans rien dire est pire
        machine.journal.append(f"ERREUR INATTENDUE : {erreur!r}")
        return "ECHOUEE", f"Erreur inattendue de l'agent : {erreur}", \
            machine.commit_installe() or avant


def _lire_json(fichier):
    try:
        return json.loads(Path(fichier).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ecrire_json(fichier, contenu):
    """Écriture atomique, lisible par le seul propriétaire (le journal peut citer la machine)."""
    temporaire = str(fichier) + ".tmp"
    descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as sortie:
        json.dump(contenu, sortie)
    os.replace(temporaire, str(fichier))


def passage(central, machine, env, fichier_cle, fichier_rapport):
    """Un passage de l'agent. Renvoie un mot pour le journal systemd."""
    # Un compte rendu final resté sur les bras (central injoignable à la fin d'une mise à
    # jour) part d'abord : sans lui, le central croirait la mise à jour perdue.
    en_attente = _lire_json(fichier_rapport)
    if en_attente:
        central.rapport(en_attente["ordre"], en_attente["statut"], en_attente["etape"],
                        en_attente.get("journal", ""), en_attente.get("version", ""))
        Path(fichier_rapport).unlink(missing_ok=True)

    ordre = central.ordre(machine.commit_installe())
    if not ordre:
        return "rien à faire"
    resultat = appliquer(ordre, central, machine, env, fichier_cle)
    if resultat is None:
        return "ordre annulé"
    statut, etape, version = resultat
    final = {"ordre": ordre.get("id", ""), "statut": statut, "etape": etape,
             "journal": machine.texte_du_journal(), "version": version}
    # Écrit AVANT l'envoi : si la machine s'arrête entre les deux, le compte rendu survit.
    _ecrire_json(fichier_rapport, final)
    central.rapport(final["ordre"], statut, etape, final["journal"], version)
    Path(fichier_rapport).unlink(missing_ok=True)
    return f"{statut} — {etape}"


def principal():
    env = lire_env(REPERTOIRE / ".env")
    central = Central(env)
    if not central.configure:
        print("Satellite pas encore enrôlé : rien à faire.")
        return 0
    # Un seul agent à la fois : une mise à jour dure plus longtemps que l'intervalle du
    # minuteur, et deux constructions simultanées se détruiraient l'une l'autre.
    verrou = open(REPERTOIRE / ".maj-verrou", "w", encoding="utf-8")  # noqa: SIM115
    try:
        fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Une mise à jour est déjà en cours.")
        return 0
    try:
        print(passage(central, Machine(), env, REPERTOIRE / ".cle-signature.pub",
                      REPERTOIRE / ".maj-rapport.json"))
        return 0
    except (urllib.error.URLError, OSError, ValueError, KeyError) as erreur:
        # Central injoignable : ce n'est pas une panne, c'est la vie d'un satellite.
        print(f"Central injoignable ou réponse illisible : {erreur}")
        return 0


if __name__ == "__main__":
    sys.exit(principal())
