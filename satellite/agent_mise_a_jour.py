#!/usr/bin/env python3
"""Agent de mise à jour du satellite : applique les mises à jour ordonnées par le central.

Demande de Sylvain du 14/11/2026. Lancé toutes les deux minutes par systemd
(`assista-satellite-maj.timer`, installé par `installer.sh`), SUR LA MACHINE et non dans un
conteneur : une mise à jour reconstruit et remplace les conteneurs, et un conteneur qui se
mettrait à jour lui-même se couperait au milieu du travail.

**Il ne sait faire que trois choses**, et le central ne lui transmet jamais de commande :

- **mettre à jour** : amener le dépôt à un commit précis, reconstruire, redémarrer — sur un
  numéro de commit et sa signature ;
- **regarder** : diagnostic, journaux de tous les services, état des migrations, état de la
  machine, du réseau et du dépôt. Rien de cela ne change la machine ;
- **agir** : redémarrer les services, appliquer les migrations, reconstruire, libérer de la
  place, sauvegarder la base — ce que ferait quelqu'un sur place, et rien d'autre.

Regarder et agir (17/11/2026) sont des mots d'une liste fermée (`ACTIONS`), sans paramètre : un
satellite a fini une mise à jour « à jour et en échec », son serveur local ne redémarrait pas,
et il a fallu téléphoner pour apprendre pourquoi. Elles ne sont pas signées : elles ne font
entrer aucun code, et ce qu'elles renvoient va au central, qui reçoit déjà les données du
satellite.

Avant une mise à jour, et avant de toucher à quoi que ce soit, il vérifie que :

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
#: Ce que le diagnostic relève : les derniers messages de chaque service en panne.
DIAGNOSTIC_LIGNES = 60
DIAGNOSTIC_SERVICES_MAX = 6
#: Ce que l'agent note avant chaque mise à jour, pour pouvoir en revenir.
FICHIER_PRECEDENTE = ".maj-precedente.json"
#: Ce que fait l'agent, pour l'écran d'état de la machine (ecran_etat.py) : dernier passage,
#: opération en cours, dernier résultat. Aucun journal ni secret : de quoi lire d'un coup d'œil.
FICHIER_ETAT_AGENT = ".etat-agent.json"
#: Par service, pour l'ordre « journaux » : tous les services, donc moins de lignes chacun.
JOURNAUX_LIGNES = 40
#: Ce qu'on garde de la sortie des commandes, par rapport envoyé. La FIN : l'erreur y est.
TAILLE_JOURNAL = 40_000


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

    def _appel(self, methode, chemin, corps=None, authentifie=True, _renouvele=False):
        entetes = {"Content-Type": "application/json", "User-Agent": "satellite-agent-maj"}
        if authentifie:
            entetes["Authorization"] = f"Bearer {self._jeton_d_acces()}"
        requete = urllib.request.Request(
            self.url + chemin, method=methode, headers=entetes,
            data=json.dumps(corps).encode() if corps is not None else None)
        try:
            with self._ouvrir(requete, timeout=30) as reponse:
                return json.loads(reponse.read().decode() or "{}")
        except urllib.error.HTTPError as erreur:
            # Jeton expiré pendant une longue construction (vu le 18/11/2026 : 3 h, compte
            # rendu final refusé en 401) : on en redemande un, une seule fois.
            if erreur.code == 401 and authentifie and not _renouvele:
                self._jeton = None
                return self._appel(methode, chemin, corps, authentifie, _renouvele=True)
            raise

    def _jeton_d_acces(self):
        if self._jeton is None:
            self._jeton = self._appel(
                "POST", "/api/token/",
                {"email": self.email, "password": self.mot_de_passe},
                authentifie=False)["access"]
        return self._jeton

    def ordre(self, version_installee):
        """L'ordre en attente, s'il y en a un. Au passage l'agent dit ce qu'il sait faire :
        sans cela le central proposerait à un agent ancien un ordre qu'il ne connaît pas, et
        celui-ci le prendrait pour une mise à jour sans numéro de version (17/11/2026)."""
        chemin = f"/api/satellites/{self.satellite}/ordre-mise-a-jour/?actions=" + ",".join(sorted(ACTIONS))
        if version_installee:
            chemin += f"&version={version_installee}"
        return self._appel("GET", chemin).get("ordre")

    def rapport(self, ordre_id, statut, etape, journal="", version=""):
        """Vrai si le central a pris le rapport, faux s'il dit d'arrêter (ordre annulé).
        Lève en cas de panne réseau : l'appelant décide alors de garder le rapport."""
        chemin = f"/api/satellites/{self.satellite}/rapport-mise-a-jour/"
        corps = {"ordre": ordre_id, "statut": statut, "etape": etape, "version": version}
        try:
            self._appel("POST", chemin, {**corps, "journal": journal[-TAILLE_JOURNAL:]})
            return True
        except urllib.error.HTTPError as erreur:
            if erreur.code in (404, 409):
                return False
            if erreur.code not in (400, 403, 413):
                raise
            code = erreur.code
        # REFUSÉ, pas injoignable : c'est le contenu qui ne passe pas. Constaté le 17/11/2026 :
        # le pare-feu du central prenait le journal — des lignes de commande et des traces —
        # pour une attaque, et répondait 403. Le compte rendu final restait donc sur les bras,
        # repartait à chaque passage, et l'agent ne revenait plus jamais chercher d'ordre.
        #
        # On renvoie alors l'essentiel — le statut et l'étape — SANS le journal, qui reste
        # lisible sur le satellite (`journalctl -u assista-satellite-maj`). On ne cherche pas à
        # le faire passer autrement : c'est au central de décider ce que son pare-feu laisse
        # entrer.
        try:
            self._appel("POST", chemin, {
                **corps,
                "journal": f"Journal non transmis : le central l'a refuse (code {code}). "
                           "Il est reste sur le satellite."})
            return True
        except urllib.error.HTTPError as erreur:
            if erreur.code in (404, 409):
                return False
            raise


