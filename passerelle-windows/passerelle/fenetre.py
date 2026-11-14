"""La fenêtre de la passerelle.

Faite pour quelqu'un qui n'est pas informaticien : trois écrans qui se suivent (enregistrer la
passerelle, attendre la validation, connecter des radios), des phrases entières, et aucun terme
technique qui ne soit pas sur l'étiquette de la radio.

**Fermer la fenêtre arrête tout** — c'est écrit en bas, et c'est ce qui se passe.

Aucune opération longue ne tourne dans le fil de l'interface : tout passe par `_en_arriere`, qui
rend la main tout de suite et rappelle l'interface quand c'est fini.
"""
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import VERSION
from .chemins import dossier_journaux
from .gestion import ErreurPasserelle, Passerelle

TITRE = "Assista-Crise Passerelle"
LIBELLE_PROTOCOLE = {"MESHCORE": "MeshCore", "MESHTASTIC": "Meshtastic"}
LIBELLE_TRANSPORT = {"USB": "USB", "BLE": "Bluetooth", "TCP": "Réseau"}
LIBELLE_ETAT = {"MARCHE": "● En marche", "RELANCE": "○ Nouvel essai…", "ARRET": "○ Arrêtée"}


class Fenetre:
    def __init__(self, passerelle: Passerelle, premier_lancement=None, racine=None):
        self.p = passerelle
        self.premier_lancement = premier_lancement or {}
        self.racine = racine or tk.Tk()
        self.racine.title(TITRE)
        self.racine.geometry("680x460")
        self.racine.minsize(600, 400)
        self.racine.protocol("WM_DELETE_WINDOW", self.fermer)
        self._resultats = queue.Queue()
        self._occupe = False
        self._ferme = False
        self._ecran = None
        self._ecran_affiche = None

        self.message = tk.StringVar()
        self.corps = ttk.Frame(self.racine, padding=16)
        self.corps.pack(fill="both", expand=True)
        pied = ttk.Frame(self.racine, padding=(16, 0, 16, 10))
        pied.pack(fill="x")
        ttk.Label(pied, textvariable=self.message, wraplength=640, justify="left").pack(anchor="w")
        ttk.Label(pied, text="Fermer cette fenêtre arrête la passerelle.  ·  version " + VERSION,
                  foreground="#666666").pack(anchor="w", pady=(6, 0))

        self._afficher()
        self.racine.after(100, self._depiler)
        self.racine.after(300, self._au_lancement)

    # ══ Tâches de fond ═══════════════════════════════════════════════════════

    def _en_arriere(self, travail, ensuite=None, attente=""):
        """Exécute `travail()` hors du fil de l'interface, puis `ensuite(resultat)` dans celui-ci.
        Une `ErreurPasserelle` s'affiche telle quelle ; toute autre erreur est journalisée."""
        if attente:
            self.message.set(attente)

        def executer():
            try:
                self._resultats.put((ensuite, travail(), None))
            except ErreurPasserelle as e:
                self._resultats.put((None, None, str(e)))
            except Exception as e:      # ne doit jamais faire disparaître la fenêtre
                journaliser(e)
                self._resultats.put((None, None, "Une erreur inattendue s'est produite. Le détail "
                                                 "est dans les journaux."))

        threading.Thread(target=executer, daemon=True).start()

    def _depiler(self):
        try:
            while True:
                ensuite, resultat, erreur = self._resultats.get_nowait()
                self._occupe = False
                if erreur:
                    self.message.set(erreur)
                elif ensuite:
                    ensuite(resultat)
        except queue.Empty:
            pass
        if not self._ferme:
            self.racine.after(100, self._depiler)

    # ══ Écrans ═══════════════════════════════════════════════════════════════

    def _afficher(self):
        if self._ecran_affiche == self.p.etat:
            return
        self._ecran_affiche = self.p.etat
        for enfant in self.corps.winfo_children():
            enfant.destroy()
        {"NON_ENROLEE": self._ecran_enrolement, "EN_ATTENTE": self._ecran_attente,
         "PRETE": self._ecran_radios}[self.p.etat]()

    def _ecran_enrolement(self):
        ttk.Label(self.corps, text="Enregistrer cette passerelle", font=("", 14, "bold")).pack(anchor="w")
        ttk.Label(self.corps, wraplength=620, justify="left", text=(
            "Saisissez l'adresse du site Assista-Crise et le code d'installation que votre "
            "administrateur vous a donné (page Satellites du site).")).pack(anchor="w", pady=(6, 14))
        grille = ttk.Frame(self.corps)
        grille.pack(anchor="w", fill="x")
        self.champ_central = tk.StringVar(value=self.premier_lancement.get("central", ""))
        self.champ_jeton = tk.StringVar(value=self.premier_lancement.get("jeton", ""))
        for ligne, (libelle, variable) in enumerate((("Adresse du site", self.champ_central),
                                                     ("Code d'installation", self.champ_jeton))):
            ttk.Label(grille, text=libelle).grid(row=ligne, column=0, sticky="w", pady=4, padx=(0, 10))
            ttk.Entry(grille, textvariable=variable, width=52).grid(row=ligne, column=1, sticky="we")
        grille.columnconfigure(1, weight=1)
        ttk.Button(self.corps, text="Enregistrer cette passerelle",
                   command=self._enroler).pack(anchor="w", pady=14)

    def _ecran_attente(self):
        ttk.Label(self.corps, text="En attente de validation", font=("", 14, "bold")).pack(anchor="w")
        ttk.Label(self.corps, wraplength=620, justify="left", text=(
            f"Cette passerelle est enregistrée sous le nom « {self.p.config.nom} » pour "
            f"{self.p.config.institution or 'votre institution'}.\n\n"
            "Un administrateur doit maintenant la valider sur la page Satellites du site "
            "Assista-Crise. Laissez cette fenêtre ouverte : elle se mettra à jour toute seule."
        )).pack(anchor="w", pady=(6, 14))
        barre = ttk.Progressbar(self.corps, mode="indeterminate", length=260)
        barre.pack(anchor="w")
        barre.start(12)
        ttk.Button(self.corps, text="Recommencer avec un autre code",
                   command=self._oublier).pack(anchor="w", pady=18)

    def _ecran_radios(self):
        ttk.Label(self.corps, text=f"Passerelle de {self.p.config.institution or 'votre institution'}",
                  font=("", 14, "bold")).pack(anchor="w")
        ttk.Label(self.corps, text="Radios connectées à ce poste :").pack(anchor="w", pady=(6, 4))

        self.table = ttk.Treeview(self.corps, columns=("type", "liaison", "etat"), height=7,
                                  selectmode="browse")
        for colonne, titre, largeur in (("#0", "Radio", 220), ("type", "Type", 90),
                                        ("liaison", "Liaison", 170), ("etat", "État", 130)):
            self.table.heading(colonne, text=titre, anchor="w")
            self.table.column(colonne, width=largeur, anchor="w")
        self.table.pack(fill="both", expand=True)

        boutons = ttk.Frame(self.corps)
        boutons.pack(fill="x", pady=(10, 0))
        self.boutons = [
            ttk.Button(boutons, text="Connecter en USB", command=self._dialogue_usb),
            ttk.Button(boutons, text="Connecter en Bluetooth", command=self._dialogue_bluetooth),
            ttk.Button(boutons, text="Connecter par adresse", command=self._dialogue_adresse),
            ttk.Button(boutons, text="Retirer", command=self._retirer),
        ]
        for bouton in self.boutons[:3]:
            bouton.pack(side="left", padx=(0, 6))
        self.boutons[3].pack(side="right")
        ttk.Button(boutons, text="Journaux", command=ouvrir_journaux).pack(side="right", padx=6)
        self._rafraichir_table()

    def _rafraichir_table(self, etats=None):
        if self.p.etat != "PRETE" or not hasattr(self, "table") or not self.table.winfo_exists():
            return
        etats = etats if etats is not None else self.p.etats()
        choisie = self.table.selection()
        self.table.delete(*self.table.get_children())
        for radio in self.p.config.radios:
            liaison = f"{LIBELLE_TRANSPORT.get(radio.transport, radio.transport)}  {radio.adresse}"
            self.table.insert("", "end", iid=radio.compagnon_id, text=radio.nom, values=(
                LIBELLE_PROTOCOLE.get(radio.protocole, radio.protocole), liaison,
                LIBELLE_ETAT.get(etats.get(radio.compagnon_id, "ARRET"), "")))
        if choisie and self.table.exists(choisie[0]):
            self.table.selection_set(choisie[0])

    # ══ Vie de l'application ═════════════════════════════════════════════════

    def _au_lancement(self):
        if self.p.etat == "NON_ENROLEE" and self.premier_lancement.get("jeton"):
            self._enroler()                      # l'installeur a tout fourni : rien à saisir
        elif self.p.etat == "PRETE":
            self._demarrer()
        self._battre()

    def _demarrer(self):
        def travail():
            deplacees = self.p.rattraper_ports_usb()
            self.p.demarrer()
            self.p.verifier_version()
            return deplacees

        def ensuite(deplacees):
            textes = []
            if deplacees:
                textes.append("Radio retrouvée sur un nouveau port : "
                              + ", ".join(f"{r.nom} ({r.adresse})" for r in deplacees) + ".")
            if self.p.nouvelle_version:
                textes.append(f"Une version plus récente ({self.p.nouvelle_version}) est "
                              "disponible : relancez l'installation depuis le site.")
            if not self.p.config.radios:
                textes.append("Aucune radio pour l'instant : branchez-en une, puis cliquez sur "
                              "« Connecter en USB ».")
            self.message.set("  ".join(textes) or "Passerelle en marche.")
            self._rafraichir_table()

        self._en_arriere(travail, ensuite, "Démarrage…")

    def _battre(self):
        """Toutes les 3 secondes : état des ponts, et validation tant qu'on l'attend."""
        if self._ferme:
            return
        if self.p.etat == "PRETE":
            self._rafraichir_table()
        elif self.p.etat == "EN_ATTENTE" and not self._occupe:
            self._occupe = True
            self._en_arriere(self.p.verifier_validation, self._apres_validation)
        self.racine.after(3000, self._battre)

    def _apres_validation(self, validee):
        if validee:
            self._afficher()
            self._demarrer()

    def _enroler(self):
        central, jeton = self.champ_central.get(), self.champ_jeton.get()
        if not central.strip() or not jeton.strip():
            self.message.set("Renseignez l'adresse du site et le code d'installation.")
            return

        def ensuite(_):
            self.message.set("")
            self._afficher()

        self._en_arriere(lambda: self.p.enroler(central, jeton), ensuite, "Enregistrement…")

    def _oublier(self):
        if messagebox.askyesno(TITRE, "Abandonner cet enregistrement et recommencer avec un "
                                      "autre code d'installation ?", parent=self.racine):
            self.premier_lancement = {"central": self.p.config.central}
            self.p.oublier()
            self._afficher()

    def fermer(self):
        """Arrêt complet. Les ponts s'arrêtent tout de suite ; prévenir le central peut prendre
        quelques secondes, mais ne retient jamais la fenêtre plus de cinq."""
        if self._ferme:
            return
        self._ferme = True
        self.message.set("Arrêt de la passerelle…")
        fin = threading.Event()

        def arreter():
            try:
                self.p.arreter()
            except Exception as e:
                journaliser(e)
            fin.set()

        threading.Thread(target=arreter, daemon=True).start()

        def attendre(restant=50):
            if fin.is_set() or restant <= 0:
                self.racine.destroy()
            else:
                self.racine.after(100, attendre, restant - 1)

        attendre()

    # ══ Connecter une radio ══════════════════════════════════════════════════

    def _proposer(self, trouvee):
        """« Voilà ce que j'ai trouvé — on la connecte ? » Rien n'est déclaré avant le oui."""
        protocole = LIBELLE_PROTOCOLE.get(trouvee["protocole"], trouvee["protocole"])
        nom = trouvee.get("nom") or "sans nom"
        if not messagebox.askyesno(TITRE, f"Radio trouvée : {nom} ({protocole}).\n\n"
                                          "La connecter à Assista-Crise ?", parent=self.racine):
            self.message.set("")
            return

        def ensuite(radio):
            self.message.set(f"« {radio.nom} » est connectée. Elle apparaît sur le site dans "
                             f"quelques instants.")
            self._rafraichir_table()

        self._en_arriere(lambda: self.p.connecter(trouvee), ensuite, "Connexion de la radio…")

    def _identifier(self, transport, adresse, protocole=None):
        self._en_arriere(lambda: self.p.identifier(transport, adresse, protocole), self._proposer,
                         "Interrogation de la radio… (jusqu'à une minute)")

    def _choisir(self, titre, consigne, charger, libelle, valider, attente):
        """Une liste à choix, remplie en arrière-plan : ports USB ou radios Bluetooth."""
        fenetre = tk.Toplevel(self.racine)
        fenetre.title(titre)
        fenetre.geometry("520x330")
        fenetre.transient(self.racine)
        cadre = ttk.Frame(fenetre, padding=14)
        cadre.pack(fill="both", expand=True)
        ttk.Label(cadre, text=consigne, wraplength=480, justify="left").pack(anchor="w")
        etat = tk.StringVar(value=attente)
        ttk.Label(cadre, textvariable=etat, foreground="#666666").pack(anchor="w", pady=(6, 2))
        liste = tk.Listbox(cadre, height=8, activestyle="none")
        liste.pack(fill="both", expand=True)
        elements = []

        def remplir(trouves):
            if not fenetre.winfo_exists():
                return
            elements[:] = trouves or []
            liste.delete(0, "end")
            for e in elements:
                liste.insert("end", libelle(e))
            etat.set(f"{len(elements)} trouvé(s)." if elements else "Rien trouvé.")
            if elements:
                liste.selection_set(0)

        def relancer():
            etat.set(attente)
            self._en_arriere(charger, remplir)

        def choisir():
            selection = liste.curselection()
            if not selection:
                return
            element = elements[selection[0]]
            fenetre.destroy()
            valider(element)

        boutons = ttk.Frame(cadre)
        boutons.pack(fill="x", pady=(10, 0))
        ttk.Button(boutons, text="Connecter", command=choisir).pack(side="left")
        ttk.Button(boutons, text="Chercher à nouveau", command=relancer).pack(side="left", padx=6)
        ttk.Button(boutons, text="Annuler", command=fenetre.destroy).pack(side="right")
        liste.bind("<Double-Button-1>", lambda _: choisir())
        relancer()
        return fenetre

    def _dialogue_usb(self):
        def libelle(p):
            suffixe = f"   — déjà connectée : {p['radio']}" if p.get("radio") else ""
            return f"{p['port']}   {p['description']}{suffixe}"

        def valider(p):
            if p.get("radio"):
                self.message.set(f"Ce port est déjà utilisé par « {p['radio']} ».")
            else:
                self._identifier("USB", p["port"])

        return self._choisir(
            "Connecter en USB",
            "Branchez la radio avec un câble USB, puis choisissez son port. Si vous hésitez, "
            "débranchez-la, cliquez sur « Chercher à nouveau », rebranchez-la : le port qui "
            "apparaît est le sien.",
            self.p.ports_usb, libelle, valider, "Recherche des ports…")

    def _dialogue_bluetooth(self):
        def libelle(r):
            return f"{r['nom']}   ({LIBELLE_PROTOCOLE.get(r['protocole'], r['protocole'])})"

        return self._choisir(
            "Connecter en Bluetooth",
            "Allumez la radio et approchez-la. Fermez l'application du téléphone si elle y est "
            "connectée : une radio ne sert qu'un appareil à la fois. Pour MeshCore, appairez "
            "d'abord la radio dans les paramètres Bluetooth de Windows (code affiché sur la "
            "radio, souvent 123456).",
            self.p.chercher_bluetooth, libelle,
            lambda r: self._identifier("BLE", r["adresse"], r["protocole"]),
            "Recherche des radios à portée… (une dizaine de secondes)")

    def _dialogue_adresse(self):
        adresse = simpledialog.askstring(
            TITRE, "Adresse de la radio sur le réseau de ce poste\n(par exemple 192.168.1.50) :",
            parent=self.racine)
        if adresse and adresse.strip():
            self._identifier("TCP", adresse.strip())

    def _retirer(self):
        selection = self.table.selection()
        if not selection:
            self.message.set("Choisissez d'abord une radio dans la liste.")
            return
        radio = self.p.config.radio(selection[0])
        if radio and messagebox.askyesno(
                TITRE, f"Retirer « {radio.nom} » de cette passerelle ?\n\nElle ne sera plus "
                       "relayée par ce poste. Vous pourrez la reconnecter plus tard.",
                parent=self.racine):
            def ensuite(_):
                self.message.set(f"« {radio.nom} » retirée.")
                self._rafraichir_table()
            self._en_arriere(lambda: self.p.retirer(radio.compagnon_id), ensuite, "Retrait…")

    def lancer(self):
        self.racine.mainloop()


# ══ Hors de la classe ═════════════════════════════════════════════════════════

def journaliser(erreur):
    import traceback
    try:
        with open(dossier_journaux() / "application.log", "a", encoding="utf-8") as f:
            f.write("".join(traceback.format_exception(type(erreur), erreur, erreur.__traceback__)))
            f.write("\n")
    except OSError:
        pass


def ouvrir_journaux():
    dossier = str(dossier_journaux())
    try:
        if sys.platform == "win32":
            os.startfile(dossier)        # noqa: S606 — ouvre l'explorateur sur un dossier à nous
        else:
            import subprocess
            subprocess.Popen(["xdg-open", dossier])
    except OSError:
        pass
