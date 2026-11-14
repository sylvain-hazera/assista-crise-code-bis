"""La passerelle Windows, vérifiée sans Windows, sans radio et sans central.

Ce qui est tenu ici : l'enrôlement en trois temps, l'identification d'une radio avant toute
déclaration, le rattrapage d'un port COM qui change, l'arrêt complet à la fermeture, et le fait
qu'aucun secret ne s'écrit en clair. Ce qui ne peut PAS l'être ici — l'installeur PowerShell, la
fenêtre, le Bluetooth et les ports COM réels — est à valider sur un vrai poste.
"""
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from passerelle import VERSION, central, coffre, config as cfg, sonde
from passerelle.chemins import dossier_donnees
from passerelle.gestion import ErreurPasserelle, Passerelle, identite_texte
from passerelle.ponts import Ponts, Spec, specs

CENTRAL = "https://central.test"


# ══ Faux central ══════════════════════════════════════════════════════════════

class FauxCentral:
    """Le strict nécessaire des endpoints du central, en mémoire."""

    def __init__(self):
        self.valide = False
        self.radios = {}
        self.appels = []
        self.identifiants_donnes = False

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        chemin, corps = requete.url.path, json.loads(requete.content or b"{}")
        self.appels.append((requete.method, chemin, corps))
        if chemin == "/api/satellites/enroler/":
            if corps["jeton"] != "BON-CODE":
                return httpx.Response(400, json={"error": "Jeton invalide, déjà utilisé ou expiré."})
            return httpx.Response(201, json={
                "satellite_id": "sat-1", "secret_recuperation": "secret-unique",
                "institution_nom": "Mairie de Moissac", "nom": corps["nom"]})
        if chemin == "/api/satellites/sat-1/recuperer-identifiants/":
            if corps["secret"] != "secret-unique" or self.identifiants_donnes:
                return httpx.Response(403, json={"error": "Secret invalide."})
            if not self.valide:
                return httpx.Response(202, json={"statut_enrolement": "EN_ATTENTE"})
            self.identifiants_donnes = True
            return httpx.Response(200, json={"email": "sat@service", "password": "mdp-service"})
        if chemin == "/api/token/":
            ok = corps == {"email": "sat@service", "password": "mdp-service"}
            return httpx.Response(200 if ok else 401, json={"access": "jeton-acces"} if ok else {})
        if requete.headers.get("authorization") != "Bearer jeton-acces":
            return httpx.Response(401)
        if chemin.endswith("/enregistrer-depuis-satellite/"):
            cle = corps.get("pubkey_hex") or corps.get("node_num")
            cree = cle not in self.radios
            self.radios[cle] = corps
            return httpx.Response(201 if cree else 200, json={"id": f"radio-{cle}", "cree": cree})
        if chemin.endswith("/retirer-du-satellite/") or chemin.endswith("/rapporter-etat/"):
            return httpx.Response(200, json={})
        return httpx.Response(404)


@pytest.fixture
def faux_central(monkeypatch):
    serveur = FauxCentral()
    transport = httpx.MockTransport(serveur)
    vrai_client = httpx.Client
    monkeypatch.setattr(central.httpx, "Client",
                        lambda **kw: vrai_client(transport=transport, **kw))
    return serveur


class FauxPonts(Ponts):
    """Les vrais calculs de `Ponts`, sans lancer de processus."""

    class Processus:
        def __init__(self):
            self.vivant = True
            self.stdin = None

        def poll(self):
            return None if self.vivant else 1

        def wait(self, timeout=None):
            self.vivant = False

        def terminate(self):
            self.vivant = False

        kill = terminate

    def __init__(self):
        self.lances = []
        self.maintenant = 0.0
        super().__init__(lancer=self._faux_lancer, horloge=lambda: self.maintenant)

    def _faux_lancer(self, spec, commun):
        processus = self.Processus()
        self.lances.append((spec, dict(commun), processus))
        return processus


def faux_sondeur(reponses):
    """Un sondeur qui répond d'après la commande reçue, et note ce qu'on lui a demandé."""
    demandes = []

    def sonder(arguments, delai=None):
        demandes.append(list(arguments))
        reponse = reponses.get(tuple(arguments), reponses.get(arguments[0]))
        return reponse(arguments) if callable(reponse) else reponse

    sonder.demandes = demandes
    return sonder


