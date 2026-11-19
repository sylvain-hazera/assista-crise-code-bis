"""Écran d'état du satellite (19/11/2026)."""
import json
import subprocess

import ecran_etat as ecran

MAINTENANT = 1_800_000_000.0

ETAT = {
    "nom": "Mairie de Saint-Exemple", "hote": "satellite-1", "profil": "full",
    "central_url": "https://assista-crise.fr", "port_web": "80",
    "version": "bc0f8c3f", "date_version": "2026-11-18",
    "adresses": [("eth0", "192.168.1.20")],
    "services": (12, 12, []),
    "connectivite": {"en_ligne": True, "depuis": MAINTENANT - 7200},
    "systeme": "charge 0.40 ; mémoire disponible 1200 Mo",
    "disque_go": 41.0, "temperature": 52.0, "allumee_depuis": 3 * 86400 + 4 * 3600,
    "agent": {"dernier_passage": MAINTENANT - 60, "resultat": "rien à faire", "central_joint": True},
    "agent_actif": True,
}


def _texte(etat, **surcharge):
    return "\n".join(ecran.composer({**etat, **surcharge}, maintenant=MAINTENANT, couleurs=False))


def test_l_essentiel_d_un_coup_d_oeil():
    texte = _texte(ETAT)
    assert "Mairie de Saint-Exemple" in texte.split("\n")[0] and "complet" in texte.split("\n")[0]
    assert "En fonctionnement" in texte and "12/12 services" in texte
    assert "http://192.168.1.20/" in texte and "192.168.1.20 (eth0)" in texte
    assert "Joignable depuis 2 h 00" in texte
    assert "bc0f8c3f du 18/11/2026" in texte
    assert "dernier passage il y a 1 min (rien à faire)" in texte
    assert "allumée depuis 3 j 4 h" in texte and "41 Go libres" in texte and "52 °C" in texte


def test_aucune_ligne_ne_deborde_d_un_ecran_de_80_colonnes():
    for ligne in ecran.composer(ETAT, maintenant=MAINTENANT, couleurs=False):
        assert len(ligne) <= 80, ligne
    # Même avec un résultat d'agent très long, et en couleurs (les codes ne comptent pas).
    import re
    long = {**ETAT, "agent": {**ETAT["agent"], "resultat": "ECHOUEE — " + "x" * 200}}
    for ligne in ecran.composer(long, maintenant=MAINTENANT, couleurs=True):
        assert len(re.sub(r"\033\[[0-9;]*m", "", ligne)) <= 80, ligne
    for ligne in ecran.composer(long, maintenant=MAINTENANT, couleurs=False):
        assert len(ligne) <= 80 and "\033" not in ligne and "[0m" not in ligne, ligne


def test_jamais_de_mot_de_passe(tmp_path):
    (tmp_path / ".env").write_text("SATELLITE_NOM=Essai\nSATELLITE_PASSWORD=Secret-Inventé-123\n"
                                   "DJANGO_SUPERUSER_PASSWORD=Autre-Secret-456\n")

    def executer(arguments, **options):
        return subprocess.CompletedProcess(arguments, 1, b"", b"")
    etat = ecran.collecter(tmp_path, executer=executer, proc=str(tmp_path))
    texte = "\n".join(ecran.composer(etat, couleurs=False))
    assert "Secret" not in texte and "Essai" in texte


def test_un_service_arrete_et_le_central_perdu_se_voient():
    texte = _texte(ETAT, services=(10, 12, ["backend", "nginx"]),
                   connectivite={"en_ligne": False, "depuis": MAINTENANT - 600})
    assert "Dégradé : backend, nginx à l'arrêt" in texte
    assert "Injoignable depuis 10 min" in texte and "travaille seul" in texte


def test_une_mise_a_jour_en_cours_puis_echouee():
    en_cours = _texte(ETAT, agent={**ETAT["agent"], "en_cours": {
        "version": "7127e7ce3c", "etape": "Construction en cours depuis 30 min", "depuis": MAINTENANT - 1800}})
    assert "Mise à jour en cours" in en_cours and "Construction en cours depuis 30 min" in en_cours
    echouee = _texte(ETAT, agent={**ETAT["agent"], "derniere_operation": {
        "quoi": "MISE_A_JOUR", "version": "7127e7ce3c", "statut": "ECHOUEE",
        "etape": "La construction a échoué. Le code a été remis à la version précédente.", "fin": MAINTENANT - 3600}})
    assert "Dernière : Mise à jour vers 7127e7ce3c échouée" in echouee
    assert "La construction a échoué" in echouee


def test_agent_arrete_et_passerelle_sans_application():
    texte = _texte(ETAT, agent_actif=False, profil="gw")
    assert "agent arrêté" in texte and "pas d'application locale" in texte and "http://" not in texte


def test_lecture_des_adresses_et_des_services():
    sortie_ip = ("1: lo    inet 127.0.0.1/8 scope host lo\n"
                 "2: eth0    inet 192.168.1.20/24 brd 192.168.1.255 scope global eth0\n"
                 "3: docker0    inet 172.17.0.1/16 scope global docker0\n"
                 "4: wlan0    inet 10.0.0.7/24 scope global wlan0\n")
    assert ecran.adresses_ip(sortie_ip) == [("eth0", "192.168.1.20"), ("wlan0", "10.0.0.7")]
    tableau = json.dumps([{"Service": "backend", "State": "running"}, {"Service": "db", "State": "exited"}])
    par_ligne = '{"Service": "backend", "State": "running"}\n{"Service": "web", "State": "running", "Health": "unhealthy"}'
    assert ecran.services(tableau) == (1, 2, ["db"])
    assert ecran.services(par_ligne) == (1, 2, ["web"])
    assert ecran.services("") == (0, 0, [])


def test_l_agent_note_son_etat_sans_s_arreter_sur_une_erreur(tmp_path):
    import agent_mise_a_jour as agent
    agent.noter_etat(tmp_path, dernier_passage=1.0, resultat="rien à faire")
    agent.noter_etat(tmp_path, en_cours={"etape": "Construction"})
    etat = json.loads((tmp_path / agent.FICHIER_ETAT_AGENT).read_text())
    assert etat == {"dernier_passage": 1.0, "resultat": "rien à faire", "en_cours": {"etape": "Construction"}}
    agent.noter_etat(tmp_path / "absent" / "x", resultat="ignoré")   # répertoire absent : aucune erreur


def test_les_durees():
    assert [ecran.duree(s) for s in (40, 420, 7500, 90000, None)] == ["40 s", "7 min", "2 h 05", "1 j 1 h", "?"]
