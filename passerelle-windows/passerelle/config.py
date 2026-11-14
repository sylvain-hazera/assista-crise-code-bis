"""Ce que la passerelle retient d'un lancement à l'autre : à qui elle appartient, et ses radios.

Un seul fichier JSON, écrit de façon atomique (fichier temporaire puis remplacement) : une
coupure de courant pendant l'écriture ne doit pas laisser une configuration à moitié écrite, qui
obligerait à tout réenrôler. Les secrets y sont protégés par `coffre`.
"""
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import coffre
from .chemins import dossier_donnees

FICHIER = "config.json"
FICHIER_PREMIER_LANCEMENT = "premier-lancement.json"


@dataclass
class Radio:
    """Une radio tenue par cette passerelle."""
    compagnon_id: str
    protocole: str          # MESHCORE | MESHTASTIC
    transport: str          # USB | BLE | TCP
    adresse: str            # COM5 | AA:BB:… | 192.168.1.50:4403
    nom: str = ""
    # L'identité lue sur la radio (clé publique MeshCore, numéro de nœud Meshtastic) : c'est
    # elle qui reconnaît la radio quand son port COM change d'un branchement à l'autre.
    identite: str = ""


@dataclass
class Config:
    central: str = ""
    nom: str = ""
    institution: str = ""
    satellite_id: str = ""
    # Protégés par le coffre. `secret` ne sert qu'entre l'enrôlement et la validation par un
    # administrateur ; `mot_de_passe` est celui du compte de service, reçu une seule fois.
    secret: str = ""
    email: str = ""
    mot_de_passe: str = ""
    radios: list = field(default_factory=list)

    @property
    def etat(self) -> str:
        if self.email and self.mot_de_passe:
            return "PRETE"
        if self.satellite_id and self.secret:
            return "EN_ATTENTE"
        return "NON_ENROLEE"

    def mot_de_passe_clair(self) -> str:
        return coffre.reveler(self.mot_de_passe) if self.mot_de_passe else ""

    def secret_clair(self) -> str:
        return coffre.reveler(self.secret) if self.secret else ""

    def radio(self, compagnon_id: str):
        return next((r for r in self.radios if r.compagnon_id == compagnon_id), None)


def _chemin() -> Path:
    return dossier_donnees() / FICHIER


def charger() -> Config:
    try:
        brut = json.loads(_chemin().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Config()
    radios = [Radio(**{k: v for k, v in r.items() if k in Radio.__dataclass_fields__})
              for r in brut.pop("radios", []) if isinstance(r, dict)]
    connus = {k: v for k, v in brut.items() if k in Config.__dataclass_fields__}
    return Config(**connus, radios=radios)


def enregistrer(config: Config) -> None:
    chemin = _chemin()
    temporaire = chemin.with_suffix(".tmp")
    temporaire.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporaire, chemin)


def lire_premier_lancement():
    """`{central, jeton}` déposé par l'installeur, lu une fois puis supprimé : le jeton est à
    usage unique, il n'a rien à faire sur le disque après l'enrôlement."""
    chemin = dossier_donnees() / FICHIER_PREMIER_LANCEMENT
    try:
        # utf-8-sig : PowerShell 5 écrit un BOM en tête de ses fichiers « UTF8 ».
        donnees = json.loads(chemin.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    finally:
        try:
            chemin.unlink()
        except OSError:
            pass
    return donnees if isinstance(donnees, dict) else None