def passerelle_prete(faux_central, reponses=None):
    faux_central.valide = True
    p = Passerelle(sonder=faux_sondeur(reponses or {}), ponts=FauxPonts())
    p.enroler(CENTRAL, "BON-CODE", "PC-ACCUEIL")
    assert p.verifier_validation() is True
    return p


HELTEC = {"protocole": "MESHCORE", "identite": {"pubkey_hex": "ab" * 32}, "nom": "Heltec V3"}
TBEAM = {"protocole": "MESHTASTIC", "identite": {"node_num": 0x0BADCAFE}, "nom": "T-Beam"}


# ══ Enrôlement ════════════════════════════════════════════════════════════════

class TestEnrolement:
    def test_les_trois_temps(self, faux_central):
        p = Passerelle(sonder=faux_sondeur({}), ponts=FauxPonts())
        assert p.etat == "NON_ENROLEE"

        p.enroler("central.test/", "BON-CODE", "PC-ACCUEIL")
        assert p.etat == "EN_ATTENTE"
        assert p.config.institution == "Mairie de Moissac"
        assert p.verifier_validation() is False          # personne n'a encore validé

        faux_central.valide = True
        assert p.verifier_validation() is True
        assert p.etat == "PRETE"

    def test_la_version_annoncee_dit_que_c_est_windows(self, faux_central):
        Passerelle(sonder=faux_sondeur({}), ponts=FauxPonts()).enroler(CENTRAL, "BON-CODE", "PC")
        assert faux_central.appels[0][2]["version_logicielle"] == f"windows-{VERSION}"

    def test_un_code_refuse_donne_un_message_lisible(self, faux_central):
        with pytest.raises(ErreurPasserelle, match="expiré"):
            Passerelle(sonder=faux_sondeur({}), ponts=FauxPonts()).enroler(CENTRAL, "FAUX", "PC")

    def test_l_etat_survit_a_la_fermeture(self, faux_central):
        passerelle_prete(faux_central)
        relancee = Passerelle(sonder=faux_sondeur({}), ponts=FauxPonts())
        assert relancee.etat == "PRETE"
        assert relancee.config.mot_de_passe_clair() == "mdp-service"

    def test_le_secret_d_attente_est_efface_apres_usage(self, faux_central):
        assert passerelle_prete(faux_central).config.secret == ""

    def test_une_adresse_saisie_a_la_main_est_normalisee(self):
        assert central.normaliser_url(" assista-crise.fr/ ") == "https://assista-crise.fr"
        assert central.normaliser_url("https://x.fr/api") == "https://x.fr"

    def test_le_fichier_de_premier_lancement_est_lu_une_seule_fois(self):
        chemin = dossier_donnees() / cfg.FICHIER_PREMIER_LANCEMENT
        # Avec le BOM que PowerShell 5 écrit en tête de ses fichiers.
        chemin.write_bytes(b"\xef\xbb\xbf" + json.dumps({"central": CENTRAL, "jeton": "J"}).encode())

        assert cfg.lire_premier_lancement() == {"central": CENTRAL, "jeton": "J"}
        assert not chemin.exists()
        assert cfg.lire_premier_lancement() is None


class TestRienEnClair:
    def test_ni_le_mot_de_passe_ni_le_secret_ne_sont_lisibles_dans_le_fichier(self, faux_central):
        p = Passerelle(sonder=faux_sondeur({}), ponts=FauxPonts())
        p.enroler(CENTRAL, "BON-CODE", "PC")
        contenu = (dossier_donnees() / cfg.FICHIER).read_text(encoding="utf-8")
        assert "secret-unique" not in contenu

        faux_central.valide = True
        p.verifier_validation()
        contenu = (dossier_donnees() / cfg.FICHIER).read_text(encoding="utf-8")
        assert "mdp-service" not in contenu

    def test_hors_windows_sans_mode_developpement_on_refuse_d_ecrire(self, monkeypatch):
        monkeypatch.delenv("ASSISTA_PASSERELLE_DEV")
        if sys.platform != "win32":
            with pytest.raises(coffre.CoffreIndisponible):
                coffre.proteger("secret")

    def test_le_mot_de_passe_ne_passe_aux_ponts_que_par_leur_environnement(self, faux_central):
        p = passerelle_prete(faux_central)
        p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})
        _, commun, _ = p.ponts.lances[-1]
        assert commun["DJANGO_BRIDGE_PASSWORD"] == "mdp-service"
        assert commun["DJANGO_API_URL"] == f"{CENTRAL}/api"


