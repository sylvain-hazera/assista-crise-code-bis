"""Le mot de passe du compte de service ne s'écrit pas en clair sur le disque.

Règle du projet : « on ne stocke rien en clair ». Sous Windows, on le confie à DPAPI
(`CryptProtectData`) : chiffré par une clé liée au compte Windows de l'utilisateur, illisible
pour un autre compte ou sur une autre machine — sans mot de passe à retenir ni dépendance, c'est
une API du système appelée par ctypes.

Ailleurs que sous Windows (développement, tests), il n'y a pas d'équivalent sans dépendance : on
refuse d'écrire, sauf `ASSISTA_PASSERELLE_DEV=1` qui accepte un stockage simplement encodé —
jamais pour un usage réel.
"""
import base64
import os
import sys

PREFIXE_DPAPI = "dpapi:"
PREFIXE_DEV = "dev:"


class CoffreIndisponible(RuntimeError):
    pass


def _dpapi(donnees: bytes, proteger: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("taille", wintypes.DWORD), ("donnees", ctypes.POINTER(ctypes.c_char))]

    tampon = ctypes.create_string_buffer(donnees, len(donnees))
    entree = Blob(len(donnees), ctypes.cast(tampon, ctypes.POINTER(ctypes.c_char)))
    sortie = Blob()
    fonction = (ctypes.windll.crypt32.CryptProtectData if proteger
                else ctypes.windll.crypt32.CryptUnprotectData)
    if not fonction(ctypes.byref(entree), None, None, None, None, 0, ctypes.byref(sortie)):
        raise CoffreIndisponible("Windows a refusé de protéger le secret (DPAPI).")
    try:
        return ctypes.string_at(sortie.donnees, sortie.taille)
    finally:
        ctypes.windll.kernel32.LocalFree(sortie.donnees)


def proteger(secret: str) -> str:
    if sys.platform == "win32":
        return PREFIXE_DPAPI + base64.b64encode(_dpapi(secret.encode("utf-8"), True)).decode("ascii")
    if os.environ.get("ASSISTA_PASSERELLE_DEV") == "1":
        return PREFIXE_DEV + base64.b64encode(secret.encode("utf-8")).decode("ascii")
    raise CoffreIndisponible(
        "Stockage protégé indisponible hors de Windows : on n'écrit pas de secret en clair.")


def reveler(protege: str) -> str:
    if protege.startswith(PREFIXE_DPAPI):
        if sys.platform != "win32":
            raise CoffreIndisponible("Ce secret a été protégé sous Windows : illisible ici.")
        return _dpapi(base64.b64decode(protege[len(PREFIXE_DPAPI):]), False).decode("utf-8")
    if protege.startswith(PREFIXE_DEV) and os.environ.get("ASSISTA_PASSERELLE_DEV") == "1":
        return base64.b64decode(protege[len(PREFIXE_DEV):]).decode("utf-8")
    raise CoffreIndisponible("Secret illisible : format inconnu.")