class Machine:
    """Tout ce que l'agent fait SUR la machine. À part pour être remplacé dans les tests."""

    #: Appelé avec les minutes écoulées, toutes les INTERVALLE_BATTEMENT_S, pendant une
    #: commande longue (la construction) : le central sait alors que la machine travaille,
    #: et dans quel état elle est, au lieu de trois heures de silence (18/11/2026).
    battement = None
    INTERVALLE_BATTEMENT_S = 600

    def __init__(self, repertoire=REPERTOIRE):
        self.satellite = Path(repertoire)
        self.journal = []

    # ── exécution ──────────────────────────────────────────────────────────────────────────
    def lancer(self, commande, cwd=None, delai=600, entree=None):
        """Lance une commande, garde sa sortie dans le journal, renvoie `(code, sortie)`."""
        self.journal.append("$ " + " ".join(str(c) for c in commande))
        if self.battement is not None and entree is None:
            return self._lancer_en_battant(commande, cwd, delai)
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

    def _lancer_en_battant(self, commande, cwd, delai):
        debut = time.monotonic()
        try:
            processus = subprocess.Popen(
                [str(c) for c in commande], cwd=str(cwd or self.satellite),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        except OSError as erreur:
            self.journal.append(str(erreur))
            return 127, str(erreur)
        while True:
            reste = delai - (time.monotonic() - debut)
            if reste <= 0:
                processus.kill()
                processus.communicate()
                sortie, code = f"(arrêtée après {delai} s sans avoir fini)", 124
                break
            try:
                brut, _ = processus.communicate(timeout=min(self.INTERVALLE_BATTEMENT_S, reste))
                sortie, code = brut.decode(errors="replace"), processus.returncode
                break
            except subprocess.TimeoutExpired:
                # communicate() peut être rappelé sans perdre la sortie déjà lue.
                try:
                    self.battement(int((time.monotonic() - debut) // 60))
                except Exception:  # noqa: BLE001 -- un compte rendu manqué n'arrête rien
                    pass
        if sortie.strip():
            self.journal.append(sortie.strip()[-6000:])
        return code, sortie

    #: Les clés de `.env` dont la valeur ne doit jamais partir dans un journal.
    CLES_SECRETES = ("PASSWORD", "PASS", "SECRET", "KEY", "CLE", "TOKEN", "JETON", "MDP")

    def secrets(self):
        """Les valeurs secrètes de `.env`, les plus longues d'abord."""
        valeurs = {v for c, v in lire_env(self.satellite / ".env").items()
                   if len(v) >= 6 and any(m in c.upper() for m in self.CLES_SECRETES)}
        return sorted(valeurs, key=len, reverse=True)

    def texte_du_journal(self):
        """Le journal tel qu'il part au central : sans aucun secret de la machine. Il contient
        la sortie de commandes et les messages des services — le 17/11/2026 le mot de passe de
        l'administrateur local s'y est retrouvé, affiché par `installer.sh`."""
        texte = "\n".join(self.journal)
        for secret in self.secrets():
            texte = texte.replace(secret, "•••")
        return texte[-TAILLE_JOURNAL:]

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

    # ── restauration ───────────────────────────────────────────────────────────────────────
    BASE = "assista-db"

    def dans_la_base(self, *commande):
        """Le début d'une commande lancée DANS le conteneur de la base. À part pour être
        remplacé dans les essais, qui parlent à un vrai PostgreSQL jetable."""
        return ["docker", "compose", "--profile", "full", "exec", "-T", "db", *commande]

    def _sql(self, env, base, requete):
        return self.lancer(self.dans_la_base(
            "psql", "-U", env.get("DB_USER", "assista"), "-d", base, "-v", "ON_ERROR_STOP=1",
            "-q", "-c", requete), delai=600)

    def restaurer_la_base(self, env, sauvegarde, horodatage=None):
        """Remet la base dans l'état de `sauvegarde`, sans rien perdre en route.

        La sauvegarde est chargée dans une base NEUVE, à côté. Tant que ce chargement n'est pas
        fini et réussi, la base en service n'est pas touchée : une restauration interrompue ne
        laisse donc jamais une base à moitié écrite. Ensuite seulement les deux sont échangées
        par renommage, et la base d'avant l'échange est gardée sous un autre nom — c'est ce qui
        permet de revenir sur un retour en arrière. Renvoie le nom sous lequel elle est gardée."""
        utilisateur = env.get("DB_USER", "assista")
        neuve = f"{self.BASE}_restauration"
        gardee = f"{self.BASE}_avant_{horodatage or time.strftime('%Y%m%d_%H%M%S')}"
        sauvegarde = Path(sauvegarde)
        if not sauvegarde.is_file():
            raise Echec(f"La sauvegarde {sauvegarde.name} n'est plus sur le satellite. Rien n'a été modifié.")

        self._sql(env, "postgres", f'DROP DATABASE IF EXISTS "{neuve}"')
        if self._sql(env, "postgres", f'CREATE DATABASE "{neuve}" OWNER "{utilisateur}"')[0] != 0:
            raise Echec("La base de restauration n'a pas pu être créée. Rien n'a été modifié.")

        self.journal.append(f"$ chargement de {sauvegarde.name} dans {neuve}")
        try:
            processus = subprocess.Popen(
                self.dans_la_base("psql", "-U", utilisateur, "-d", neuve, "-v", "ON_ERROR_STOP=1", "-q"),
                cwd=str(self.satellite), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE)
            with gzip.open(str(sauvegarde), "rb") as entree:
                shutil.copyfileobj(entree, processus.stdin, 1 << 20)
            processus.stdin.close()
            erreurs = processus.stderr.read().decode(errors="replace")
            code = processus.wait()
        except (OSError, EOFError) as erreur:
            erreurs, code = str(erreur), 1
        if code != 0:
            self.journal.append(erreurs.strip()[-2000:])
            self._sql(env, "postgres", f'DROP DATABASE IF EXISTS "{neuve}"')
            raise Echec("La sauvegarde n'a pas pu être rechargée : la base en service n'a pas "
                        "été touchée.")

        # L'échange. Plus personne ne doit être connecté à la base en service : les services
        # sont arrêtés par l'appelant, on coupe ce qui resterait.
        self._sql(env, "postgres",
                  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                  f"WHERE datname IN ('{self.BASE}', '{neuve}') AND pid <> pg_backend_pid()")
        if self._sql(env, "postgres", f'ALTER DATABASE "{self.BASE}" RENAME TO "{gardee}"')[0] != 0:
            self._sql(env, "postgres", f'DROP DATABASE IF EXISTS "{neuve}"')
            raise Echec("La base en service n'a pas pu être mise de côté (encore utilisée ?). "
                        "Elle n'a pas été modifiée.")
        if self._sql(env, "postgres", f'ALTER DATABASE "{neuve}" RENAME TO "{self.BASE}"')[0] != 0:
            # On défait : la base d'origine reprend son nom.
            self._sql(env, "postgres", f'ALTER DATABASE "{gardee}" RENAME TO "{self.BASE}"')
            raise Echec("L'échange des bases a échoué : la base d'origine a été remise en place.")
        return gardee

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

    # ── diagnostic ─────────────────────────────────────────────────────────────────────────
    def diagnostiquer(self):
        """Ajoute au journal de quoi comprendre une panne sans se déplacer : l'état de chaque
        service, la place libre, et les derniers messages de ceux qui ne vont pas bien — et
        toujours ceux du serveur local, parce que c'est lui qui applique les migrations.

        Ne change rien à la machine. Ne lève jamais : un diagnostic qui échoue ne doit pas
        masquer la panne qu'il venait décrire."""
        try:
            self.journal.append("── Diagnostic")
            self.journal.append(f"Version du code : {self.commit_installe() or 'inconnue'}")
            self.journal.append(f"Place libre : {self.espace_libre_go():.1f} Go")
            code, sortie = self.compose(
                "ps", "--all", "--format", "{{.Service}}\t{{.State}}\t{{.Health}}\t{{.Status}}", delai=120)
            a_lire = ["backend"]
            if code == 0:
                for ligne in sortie.splitlines():
                    champs = ligne.split("\t")
                    if len(champs) < 3:
                        continue
                    service, etat, sante = champs[0], champs[1], champs[2]
                    # Un service à exécution unique qui s'est terminé normalement n'est pas en panne.
                    en_panne = etat in ("restarting", "dead", "created") or sante == "unhealthy" \
                        or (etat == "exited" and "Exited (0)" not in ligne)
                    if en_panne and service not in a_lire:
                        a_lire.append(service)
            for service in a_lire[:DIAGNOSTIC_SERVICES_MAX]:
                self.compose("logs", "--no-color", "--tail", str(DIAGNOSTIC_LIGNES), service, delai=120)
        except Exception as erreur:  # noqa: BLE001
            self.journal.append(f"(diagnostic interrompu : {erreur!r})")

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


def etat_de_la_machine(proc="/proc"):
    """« charge 3.1 ; mémoire disponible 210 Mo ; swap utilisé 1.8 Go sur 2.0 » : de quoi voir
    une machine qui sature pendant une construction. Lu dans /proc, rien n'est lancé."""
    morceaux = []
    try:
        morceaux.append("charge " + open(f"{proc}/loadavg", encoding="utf-8").read().split()[0])
    except (OSError, IndexError):
        pass
    try:
        info = {}
        for ligne in open(f"{proc}/meminfo", encoding="utf-8"):
            cle, _, valeur = ligne.partition(":")
            info[cle] = int(valeur.split()[0])       # en kio
        morceaux.append(f"mémoire disponible {info['MemAvailable'] // 1024} Mo")
        if info.get("SwapTotal"):
            utilise = (info["SwapTotal"] - info.get("SwapFree", 0)) / 1048576
            morceaux.append(f"swap utilisé {utilise:.1f} Go sur {info['SwapTotal'] / 1048576:.1f}")
    except (OSError, KeyError, ValueError, IndexError):
        pass
    return " ; ".join(morceaux) or "état de la machine illisible"


def appliquer(ordre, central, machine, env, fichier_cle):
    """Exécute un ordre. Renvoie `(statut, etape, version)` — ne lève jamais.

    Chaque refus dit s'il reste quelque chose de modifié : c'est la première question qu'on
    se pose en lisant un échec depuis le central."""
    commit, identifiant = ordre.get("commit", ""), ordre.get("id", "")

    debut = time.time()

    def etape(texte):
        machine.journal.append(f"── {texte}")
        noter_etat(machine.satellite, en_cours={"version": commit[:10], "etape": texte, "depuis": debut})
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

        sauvegarde = None
        if machine.profil() == "full":
            etape("Sauvegarde de la base")
            sauvegarde = machine.sauvegarder_la_base(env, commit)
            machine.journal.append(f"Sauvegarde : {sauvegarde}")
        # De quoi revenir en arrière : la version d'avant, et la sauvegarde qui va avec. Écrit
        # par l'agent, ici, au moment où il le fait — le central ne choisit jamais vers quoi
        # un satellite revient.
        _ecrire_json(machine.satellite / FICHIER_PRECEDENTE, {
            "commit": avant, "vers": commit, "sauvegarde": str(sauvegarde) if sauvegarde else "",
            "date": time.strftime("%Y-%m-%d %H:%M:%S")})

        if machine.git("merge", "--ff-only", commit)[0] != 0:
            raise Echec("Le code n'a pas pu être avancé (git merge --ff-only). "
                        "Rien n'a été modifié.")

        etape("Construction (peut prendre longtemps)")

        def battement(minutes):
            noter_etat(machine.satellite, en_cours={
                "version": commit[:10], "etape": f"Construction en cours depuis {minutes} min", "depuis": debut})
            central.rapport(identifiant, "EN_COURS",
                            f"Construction en cours depuis {minutes} min — {etat_de_la_machine()}",
                            machine.texte_du_journal())
        machine.battement = battement
        try:
            construite = machine.compose("build", delai=DUREE_MAX_CONSTRUCTION_S)[0] == 0
        finally:
            machine.battement = None
        if not construite:
            # L'arbre était propre (vérifié plus haut) : revenir au commit d'avant ne perd rien.
            machine.git("reset", "--hard", avant)
            raise Echec("La construction a échoué. Le code a été remis à la version "
                        "précédente, qui n'a pas cessé de tourner.")

        etape("Redémarrage")
        code, _ = machine.lancer([machine.satellite / "installer.sh", "demarrer"],
                                 delai=DUREE_MAX_DEMARRAGE_S)
        if code != 0:
            # Le pourquoi part avec l'échec : sans lui, le central ne sait que « ça n'a pas
            # redémarré », et il faut téléphoner.
            machine.diagnostiquer()
            raise Echec("Le redémarrage a échoué APRÈS la construction : le satellite peut "
                        "être en partie sur la nouvelle version. Le diagnostic est à la fin "
                        "du journal. La sauvegarde de la base est dans satellite/sauvegardes/.")

        etape("Vérification du redémarrage")
        ok, explication = machine.en_bonne_sante(lire_env(machine.satellite / ".env"))
        if not ok:
            machine.diagnostiquer()
            raise Echec(f"Le satellite a redémarré mais ne va pas bien : {explication}. "
                        "Le diagnostic est à la fin du journal. La sauvegarde de la base est "
                        "dans satellite/sauvegardes/.")
        return "REUSSIE", "Mise à jour terminée.", commit
    except Echec as echec:
        machine.journal.append(f"ÉCHEC : {echec}")
        return "ECHOUEE", str(echec), machine.commit_installe() or avant
    except Exception as erreur:  # noqa: BLE001 — un agent qui meurt sans rien dire est pire
        machine.journal.append(f"ERREUR INATTENDUE : {erreur!r}")
        return "ECHOUEE", f"Erreur inattendue de l'agent : {erreur}", \
            machine.commit_installe() or avant


# ── Les ordres autres qu'une mise à jour ───────────────────────────────────────────────────
# Chacun rend le mot de la fin, ou lève `Echec`. Aucun ne prend de paramètre : ce que le
# central peut faire faire à un satellite se lit en entier dans ce fichier.

def _django(machine, *arguments, delai=1800):
    """Une commande `manage.py` dans l'image du serveur, SANS son point d'entrée — celui-ci
    applique les migrations, ce qu'on ne veut pas déclencher en demandant leur état — et sans
    dépendre de ce que le serveur tourne : c'est justement quand il ne démarre pas qu'on en a
    besoin."""
    if machine.profil() != "full":
        raise Echec("Ce satellite est une passerelle : il n'a ni base ni serveur local.")
    return machine.compose("run", "--rm", "--no-deps", "-T", "--entrypoint", "python",
                           "backend", "manage.py", *arguments, delai=delai)


def _redemarrer(machine, env):
    code, _ = machine.lancer([machine.satellite / "installer.sh", "demarrer"],
                             delai=DUREE_MAX_DEMARRAGE_S)
    ok, explication = (False, "le démarrage a rendu une erreur") if code != 0 \
        else machine.en_bonne_sante(lire_env(machine.satellite / ".env"))
    machine.diagnostiquer()
    if not ok:
        raise Echec(f"Les services ne sont pas repartis : {explication}. "
                    "Le diagnostic est à la fin du journal.")


def action_diagnostic(machine, env):
    machine.diagnostiquer()
    return "Diagnostic relevé : voir le journal."


def action_journaux(machine, env):
    """Les derniers messages de TOUS les services, pas seulement de ceux qui sont en panne :
    un service « en marche » peut tourner à vide."""
    code, sortie = machine.compose("ps", "--all", "--format", "{{.Service}}", delai=120)
    services = sorted({s.strip() for s in sortie.splitlines() if s.strip()}) if code == 0 else []
    if not services:
        raise Echec("Aucun service à lire (docker compose ps ne rend rien).")
    for service in services:
        machine.compose("logs", "--no-color", "--tail", str(JOURNAUX_LIGNES), service, delai=120)
    return f"Journaux de {len(services)} services relevés : voir le journal."


def action_migrations(machine, env):
    """Où en est la base : ce qui est appliqué, ce qui attend, et si le code démarre."""
    machine.journal.append("── Migrations en attente")
    code, _ = _django(machine, "showmigrations", "--plan", delai=600)
    machine.journal.append("── Vérification du code")
    _django(machine, "check", delai=600)
    if code != 0:
        raise Echec("L'état des migrations n'a pas pu être lu : voir le journal.")
    return "État des migrations relevé : « [ ] » marque celles qui attendent."


def action_migrer(machine, env):
    """Applique les migrations en attente, une par une, après avoir sauvegardé la base. Le
    journal montre chacune : c'est là qu'on lit laquelle a échoué, et pourquoi."""
    if machine.profil() != "full":
        raise Echec("Ce satellite est une passerelle : il n'a ni base ni serveur local.")
    machine.journal.append("── Sauvegarde de la base")
    sauvegarde = machine.sauvegarder_la_base(env, machine.commit_installe() or "inconnu")
    machine.journal.append(f"Sauvegarde : {sauvegarde}")
    machine.journal.append("── Migrations")
    code, _ = _django(machine, "migrate", "--noinput", "-v", "1")
    if code != 0:
        raise Echec("Une migration a échoué : la dernière ligne « Applying » du journal dit "
                    "laquelle. La base a été sauvegardée avant, dans satellite/sauvegardes/.")
    return "Migrations appliquées. Redémarrez les services pour qu'ils les prennent."


def action_redemarrage(machine, env):
    machine.journal.append("── Redémarrage des services")
    _redemarrer(machine, env)
    return "Services redémarrés."


def action_reconstruction(machine, env):
    """Reconstruit les images depuis le code installé, puis redémarre : pour une image abîmée
    ou une construction interrompue."""
    if machine.espace_libre_go() < ESPACE_LIBRE_MIN_GO:
        raise Echec(f"Moins de {ESPACE_LIBRE_MIN_GO} Go libres : libérez d'abord de la place.")
    machine.journal.append("── Construction")
    if machine.compose("build", delai=DUREE_MAX_CONSTRUCTION_S)[0] != 0:
        raise Echec("La construction a échoué : voir le journal. Les services en place n'ont pas été touchés.")
    machine.journal.append("── Redémarrage des services")
    _redemarrer(machine, env)
    return "Images reconstruites, services redémarrés."


def action_systeme(machine, env):
    """La machine elle-même : place, mémoire, charge, température, ce que Docker occupe."""
    machine.journal.append("── Machine")
    for commande in (["uptime"], ["df", "-h", "/"], ["free", "-m"], ["docker", "system", "df"],
                     ["vcgencmd", "measure_temp"], ["vcgencmd", "get_throttled"],
                     ["systemctl", "is-active", "assista-satellite-maj.timer"]):
        machine.lancer(commande, delai=60)
    return "État de la machine relevé : voir le journal."


def action_reseau(machine, env):
    """Ce que le satellite voit du réseau : son heure, ses adresses, et s'il joint le central."""
    machine.journal.append("── Réseau")
    for commande in (["date", "-u"], ["timedatectl", "show", "-p", "NTPSynchronized"],
                     ["ip", "-brief", "addr"], ["ip", "route"]):
        machine.lancer(commande, delai=60)
    central = (env.get("CENTRAL_URL") or "https://assista-crise.fr").rstrip("/")
    debut = time.time()
    try:
        with urllib.request.urlopen(central + "/api/sonde/", timeout=20) as reponse:
            verdict = f"répond {reponse.status}"
    except urllib.error.HTTPError as erreur:
        verdict = f"répond {erreur.code}"
    except (urllib.error.URLError, OSError) as erreur:
        verdict = f"injoignable ({erreur})"
    machine.journal.append(f"Central {central} : {verdict} en {time.time() - debut:.1f} s")
    return "État du réseau relevé : voir le journal."


def action_depot(machine, env):
    """Le code sur place : sa version, et ce qui y aurait été modifié à la main — la première
    cause d'une mise à jour refusée."""
    machine.journal.append("── Dépôt")
    machine.git("log", "-5", "--format=%h %ad %s", "--date=short")
    machine.git("status", "--short", "--branch")
    machine.git("diff", "--stat")
    return "État du dépôt relevé : voir le journal."


def action_nettoyage(machine, env):
    """Libère de la place sans rien retirer de ce qui sert : le cache de construction de plus
    d'un jour et les images orphelines. Ni conteneur, ni volume, ni sauvegarde."""
    avant = machine.espace_libre_go()
    machine.journal.append("── Nettoyage")
    machine.lancer(["docker", "builder", "prune", "-f", "--filter", "until=24h"], delai=1800)
    machine.lancer(["docker", "image", "prune", "-f"], delai=1800)
    apres = machine.espace_libre_go()
    machine.journal.append(f"Place libre : {avant:.1f} Go → {apres:.1f} Go")
    return f"{max(0.0, apres - avant):.1f} Go libérés ; {apres:.1f} Go libres."


def action_sauvegarde(machine, env):
    if machine.profil() != "full":
        raise Echec("Ce satellite est une passerelle : il n'a pas de base à sauvegarder.")
    sauvegarde = machine.sauvegarder_la_base(env, machine.commit_installe() or "inconnu")
    machine.journal.append(f"Sauvegarde : {sauvegarde}")
    return f"Base sauvegardée sur le satellite ({sauvegarde.name})."


def action_restauration(machine, env):
    """Revient à la version d'avant la dernière mise à jour : le code, et la base telle qu'elle
    était sauvegardée juste avant.

    Vers quoi on revient est noté par l'agent lui-même au moment de la mise à jour
    (`.maj-precedente.json`) ; l'ordre ne porte aucun paramètre. La base en service au moment
    du retour est gardée sous un autre nom : ce qui aurait été saisi depuis n'est pas détruit,
    seulement mis de côté."""
    precedente = _lire_json(machine.satellite / FICHIER_PRECEDENTE)
    if not precedente or not commit_valide(precedente.get("commit", "")):
        raise Echec("Cet agent n'a noté aucune mise à jour dont revenir (il ne le fait que "
                    "depuis sa version du 17/11/2026). Rien n'a été modifié.")
    commit = precedente["commit"]
    if machine.commit_installe() == commit:
        raise Echec("Le satellite est déjà sur la version d'avant la dernière mise à jour.")
    code, modifies = machine.git("status", "--porcelain", "--untracked-files=no")
    if code != 0 or modifies.strip():
        raise Echec("Des fichiers du dépôt ont été modifiés sur place : le retour les "
                    "écraserait. Rien n'a été modifié.")
    if machine.git("cat-file", "-e", f"{commit}^{{commit}}")[0] != 0:
        raise Echec("La version d'avant n'est plus dans le dépôt. Rien n'a été modifié.")
    if machine.espace_libre_go() < ESPACE_LIBRE_MIN_GO:
        raise Echec(f"Moins de {ESPACE_LIBRE_MIN_GO} Go libres : libérez d'abord de la place.")

    complet = machine.profil() == "full"
    if complet:
        if not precedente.get("sauvegarde"):
            raise Echec("Aucune sauvegarde n'accompagne cette mise à jour. Rien n'a été modifié.")
        # Tout sauf la base : plus personne ne doit y écrire pendant l'échange.
        machine.journal.append("── Arrêt des services")
        code, sortie = machine.compose("ps", "--services", delai=120)
        services = [s.strip() for s in sortie.splitlines() if s.strip() and s.strip() != "db"]
        if code == 0 and services:
            machine.compose("stop", *services, delai=600)
        machine.journal.append("── Restauration de la base")
        gardee = machine.restaurer_la_base(env, precedente["sauvegarde"])
        machine.journal.append(f"Base d'avant le retour gardée sous le nom : {gardee}")

    machine.journal.append("── Retour du code")
    if machine.git("reset", "--hard", commit)[0] != 0:
        raise Echec("Le code n'a pas pu être ramené à la version d'avant. La base, elle, a été "
                    "restaurée : relancez « Revenir à la version précédente ».")
    machine.journal.append("── Construction")
    if machine.compose("build", delai=DUREE_MAX_CONSTRUCTION_S)[0] != 0:
        raise Echec("La construction de la version d'avant a échoué : voir le journal.")
    machine.journal.append("── Redémarrage des services")
    _redemarrer(machine, env)
    # Ce retour est fait : on ne revient pas deux fois d'une même mise à jour.
    (machine.satellite / FICHIER_PRECEDENTE).unlink(missing_ok=True)
    return f"Revenu à la version {commit[:10]}, base restaurée." if complet \
        else f"Revenu à la version {commit[:10]}."


def action_bilan(machine, env):
    """Tout ce qu'il y a à regarder, en un seul ordre et un seul journal : pour quelqu'un qui
    dépanne à distance, six allers-retours de deux minutes sont six de trop.

    Du plus général au plus précis, parce que c'est la FIN du journal qui est gardée si la
    place manque : la machine, le réseau, le code, les migrations, puis les journaux des
    services et le diagnostic. Un relevé qui échoue n'empêche pas les suivants."""
    for titre, releve in (("MACHINE", action_systeme), ("RÉSEAU", action_reseau),
                          ("CODE INSTALLÉ", action_depot), ("MIGRATIONS", action_migrations),
                          ("JOURNAUX", action_journaux), ("DIAGNOSTIC", action_diagnostic)):
        machine.journal.append(f"════════ {titre} ════════")
        try:
            releve(machine, env)
        except Echec as echec:
            machine.journal.append(f"(relevé incomplet : {echec})")
        except Exception as erreur:  # noqa: BLE001
            machine.journal.append(f"(relevé interrompu : {erreur!r})")
    return "Bilan complet relevé : voir le journal."


#: LA liste. Tout autre mot est refusé. Doit rester identique à `ActionSatellite` côté central.
ACTIONS = {
    # regarder
    "BILAN": action_bilan,
    "DIAGNOSTIC": action_diagnostic,
    "JOURNAUX": action_journaux,
    "MIGRATIONS": action_migrations,
    "SYSTEME": action_systeme,
    "RESEAU": action_reseau,
    "DEPOT": action_depot,
    # agir
    "REDEMARRAGE": action_redemarrage,
    "MIGRER": action_migrer,
    "RECONSTRUCTION": action_reconstruction,
    "NETTOYAGE": action_nettoyage,
    "SAUVEGARDE": action_sauvegarde,
    "RESTAURATION": action_restauration,
}


def agir(ordre, central, machine, env):
    """Exécute un ordre qui n'est pas une mise à jour. Renvoie `(statut, etape, version)`, ou
    `None` si le central l'a annulé entre-temps. Ne lève jamais."""
    action, identifiant = ordre.get("action", ""), ordre.get("id", "")
    version = machine.commit_installe()
    try:
        if not central.rapport(identifiant, "EN_COURS", "Vérification"):
            return None
        if action not in ACTIONS:
            # Un mot que cet agent ne connaît pas : il ne devine pas, il refuse.
            return "ECHOUEE", f"Ordre inconnu de cet agent : {action!r}. Mettez d'abord le satellite à jour.", version
        return "REUSSIE", ACTIONS[action](machine, env), machine.commit_installe() or version
    except Echec as echec:
        machine.journal.append(f"ÉCHEC : {echec}")
        return "ECHOUEE", str(echec), version
    except Exception as erreur:  # noqa: BLE001 — un agent qui meurt sans rien dire est pire
        machine.journal.append(f"ERREUR INATTENDUE : {erreur!r}")
        return "ECHOUEE", f"Erreur inattendue de l'agent : {erreur}", version


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


def noter_etat(repertoire, **champs):
    """Complète `.etat-agent.json` ; une erreur d'écriture n'arrête jamais l'agent."""
    try:
        fichier = Path(repertoire) / FICHIER_ETAT_AGENT
        etat = _lire_json(fichier) or {}
        etat.update(champs)
        _ecrire_json(fichier, etat)
    except OSError:
        pass


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
    if ordre.get("action") and ordre.get("action") != "MISE_A_JOUR":
        resultat = agir(ordre, central, machine, env)
    else:
        resultat = appliquer(ordre, central, machine, env, fichier_cle)
    if resultat is None:
        return "ordre annulé"
    statut, etape, version = resultat
    noter_etat(machine.satellite, en_cours=None, derniere_operation={
        "quoi": ordre.get("action") or "MISE_A_JOUR", "version": (ordre.get("commit") or "")[:10],
        "statut": statut, "etape": etape, "fin": time.time()})
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
        resultat = passage(central, Machine(), env, REPERTOIRE / ".cle-signature.pub",
                           REPERTOIRE / ".maj-rapport.json")
        noter_etat(REPERTOIRE, dernier_passage=time.time(), resultat=resultat, central_joint=True, en_cours=None)
        print(resultat)
        return 0
    except (urllib.error.URLError, OSError, ValueError, KeyError) as erreur:
        # Central injoignable : ce n'est pas une panne, c'est la vie d'un satellite.
        noter_etat(REPERTOIRE, dernier_passage=time.time(), resultat="central injoignable",
                   central_joint=False, en_cours=None)
        print(f"Central injoignable ou réponse illisible : {erreur}")
        return 0


if __name__ == "__main__":
    sys.exit(principal())
