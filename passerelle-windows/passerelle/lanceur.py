"""Lance un pont dans un sous-processus qui meurt avec l'application.

« Ça doit s'arrêter à la fermeture de l'application » (Sylvain, 15/11/2026) — y compris quand
elle est tuée par le gestionnaire des tâches ou qu'elle plante, cas où elle n'a pas l'occasion
d'arrêter ses ponts elle-même. L'application garde donc ouvert un tuyau vers l'entrée standard
de chaque pont : quand elle disparaît, quelle qu'en soit la raison, le système ferme le tuyau,
la lecture ci-dessous se termine, et le pont s'arrête. Aucun pont orphelin ne continue de tenir
une radio en arrière-plan.
"""
import os
import runpy
import sys
import threading


def _mourir_avec_le_parent():
    # Lecture directe du descripteur, pas de `sys.stdin` : son tampon porte un verrou que
    # l'interpréteur veut reprendre en s'arrêtant, et un pont qui se terminait de lui-même
    # finissait sur « Fatal Python error: could not acquire lock for stdin ».
    try:
        while os.read(0, 4096):
            pass
    except OSError:
        pass
    os._exit(0)


if __name__ == "__main__":
    script = sys.argv[1]
    threading.Thread(target=_mourir_avec_le_parent, daemon=True).start()
    # Le pont importe ses modules voisins (crypto, admin_meshtastic…) : son dossier d'abord.
    sys.path.insert(0, os.path.dirname(os.path.abspath(script)))
    sys.argv = [script]
    runpy.run_path(script, run_name="__main__")
