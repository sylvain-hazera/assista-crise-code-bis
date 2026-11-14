"""Où l'application range ses affaires. Tout sous le profil de l'utilisateur : aucune écriture
ne demande de droits d'administrateur."""
import os
import sys
from pathlib import Path

NOM_DOSSIER = "AssistaCrisePasserelle"


def dossier_donnees() -> Path:
    """Configuration et journaux. `ASSISTA_PASSERELLE_DOSSIER` le déplace (tests)."""
    force = os.environ.get("ASSISTA_PASSERELLE_DOSSIER")
    if force:
        base = Path(force)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / NOM_DOSSIER
    else:
        base = Path.home() / ".config" / NOM_DOSSIER
    base.mkdir(parents=True, exist_ok=True)
    return base


def dossier_journaux() -> Path:
    d = dossier_donnees() / "journaux"
    d.mkdir(parents=True, exist_ok=True)
    return d


def dossier_application() -> Path:
    """Le dossier qui contient `passerelle/` et `ponts/`."""
    return Path(__file__).resolve().parent.parent


def dossier_pont(protocole: str) -> Path:
    return dossier_application() / "ponts" / ("meshtastic" if protocole == "MESHTASTIC" else "meshcore")
