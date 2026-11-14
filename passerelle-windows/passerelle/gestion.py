"""Ce que fait la passerelle, sans rien savoir de la fenêtre qui la montre.

Trois temps :

1. **s'enrôler** : le code d'installation donné par un administrateur est échangé contre une
   place de passerelle ; un administrateur la valide sur la page Satellites du central ; la
   passerelle reçoit alors son compte de service ;
2. **connecter des radios** : c'est la personne qui désigne la radio — un port USB, une radio
   Bluetooth choisie dans la liste, une adresse du réseau local. La radio dit qui elle est, le
   central la déclare, un pont la prend en charge ;
3. **relayer** tant que la fenêtre est ouverte.

Toutes les opérations longues (sonder une radio, parler au central) sont bloquantes : la fenêtre
les appelle depuis un fil d'exécution.
"""
import json
import platform
import subprocess
import sys

from . import VERSION, central as api_central, coffre, config as cfg
from .chemins import dossier_application
from .ponts import Ponts, arreter_processus, specs


class ErreurPasserelle(Exception):
    """Message fait pour être affiché tel quel."""


def sonder(arguments, delai=45.0):
    """Lance `python -m passerelle.sonde …` et rend son résultat. Le processus est tué à
    l'échéance : une radio muette ne bloque jamais l'application."""
    options = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    processus = subprocess.Popen(
        [sys.executable, "-m", "passerelle.sonde", *[str(a) for a in arguments]],
        cwd=str(dossier_application()), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, **options)
    try:
        sortie, _ = processus.communicate(timeout=delai)
    except subprocess.TimeoutExpired:
        arreter_processus(processus, patience=1.0)
        return None
    for ligne in reversed(sortie.decode("utf-8", "replace").strip().splitlines()):
        try:
            reponse = json.loads(ligne)
        except ValueError:
            continue
        if not reponse.get("ok"):
            raise ErreurPasserelle(reponse.get("erreur") or "La détection a échoué.")
        return reponse.get("resultat")
    return None


def identite_texte(protocole, identite):
    if protocole == "MESHTASTIC":
        return f"!{int(identite['node_num']):08x}"
    return str(identite["pubkey_hex"]).lower()


