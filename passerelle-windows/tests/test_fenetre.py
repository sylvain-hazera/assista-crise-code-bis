"""La fenêtre, sur un écran virtuel : elle s'ouvre, passe d'un écran à l'autre, et se ferme en
arrêtant tout. Ignoré là où tkinter ou un écran manquent."""
import pytest

tk = pytest.importorskip("tkinter")

from test_passerelle import (CENTRAL, FauxPonts, HELTEC, faux_central, faux_sondeur,   # noqa: E402,F401
                             passerelle_prete)
from passerelle.fenetre import Fenetre                                               # noqa: E402
from passerelle.gestion import Passerelle                                            # noqa: E402


@pytest.fixture
def racine():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("pas d'écran")
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def tourner(racine, condition, essais=300):
    """Fait tourner la boucle de l'interface jusqu'à ce que `condition()` soit vraie."""
    import time
    for _ in range(essais):
        racine.update()
        if condition():
            return True
        time.sleep(0.01)
    return False


def textes(widget):
    trouves = []
    for enfant in widget.winfo_children():
        try:
            trouves.append(str(enfant.cget("text")))
        except tk.TclError:
            pass
        trouves += textes(enfant)
    return trouves


def test_premier_lancement_l_installeur_a_tout_fourni(racine, faux_central):
    """Rien à saisir : l'enrôlement part tout seul, puis la fenêtre attend la validation et
    bascule d'elle-même quand un administrateur valide."""
    p = Passerelle(sonder=faux_sondeur({"ports": []}), ponts=FauxPonts())
    f = Fenetre(p, premier_lancement={"central": CENTRAL, "jeton": "BON-CODE"}, racine=racine)

    assert tourner(racine, lambda: p.etat == "EN_ATTENTE" and f._ecran_affiche == "EN_ATTENTE")
    assert any("En attente de validation" in t for t in textes(racine))

    faux_central.valide = True
    f._battre()
    assert tourner(racine, lambda: f._ecran_affiche == "PRETE")
    assert any("Connecter en USB" in t for t in textes(racine))


def test_un_code_refuse_s_affiche_en_clair(racine, faux_central):
    p = Passerelle(sonder=faux_sondeur({}), ponts=FauxPonts())
    f = Fenetre(p, premier_lancement={"central": CENTRAL, "jeton": "FAUX"}, racine=racine)

    assert tourner(racine, lambda: "expiré" in f.message.get())
    assert p.etat == "NON_ENROLEE"


def test_les_radios_s_affichent_avec_leur_etat(racine, faux_central):
    p = passerelle_prete(faux_central, {"ports": [{"port": "COM5", "description": ""}]})
    p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})
    f = Fenetre(p, racine=racine)

    assert tourner(racine, lambda: "en marche" in f.message.get().lower() or f.table.get_children())
    ligne = f.table.item(f.table.get_children()[0])
    assert ligne["text"] == "Heltec V3"
    assert ligne["values"][0] == "MeshCore" and "COM5" in ligne["values"][1]
    assert "En marche" in ligne["values"][2]


def test_fermer_la_fenetre_arrete_les_ponts(racine, faux_central):
    p = passerelle_prete(faux_central, {"ports": [{"port": "COM5", "description": ""}]})
    p.connecter({**HELTEC, "transport": "USB", "adresse": "COM5"})
    f = Fenetre(p, racine=racine)
    tourner(racine, lambda: bool(f.table.get_children()))

    f.fermer()

    def detruite():
        try:
            return not racine.winfo_exists()
        except tk.TclError:
            return True
    import time
    for _ in range(600):
        try:
            racine.update()
        except tk.TclError:
            break
        if detruite():
            break
        time.sleep(0.01)
    assert not any(x[2].vivant for x in p.ponts.lances)
