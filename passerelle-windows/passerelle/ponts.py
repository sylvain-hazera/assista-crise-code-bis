"""Les ponts radio, lancés et surveillés comme sous-processus.

Ce sont les ponts du satellite, inchangés : `meshtastic-bridge` — UN processus pour toutes les
radios Meshtastic, il demande lui-même au central lesquelles sont les siennes — et
`meshcore-bridge` — UN processus par radio, c'est ainsi qu'il est fait. Ils se configurent par
variables d'environnement, exactement comme dans Docker.

Le mot de passe du compte de service leur est passé par l'environnement du processus, en
mémoire : il n'est écrit nulle part.
"""
import hashlib
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .chemins import dossier_application, dossier_donnees, dossier_journaux, dossier_pont

#: Un pont qui s'arrête tout seul (radio absente au démarrage, erreur imprévue) est relancé,
#: mais pas en boucle serrée.
DELAI_RELANCE_S = 15
TAILLE_MAX_JOURNAL = 1_000_000


@dataclass(frozen=True)
class Spec:
    cle: str            # « meshtastic » ou « meshcore-<identifiant> »
    protocole: str
    env: tuple          # variables propres à ce pont, triées : comparables d'un tour à l'autre


def specs(config) -> list:
    """Les ponts qui doivent tourner pour cette configuration."""
    resultat = []
    meshtastic = sorted((r.compagnon_id, r.transport, r.adresse)
                        for r in config.radios if r.protocole == "MESHTASTIC")
    if meshtastic:
        # Le pont découvre ses radios auprès du central ; la signature ne sert qu'à le relancer
        # quand la liste change, pour ne pas attendre son rafraîchissement.
        signature = hashlib.sha256(repr(meshtastic).encode()).hexdigest()[:12]
        resultat.append(Spec("meshtastic", "MESHTASTIC", (("PASSERELLE_SIGNATURE", signature),)))
    for r in config.radios:
        if r.protocole != "MESHCORE":
            continue
        env = {"COMPAGNON_ID": r.compagnon_id}
        if r.transport == "USB":
            env.update(MESHCORE_CONNEXION_TYPE="SERIE", MESHCORE_SERIE_DEVICE=r.adresse)
        elif r.transport == "BLE":
            env.update(MESHCORE_CONNEXION_TYPE="BLE", MESHCORE_BLE_ADRESSE=r.adresse)
        else:
            hote, _, port = r.adresse.rpartition(":")
            env.update(MESHCORE_CONNEXION_TYPE="TCP", MESHCORE_TCP_HOST=hote, MESHCORE_TCP_PORT=port)
        resultat.append(Spec(f"meshcore-{r.compagnon_id}", "MESHCORE", tuple(sorted(env.items()))))
    return resultat


def _ouvrir_journal(cle: str):
    chemin = dossier_journaux() / f"pont-{cle}.log"
    try:
        if chemin.stat().st_size > TAILLE_MAX_JOURNAL:
            chemin.replace(chemin.with_suffix(".log.ancien"))
    except OSError:
        pass
    return open(chemin, "ab")


def _lancer(spec: Spec, commun: dict):
    script = dossier_pont(spec.protocole) / "bridge.py"
    env = {**os.environ, **commun, **dict(spec.env)}
    options = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW   # pas de fenêtre noire
    journal = _ouvrir_journal(spec.cle)
    try:
        return subprocess.Popen(
            [sys.executable, "-m", "passerelle.lanceur", str(script)],
            cwd=str(dossier_application()), env=env,
            stdin=subprocess.PIPE, stdout=journal, stderr=subprocess.STDOUT, **options)
    finally:
        journal.close()     # le processus enfant garde sa propre copie du descripteur


class Ponts:
    def __init__(self, lancer=_lancer, horloge=time.monotonic):
        self._lancer = lancer
        self._horloge = horloge
        self._commun = {}
        self._voulus = {}       # cle -> Spec
        self._processus = {}    # cle -> (Spec, Popen)
        self._morts = {}        # cle -> instant de la mort constatée

    def configurer(self, central: str, email: str, mot_de_passe: str) -> None:
        self._commun = {
            "DJANGO_API_URL": f"{central}/api",
            "DJANGO_BRIDGE_EMAIL": email,
            "DJANGO_BRIDGE_PASSWORD": mot_de_passe,
            # Fichier propre aux satellites « full » ; absent ici, le pont parle au central.
            "FICHIER_ETAT_CONNECTIVITE": str(dossier_donnees() / "etat_connectivite.json"),
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }

    def synchroniser(self, voulus: list) -> None:
        """Arrête ce qui n'a plus lieu d'être, relance ce qui a changé, démarre ce qui manque."""
        self._voulus = {s.cle: s for s in voulus}
        for cle, (spec, _) in list(self._processus.items()):
            if self._voulus.get(cle) != spec:
                self._arreter(cle)
        for cle, spec in self._voulus.items():
            if cle not in self._processus:
                self._demarrer(spec)

    def _demarrer(self, spec: Spec) -> None:
        self._processus[spec.cle] = (spec, self._lancer(spec, self._commun))
        self._morts.pop(spec.cle, None)

    def _arreter(self, cle: str) -> None:
        _, processus = self._processus.pop(cle)
        self._morts.pop(cle, None)
        arreter_processus(processus)

    def surveiller(self) -> dict:
        """À appeler régulièrement. Relance les ponts tombés (après un délai) et renvoie l'état
        de chacun : `MARCHE` ou `RELANCE`."""
        etats = {}
        maintenant = self._horloge()
        for cle, (spec, processus) in list(self._processus.items()):
            if processus.poll() is None:
                etats[cle] = "MARCHE"
                continue
            mort = self._morts.setdefault(cle, maintenant)
            etats[cle] = "RELANCE"
            if maintenant - mort >= DELAI_RELANCE_S:
                self._demarrer(spec)
        return etats

    def liberer(self, cle: str) -> None:
        """Arrête un pont le temps d'une opération sur sa radio ; `synchroniser` le relancera."""
        if cle in self._processus:
            self._arreter(cle)

    def arreter_tout(self) -> None:
        self._voulus = {}
        for cle in list(self._processus):
            self._arreter(cle)


def arreter_processus(processus, patience: float = 3.0) -> None:
    """Fermer le tuyau suffit en principe (voir lanceur.py) ; on insiste si le pont traîne."""
    try:
        if processus.stdin:
            processus.stdin.close()
    except OSError:
        pass
    try:
        processus.wait(timeout=patience)
        return
    except subprocess.TimeoutExpired:
        pass
    processus.terminate()
    try:
        processus.wait(timeout=patience)
    except subprocess.TimeoutExpired:
        processus.kill()


def journal_recent(cle: str, lignes: int = 3) -> str:
    """Les dernières lignes du journal d'un pont, pour dire à l'écran pourquoi ça ne marche pas."""
    chemin: Path = dossier_journaux() / f"pont-{cle}.log"
    try:
        with open(chemin, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 4000))
            texte = f.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(texte.strip().splitlines()[-lignes:])