# ══ Radios ════════════════════════════════════════════════════════════════════

class TestConnecterUneRadio:
    def test_identifier_ne_declare_rien(self, faux_central):
        """La personne voit ce qu'on a trouvé AVANT que quoi que ce soit parte au central."""
        p = passerelle_prete(faux_central, {("usb", "COM5"): HELTEC})

        trouvee = p.identifier("USB", "COM5")

        assert trouvee["nom"] == "Heltec V3" and trouvee["adresse"] == "COM5"
        assert faux_central.radios == {}

    def test_connecter_declare_la_radio_et_lance_son_pont(self, faux_central):
        p = passerelle_prete(faux_central)

        radio = p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})

        assert faux_central.radios["ab" * 32]["connexion_type"] == "SERIE"
        assert faux_central.radios["ab" * 32]["serie_device"] == "COM5"
        spec, _, _ = p.ponts.lances[-1]
        assert dict(spec.env) == {"COMPAGNON_ID": radio.compagnon_id,
                                  "MESHCORE_CONNEXION_TYPE": "SERIE",
                                  "MESHCORE_SERIE_DEVICE": "COM5"}
        assert p.etats() == {radio.compagnon_id: "MARCHE"}

    def test_bluetooth_et_reseau_local(self, faux_central):
        p = passerelle_prete(faux_central, {
            ("ble", "AA:BB", "MESHTASTIC"): TBEAM,
            "ip": lambda a: {**HELTEC, "port": 5000},
        })

        ble = p.identifier("BLE", "AA:BB", "MESHTASTIC")
        p.connecter(ble)
        assert faux_central.radios[0x0BADCAFE]["ble_adresse"] == "AA:BB"

        ip = p.identifier("TCP", "192.168.1.50")
        assert ip["adresse"] == "192.168.1.50:5000"       # le port trouvé est retenu
        p.connecter(ip)
        assert faux_central.radios["ab" * 32]["tcp_port"] == 5000

    def test_une_radio_muette_donne_un_conseil_pas_une_trace_technique(self, faux_central):
        p = passerelle_prete(faux_central, {("usb", "COM9"): None})
        with pytest.raises(ErreurPasserelle, match="câble"):
            p.identifier("USB", "COM9")

    def test_un_seul_pont_pour_toutes_les_radios_meshtastic(self, faux_central):
        p = passerelle_prete(faux_central)
        p.connecter({**TBEAM, "transport": "USB", "adresse": "COM3"})
        p.connecter({"protocole": "MESHTASTIC", "identite": {"node_num": 7}, "nom": "Rak",
                     "transport": "BLE", "adresse": "CC:DD"})

        assert [s.cle for s in specs(p.config)] == ["meshtastic"]

    def test_ajouter_une_radio_meshtastic_relance_le_pont_sans_attendre(self, faux_central):
        p = passerelle_prete(faux_central)
        p.connecter({**TBEAM, "transport": "USB", "adresse": "COM3"})
        avant = len(p.ponts.lances)
        p.connecter({"protocole": "MESHTASTIC", "identite": {"node_num": 7}, "nom": "Rak",
                     "transport": "BLE", "adresse": "CC:DD"})
        assert len(p.ponts.lances) == avant + 1

    def test_le_bluetooth_cherche_sans_reproposer_les_radios_deja_la(self, faux_central):
        trouvees = [{"adresse": "AA:BB", "nom": "T-Beam", "protocole": "MESHTASTIC", "signal": -60},
                    {"adresse": "CC:DD", "nom": "MeshCore-1", "protocole": "MESHCORE", "signal": -70}]
        p = passerelle_prete(faux_central, {"ble-chercher": trouvees})
        p.connecter({**TBEAM, "transport": "BLE", "adresse": "AA:BB"})

        assert [r["adresse"] for r in p.chercher_bluetooth()] == ["CC:DD"]

    def test_les_ports_tenus_par_un_pont_sont_marques(self, faux_central):
        ports = [{"port": "COM5", "description": "CP210x"}, {"port": "COM6", "description": "CH340"}]
        p = passerelle_prete(faux_central, {"ports": ports})
        p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})

        assert [(x["port"], x["radio"]) for x in p.ports_usb()] == [("COM5", "Heltec V3"), ("COM6", None)]


