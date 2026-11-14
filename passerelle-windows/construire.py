#!/usr/bin/env python3
"""Assemble ce que le central distribue aux PC Windows, dans `frontend/public/passerelle/` :

- `passerelle.zip` : l'application (`passerelle/`), les deux ponts du satellite (`ponts/`), la
  liste des composants, l'icône et le désinstalleur ;
- `installer.ps1` : l'installeur, téléchargé par le petit .bat que génère la page Satellites ;
- `version.json` : la version distribuée, que l'application compare à la sienne.

Ces fichiers sont versionnés avec le dépôt : l'image du site se construit depuis `frontend/`
seul et ne voit ni ce dossier ni les ponts. **À relancer après toute modification de
l'application ou d'un pont** — `tests/test_distribution.py` échoue tant que ce n'est pas fait.

L'archive est reproductible (ordre et dates fixes) : la reconstruire sans rien changer ne
modifie pas un octet, ce qui permet justement de vérifier qu'elle est à jour.

    python3 construire.py            # reconstruit
    python3 construire.py --verifier # dit seulement si c'est à jour (code 1 sinon)
"""
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ICI = Path(__file__).resolve().parent
DEPOT = ICI.parent
SORTIE = DEPOT / "frontend" / "public" / "passerelle"
DATE_FIXE = (2026, 1, 1, 0, 0, 0)


def version() -> str:
    return re.search(r'VERSION = "([^"]+)"', (ICI / "passerelle" / "__init__.py").read_text()).group(1)


def contenu() -> dict:
    """Chemin dans l'archive -> octets."""
    fichiers = {}
    for f in sorted((ICI / "passerelle").glob("*.py")):
        fichiers[f"passerelle/{f.name}"] = f.read_bytes()
    for dossier, source in (("meshcore", "meshcore-bridge"), ("meshtastic", "meshtastic-bridge")):
        for f in sorted((DEPOT / source).glob("*.py")):
            if not f.name.startswith("test_"):
                fichiers[f"ponts/{dossier}/{f.name}"] = f.read_bytes()
    fichiers["requirements.txt"] = (ICI / "requirements.txt").read_bytes()
    fichiers["desinstaller.bat"] = (ICI / "desinstaller.bat").read_bytes()
    fichiers["passerelle.ico"] = (DEPOT / "frontend" / "public" / "logo.ico").read_bytes()
    return fichiers


def archive() -> bytes:
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for nom, octets in sorted(contenu().items()):
            info = zipfile.ZipInfo(nom, date_time=DATE_FIXE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, octets)
    return tampon.getvalue()


def produits() -> dict:
    return {
        "passerelle.zip": archive(),
        "installer.ps1": (ICI / "installer.ps1").read_bytes(),
        "version.json": (json.dumps({"version": version()}) + "\n").encode(),
    }


def perimes() -> list:
    return [nom for nom, octets in produits().items()
            if not (SORTIE / nom).exists() or (SORTIE / nom).read_bytes() != octets]


if __name__ == "__main__":
    if "--verifier" in sys.argv:
        vieux = perimes()
        print("à jour" if not vieux else "périmé : " + ", ".join(vieux))
        sys.exit(1 if vieux else 0)
    SORTIE.mkdir(parents=True, exist_ok=True)
    for nom, octets in produits().items():
        (SORTIE / nom).write_bytes(octets)
        print(f"{nom:16s} {len(octets):>8d} octets")
