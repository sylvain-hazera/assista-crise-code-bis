"""Point d'entrée : `pythonw -m passerelle` — c'est ce que lance le raccourci du bureau."""
import socket
import sys

#: Port local réservé tant que l'application tourne. Deux exemplaires ouverts lanceraient deux
#: ponts sur la même radio : chaque message partirait en double, et ils se disputeraient le port.
PORT_VERROU = 47631


def prendre_le_verrou():
    verrou = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        verrou.bind(("127.0.0.1", PORT_VERROU))
        verrou.listen(1)
        return verrou
    except OSError:
        verrou.close()
        return None


def main():
    from tkinter import Tk, messagebox

    verrou = prendre_le_verrou()
    if verrou is None:
        racine = Tk()
        racine.withdraw()
        messagebox.showinfo("Assista-Crise Passerelle",
                            "La passerelle est déjà ouverte : regardez dans la barre des tâches.")
        return 0

    from . import config
    from .fenetre import Fenetre, journaliser
    from .gestion import Passerelle

    try:
        passerelle = Passerelle()
        Fenetre(passerelle, premier_lancement=config.lire_premier_lancement()).lancer()
    except Exception as erreur:
        journaliser(erreur)
        raise
    finally:
        verrou.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