class TestLePortComChange:
    """Windows attribue un autre numéro de port selon la prise USB utilisée."""

    def test_la_radio_est_retrouvee_sur_son_nouveau_port(self, faux_central):
        p = passerelle_prete(faux_central, {
            "ports": [{"port": "COM7", "description": "CP210x"}],
            ("usb", "COM7"): HELTEC,
        })
        ancienne = p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})

        deplacees = p.rattraper_ports_usb()

        assert [r.adresse for r in deplacees] == ["COM7"]
        assert len(p.config.radios) == 1                       # mise à jour, pas doublée
        assert p.config.radios[0].compagnon_id == ancienne.compagnon_id
        assert faux_central.radios["ab" * 32]["serie_device"] == "COM7"

    def test_on_ne_sonde_jamais_un_port_tenu_par_une_radio_presente(self, faux_central):
        sondeur_ports = [{"port": "COM5", "description": ""}, {"port": "COM8", "description": ""}]
        p = passerelle_prete(faux_central, {"ports": sondeur_ports, ("usb", "COM8"): TBEAM})
        p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})
        p.connecter({**TBEAM, "transport": "USB", "adresse": "COM3"})     # COM3 a disparu

        p.rattraper_ports_usb()

        assert ["usb", "COM5"] not in p._sonder.demandes
        assert ["usb", "COM8"] in p._sonder.demandes

    def test_rien_a_faire_quand_tout_est_a_sa_place(self, faux_central):
        p = passerelle_prete(faux_central, {"ports": [{"port": "COM5", "description": ""}]})
        p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})
        assert p.rattraper_ports_usb() == []


class TestRetirer:
    def test_retirer_arrete_le_pont_et_previent_le_central(self, faux_central):
        p = passerelle_prete(faux_central)
        radio = p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})
        processus = p.ponts.lances[-1][2]

        p.retirer(radio.compagnon_id)

        assert processus.vivant is False
        assert p.config.radios == []
        assert ("POST", f"/api/compagnons-meshcore/{radio.compagnon_id}/retirer-du-satellite/", {}) \
            in faux_central.appels


# ══ Marche et arrêt ═══════════════════════════════════════════════════════════

class TestArretALaFermeture:
    def test_fermer_arrete_tous_les_ponts_et_le_dit_au_central(self, faux_central):
        p = passerelle_prete(faux_central)
        a = p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})
        b = p.connecter({**TBEAM, "transport": "BLE", "adresse": "AA:BB"})
        processus = [x[2] for x in p.ponts.lances]

        p.arreter()

        assert not any(x.vivant for x in processus)
        arrets = [c for (_, c, corps) in faux_central.appels if corps == {"etat": "DECONNECTE"}]
        assert len(arrets) == 2 and a.compagnon_id in arrets[0] and b.compagnon_id in arrets[1]

    def test_relancer_l_application_reprend_ses_radios(self, faux_central):
        p = passerelle_prete(faux_central)
        p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})
        p.arreter()

        relancee = Passerelle(sonder=faux_sondeur({}), ponts=FauxPonts())
        relancee.demarrer()

        assert [s.cle for s, _, _ in relancee.ponts.lances] == [f"meshcore-radio-{'ab' * 32}"]


class TestSurveillanceDesPonts:
    def test_un_pont_tombe_est_relance_apres_un_delai(self):
        ponts = FauxPonts()
        ponts.configurer(CENTRAL, "e", "m")
        ponts.synchroniser([Spec("meshtastic", "MESHTASTIC", ())])
        ponts.lances[0][2].vivant = False

        assert ponts.surveiller() == {"meshtastic": "RELANCE"}
        assert len(ponts.lances) == 1                    # pas tout de suite
        ponts.maintenant += 20
        ponts.surveiller()
        assert len(ponts.lances) == 2
        assert ponts.surveiller() == {"meshtastic": "MARCHE"}

    def test_synchroniser_deux_fois_ne_relance_rien(self):
        ponts = FauxPonts()
        ponts.configurer(CENTRAL, "e", "m")
        voulu = [Spec("meshcore-1", "MESHCORE", (("COMPAGNON_ID", "1"),))]
        ponts.synchroniser(voulu)
        ponts.synchroniser(voulu)
        assert len(ponts.lances) == 1