class Passerelle:
    def __init__(self, sonder=sonder, ponts=None, session=None):
        self.config = cfg.charger()
        self._sonder = sonder
        self.ponts = ponts or Ponts()
        self._fabrique_session = session or api_central.Session
        self._session = None
        self.nouvelle_version = None

    # ══ Enrôlement ═══════════════════════════════════════════════════════════

    @property
    def etat(self):
        return self.config.etat

    def enroler(self, central, jeton, nom=None):
        central = api_central.normaliser_url(central)
        nom = (nom or platform.node() or "Passerelle Windows").strip()[:100]
        try:
            reponse = api_central.enroler(central, jeton, nom)
        except api_central.ErreurCentral as e:
            raise ErreurPasserelle(str(e)) from None
        self.config = cfg.Config(
            central=central, nom=reponse.get("nom") or nom,
            institution=reponse.get("institution_nom") or "",
            satellite_id=reponse["satellite_id"],
            secret=coffre.proteger(reponse["secret_recuperation"]),
        )
        cfg.enregistrer(self.config)

    def verifier_validation(self):
        """Vrai dès qu'un administrateur a validé la passerelle. À rappeler toutes les quelques
        secondes tant que l'état est EN_ATTENTE."""
        if self.etat != "EN_ATTENTE":
            return self.etat == "PRETE"
        try:
            identifiants = api_central.recuperer_identifiants(
                self.config.central, self.config.satellite_id, self.config.secret_clair())
        except api_central.ErreurCentral as e:
            raise ErreurPasserelle(str(e)) from None
        if identifiants is None:
            return False
        self.config.email = identifiants[0]
        self.config.mot_de_passe = coffre.proteger(identifiants[1])
        self.config.secret = ""       # à usage unique : le central l'a déjà effacé de son côté
        cfg.enregistrer(self.config)
        return True

    def oublier(self):
        """Repart de zéro (passerelle révoquée, changement d'institution)."""
        self.arreter()
        self.config = cfg.Config()
        cfg.enregistrer(self.config)

    # ══ Marche et arrêt ══════════════════════════════════════════════════════

    def session(self):
        if self._session is None:
            self._session = self._fabrique_session(
                self.config.central, self.config.email, self.config.mot_de_passe_clair())
        return self._session

    def demarrer(self):
        if self.etat != "PRETE":
            return
        self.ponts.configurer(self.config.central, self.config.email,
                              self.config.mot_de_passe_clair())
        self.ponts.synchroniser(specs(self.config))

    def arreter(self):
        """Fermeture de l'application : les ponts s'arrêtent, et le central l'apprend."""
        self.ponts.arreter_tout()
        if self.etat == "PRETE":
            for radio in self.config.radios:
                try:
                    self.session().signaler_arret(radio.protocole, radio.compagnon_id)
                except Exception:
                    pass

    def etats(self):
        """`compagnon_id -> MARCHE | RELANCE | ARRET`, en relançant au passage les ponts tombés."""
        par_pont = self.ponts.surveiller()
        resultat = {}
        for radio in self.config.radios:
            cle = "meshtastic" if radio.protocole == "MESHTASTIC" else f"meshcore-{radio.compagnon_id}"
            resultat[radio.compagnon_id] = par_pont.get(cle, "ARRET")
        return resultat

    def verifier_version(self):
        derniere = api_central.derniere_version(self.config.central) if self.config.central else None
        self.nouvelle_version = derniere if derniere and derniere != VERSION else None
        return self.nouvelle_version

    # ══ Trouver des radios ═══════════════════════════════════════════════════

    def ports_usb(self):
        """Les ports série présents, en marquant ceux qu'une radio connectée occupe déjà — on
        ne sonde jamais un port tenu par un pont : deux programmes sur le même port se volent
        les réponses, et l'ouvrir redémarre souvent une radio ESP32."""
        pris = {r.adresse: r for r in self.config.radios if r.transport == "USB"}
        ports = self._sonder(["ports"], delai=15) or []
        return [{**p, "radio": pris[p["port"]].nom if p["port"] in pris else None} for p in ports]

    def chercher_bluetooth(self):
        pris = {r.adresse for r in self.config.radios if r.transport == "BLE"}
        return [r for r in (self._sonder(["ble-chercher"], delai=30) or [])
                if r["adresse"] not in pris]

    def identifier(self, transport, adresse, protocole=None):
        """Interroge la radio désignée. Renvoie `{protocole, identite, nom, adresse}` — sans
        rien enregistrer : c'est `connecter` qui le fait, une fois la personne d'accord."""
        if transport == "USB":
            resultat = self._sonder(["usb", adresse])
        elif transport == "BLE":
            resultat = self._sonder(["ble", adresse, protocole or "MESHCORE"], delai=60)
        else:
            hote, _, port = adresse.strip().partition(":")
            if not hote:
                raise ErreurPasserelle("Indiquez l'adresse de la radio, par exemple 192.168.1.50.")
            resultat = self._sonder(["ip", hote, port.strip()])
            if resultat:
                adresse = f"{hote}:{resultat.pop('port')}"
        if not resultat:
            raise ErreurPasserelle(self._pourquoi_muette(transport))
        return {**resultat, "transport": transport, "adresse": adresse}

    @staticmethod
    def _pourquoi_muette(transport):
        if transport == "USB":
            return ("Aucune radio MeshCore ou Meshtastic ne répond sur ce port. Vérifiez le câble "
                    "(certains ne servent qu'à la charge), et qu'aucune autre application "
                    "n'utilise la radio.")
        if transport == "BLE":
            return ("La radio ne répond pas en Bluetooth. Rapprochez-la, fermez l'application "
                    "du téléphone qui y serait connectée, et pour MeshCore appairez-la d'abord "
                    "dans les paramètres Bluetooth de Windows (code affiché sur la radio, "
                    "souvent 123456).")
        return ("Aucune radio ne répond à cette adresse. Vérifiez qu'elle est sur le même réseau "
                "que ce poste et que son Wi-Fi est activé.")

    # ══ Connecter, retirer ═══════════════════════════════════════════════════

    def connecter(self, trouvee):
        """Déclare la radio sur le central et lance son pont. Une radio déjà connue (même
        identité) est mise à jour, pas doublée : c'est ce qui rattrape un port COM qui a changé.
        """
        protocole, identite = trouvee["protocole"], trouvee["identite"]
        empreinte = identite_texte(protocole, identite)
        nom = trouvee.get("nom") or f"Radio {empreinte[:9]}"
        try:
            compagnon_id = self.session().enregistrer_radio(
                protocole, identite, trouvee["transport"], trouvee["adresse"], nom)
        except api_central.ErreurCentral as e:
            raise ErreurPasserelle(str(e)) from None
        radio = cfg.Radio(compagnon_id=compagnon_id, protocole=protocole,
                          transport=trouvee["transport"], adresse=trouvee["adresse"],
                          nom=nom, identite=empreinte)
        self.config.radios = [r for r in self.config.radios
                              if r.compagnon_id != compagnon_id and r.identite != empreinte]
        self.config.radios.append(radio)
        cfg.enregistrer(self.config)
        self.demarrer()
        return radio

    def retirer(self, compagnon_id):
        radio = self.config.radio(compagnon_id)
        if radio is None:
            return
        self.config.radios = [r for r in self.config.radios if r.compagnon_id != compagnon_id]
        cfg.enregistrer(self.config)
        self.demarrer()                      # arrête le pont de cette radio
        try:
            self.session().retirer_radio(radio.protocole, compagnon_id)
        except api_central.ErreurCentral as e:
            raise ErreurPasserelle(
                f"Radio retirée de ce poste, mais le central n'a pas été prévenu : {e}") from None

    def rattraper_ports_usb(self):
        """Au lancement : une radio USB dont le port a disparu a peut-être simplement changé de
        numéro (Windows en attribue un autre selon la prise). On sonde les ports que personne
        ne tient, et on remet chaque radio reconnue sur son nouveau port. Renvoie les radios
        déplacées."""
        usb = [r for r in self.config.radios if r.transport == "USB"]
        if not usb:
            return []
        presents = {p["port"] for p in (self._sonder(["ports"], delai=15) or [])}
        perdues = {r.identite: r for r in usb if r.adresse not in presents}
        if not perdues:
            return []
        deplacees = []
        tenus = {r.adresse for r in usb if r.adresse in presents}
        for port in sorted(presents - tenus):
            trouvee = self._sonder(["usb", port])
            if not trouvee:
                continue
            empreinte = identite_texte(trouvee["protocole"], trouvee["identite"])
            if empreinte in perdues:
                deplacees.append(self.connecter({**trouvee, "transport": "USB", "adresse": port}))
                perdues.pop(empreinte)
            if not perdues:
                break
        return deplacees