class TestLeLanceurMeurtAvecLApplication:
    def test_le_pont_s_arrete_quand_le_tuyau_se_ferme(self, tmp_path):
        """Le vrai lanceur, sur un faux pont qui ne s'arrêterait jamais de lui-même : c'est ce
        qui évite un pont orphelin quand l'application est tuée sans pouvoir faire le ménage."""
        script = tmp_path / "bridge.py"
        script.write_text("import time\nprint('demarre', flush=True)\ntime.sleep(600)\n")
        racine = Path(__file__).resolve().parent.parent
        processus = subprocess.Popen(
            [sys.executable, "-m", "passerelle.lanceur", str(script)], cwd=str(racine),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        assert processus.stdout.readline().strip() == b"demarre"

        processus.stdin.close()          # ce que fait le système quand l'application disparaît

        assert processus.wait(timeout=10) == 0


    def test_un_pont_qui_s_arrete_seul_sort_proprement(self, tmp_path):
        """Régression : le fil de garde tenait le verrou de stdin, et l'arrêt normal d'un pont
        se terminait en « Fatal Python error » dans son journal."""
        script = tmp_path / "bridge.py"
        script.write_text("print('fini')\n")
        racine = Path(__file__).resolve().parent.parent
        sortie = subprocess.run(
            [sys.executable, "-m", "passerelle.lanceur", str(script)], cwd=str(racine),
            stdin=subprocess.PIPE, capture_output=False, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=20)
        assert sortie.returncode == 0
        assert b"Fatal Python error" not in sortie.stderr


# ══ Sonde ═════════════════════════════════════════════════════════════════════

class TestSonde:
    def test_meshcore_d_abord_meshtastic_ensuite(self):
        ordre = []
        mc = lambda t, a: ordre.append("mc") or None            # noqa: E731
        mt = lambda t, a: ordre.append("mt") or TBEAM           # noqa: E731

        assert sonde.sonder_usb("COM5", meshcore=mc, meshtastic=mt) == TBEAM
        assert ordre == ["mc", "mt"]

    def test_par_adresse_sans_port_on_essaie_celui_de_chaque_protocole(self):
        essais = []
        mt = lambda t, a: essais.append(("mt", a)) or None       # noqa: E731
        mc = lambda t, a: essais.append(("mc", a)) or HELTEC     # noqa: E731

        resultat = sonde.sonder_ip("192.168.1.50", meshcore=mc, meshtastic=mt)

        assert essais == [("mt", ("192.168.1.50", 4403)), ("mc", ("192.168.1.50", 5000))]
        assert resultat["port"] == 5000

    def test_en_bluetooth_seul_le_protocole_annonce_est_essaye(self):
        appels = []
        mc = lambda t, a: appels.append("mc") or HELTEC          # noqa: E731
        mt = lambda t, a: appels.append("mt") or TBEAM           # noqa: E731

        sonde.sonder_ble("AA:BB", "MESHTASTIC", meshcore=mc, meshtastic=mt)
        assert appels == ["mt"]

    def test_reconnaitre_une_radio_a_son_annonce_bluetooth(self):
        assert sonde.protocole_ble("T-Beam_1234", [sonde.SERVICE_BLE_MESHTASTIC.upper()]) == "MESHTASTIC"
        assert sonde.protocole_ble("MeshCore-Heltec", [sonde.SERVICE_BLE_MESHCORE]) == "MESHCORE"
        # Le service UART Nordic seul ne suffit pas : bien d'autres appareils l'exposent.
        assert sonde.protocole_ble("Montre", [sonde.SERVICE_BLE_MESHCORE]) is None
        assert sonde.protocole_ble("Casque", []) is None

    def test_la_ligne_de_commande_repond_en_json_meme_en_cas_d_erreur(self):
        racine = Path(__file__).resolve().parent.parent
        sortie = subprocess.run([sys.executable, "-m", "passerelle.sonde", "inconnue"],
                                cwd=str(racine), capture_output=True, timeout=30)
        assert json.loads(sortie.stdout.decode().strip().splitlines()[-1])["ok"] is False

    def test_lister_les_ports_ne_plante_pas_sans_aucune_radio(self):
        assert isinstance(sonde.lister_ports(), list)


def test_identite_texte():
    assert identite_texte("MESHTASTIC", {"node_num": 0x0BADCAFE}) == "!0badcafe"
    assert identite_texte("MESHCORE", {"pubkey_hex": "AB" * 32}) == "ab" * 32


def test_la_version_distribuee_par_le_central(faux_central, monkeypatch):
    assert central.derniere_version(CENTRAL) is None          # 404 : on ne sait pas, on continue
