#!/usr/bin/env python3
"""Écran d'état du satellite, à la manière de Home Assistant OS : sur l'écran branché à la
machine (console tty1), en permanence, ce qu'il faut savoir sans se connecter.

    python3 ecran_etat.py              # une fois, dans le terminal
    python3 ecran_etat.py --boucle     # en continu (service assista-satellite-ecran)

Ce qu'il montre : en fonctionnement ou non, l'adresse IP et l'URL de l'application locale,
la liaison avec le central, la machine (charge, mémoire, disque, température), la version et
l'état des mises à jour. Ce qu'il ne montre JAMAIS : un mot de passe ou un jeton. L'écran est
visible de quiconque passe devant ; le compte admin local se réaffiche dans un terminal
(`./installer.sh acces-web`).

Bibliothèque standard seulement : il tourne sur la machine, hors conteneur, comme l'agent de
mise à jour, dont il réutilise la lecture du .env et de l'état de la machine.
"""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_mise_a_jour as agent  # noqa: E402

REPERTOIRE = Path(__file__).resolve().parent
LARGEUR = 78
FICHIER_CONNECTIVITE = "/var/run/satellite/etat_connectivite.json"

VERT, ORANGE, ROUGE, GRIS, GRAS, FIN = "\033[32m", "\033[33m", "\033[31m", "\033[90m", "\033[1m", "\033[0m"

STATUTS = {"REUSSIE": ("réussie", VERT), "ECHOUEE": ("échouée", ROUGE), "EN_COURS": ("en cours", ORANGE),
           "REFUSEE": ("refusée", ROUGE), "ANNULEE": ("annulée", GRIS)}


# ── Collecte ─────────────────────────────────────────────────────────────────────────────────

def _commande(arguments, executer=subprocess.run, delai=8):
    try:
        resultat = executer(arguments, capture_output=True, timeout=delai, check=False)
        return resultat.returncode, resultat.stdout.decode(errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def adresses_ip(sortie_ip):
    """[(interface, adresse)] des IPv4 de la machine, hors boucle locale et réseaux de Docker
    (même règle que `ips_privees` dans installer.sh)."""
    adresses = []
    for ligne in sortie_ip.splitlines():
        morceaux = ligne.split()
        if len(morceaux) < 4 or morceaux[2] != "inet":
            continue
        interface = morceaux[1]
        if interface.startswith(("lo", "docker", "br-", "veth", "virbr")):
            continue
        adresses.append((interface, morceaux[3].split("/")[0]))
    return adresses


def services(sortie_ps):
    """(en marche, total, [arrêtés]) d'après `docker compose ps --format json`, qui rend selon
    les versions un tableau ou un objet par ligne."""
    sortie_ps = sortie_ps.strip()
    if not sortie_ps:
        return 0, 0, []
    try:
        lignes = json.loads(sortie_ps)
        lignes = lignes if isinstance(lignes, list) else [lignes]
    except ValueError:
        lignes = []
        for ligne in sortie_ps.splitlines():
            try:
                lignes.append(json.loads(ligne))
            except ValueError:
                continue
    en_marche, arretes = 0, []
    for service in lignes:
        nom = service.get("Service") or service.get("Name") or "?"
        if (service.get("State") or "").lower() == "running" and (service.get("Health") or "") != "unhealthy":
            en_marche += 1
        else:
            arretes.append(nom)
    return en_marche, len(lignes), arretes


def _temperature(racine="/sys/class/thermal"):
    try:
        return int(Path(racine, "thermal_zone0", "temp").read_text().strip()) / 1000
    except (OSError, ValueError):
        return None


def _allumee_depuis(proc="/proc"):
    try:
        return float(Path(proc, "uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def collecter(repertoire=REPERTOIRE, executer=subprocess.run, proc="/proc"):
    repertoire = Path(repertoire)
    env = agent.lire_env(repertoire / ".env")
    try:
        profil = (repertoire / ".profil").read_text(encoding="utf-8").strip() or "gw"
    except OSError:
        profil = "gw"
    compose = ["docker", "compose", "--project-directory", str(repertoire), "--profile", profil]

    _, version = _commande(["git", "-C", str(repertoire.parent), "log", "-1", "--format=%h|%cs"], executer)
    _, sortie_ip = _commande(["ip", "-4", "-o", "addr", "show"], executer)
    code_ps, sortie_ps = _commande([*compose, "ps", "--format", "json"], executer, delai=15)
    code_cx, sortie_cx = _commande([*compose, "exec", "-T", "etat-connectivite", "cat", FICHIER_CONNECTIVITE],
                                   executer, delai=10)
    code_minuteur, _ = _commande(["systemctl", "is-active", "--quiet", "assista-satellite-maj.timer"], executer)
    try:
        connectivite = json.loads(sortie_cx) if code_cx == 0 else None
    except ValueError:
        connectivite = None
    try:
        disque = shutil.disk_usage(repertoire).free / 1e9
    except OSError:
        disque = None
    morceaux_version = version.strip().split("|")
    return {
        "nom": env.get("SATELLITE_NOM") or socket.gethostname(),
        "hote": socket.gethostname(),
        "profil": profil,
        "central_url": (env.get("CENTRAL_URL") or "").rstrip("/"),
        "port_web": env.get("WEB_PORT") or "80",
        "version": morceaux_version[0] if morceaux_version and morceaux_version[0] else "",
        "date_version": morceaux_version[1] if len(morceaux_version) > 1 else "",
        "adresses": adresses_ip(sortie_ip),
        "services": services(sortie_ps) if code_ps == 0 else None,
        "connectivite": connectivite,
        "systeme": agent.etat_de_la_machine(proc),
        "disque_go": disque,
        "temperature": _temperature(),
        "allumee_depuis": _allumee_depuis(proc),
        "agent": agent._lire_json(repertoire / agent.FICHIER_ETAT_AGENT) or {},
        "agent_actif": code_minuteur == 0,
    }


# ── Mise en page ─────────────────────────────────────────────────────────────────────────────

def duree(secondes):
    """« 3 j 4 h », « 2 h 05 », « 7 min », « 40 s »."""
    if secondes is None:
        return "?"
    secondes = int(max(0, secondes))
    if secondes >= 86400:
        return f"{secondes // 86400} j {secondes % 86400 // 3600} h"
    if secondes >= 3600:
        return f"{secondes // 3600} h {secondes % 3600 // 60:02d}"
    if secondes >= 60:
        return f"{secondes // 60} min"
    return f"{secondes} s"


def _date(horodatage):
    return time.strftime("%d/%m à %H:%M", time.localtime(horodatage)) if horodatage else "?"


def systeme_court(texte):
    """« charge 0.4 ; mémoire libre 900 Mo ; swap 1.8/2.0 Go » : la forme courte de
    agent.etat_de_la_machine, dont la forme longue sert aux comptes rendus envoyés au central."""
    texte = (texte or "?").replace("mémoire disponible", "mémoire libre").replace("swap utilisé ", "swap ")
    if " Go sur " in texte:
        texte = texte.replace(" Go sur ", "/") + " Go"
    return texte


def composer(etat, maintenant=None, couleurs=True):
    maintenant = maintenant or time.time()
    c = (lambda texte, couleur: f"{couleur}{texte}{FIN}") if couleurs else (lambda texte, couleur: texte)
    puce = lambda couleur: c("●", couleur)  # noqa: E731
    lignes = []
    ligne = lambda titre, valeur: lignes.append(f" {titre:<15} {valeur}")  # noqa: E731
    trait = " " + "─" * (LARGEUR - 2)

    profil = "complet" if etat.get("profil") == "full" else "passerelle radio"
    titre = f" ASSISTA-CRISE · satellite « {etat.get('nom', '?')} »"
    lignes.append(c(titre, GRAS) + " " * max(1, LARGEUR - len(titre) - len(profil) - 1) + c(profil, GRIS))
    lignes.append(trait)

    # Fonctionnement
    agent_etat = etat.get("agent") or {}
    en_cours = agent_etat.get("en_cours")
    svc = etat.get("services")
    if en_cours:
        ligne("État", f"{puce(ORANGE)} Mise à jour en cours")
    elif svc is None:
        ligne("État", f"{puce(ROUGE)} Docker ne répond pas")
    else:
        en_marche, total, arretes = svc
        if total and en_marche == total:
            ligne("État", f"{puce(VERT)} En fonctionnement  {c(f'({en_marche}/{total} services)', GRIS)}")
        elif en_marche:
            ligne("État", f"{puce(ORANGE)} Dégradé : {', '.join(arretes[:4])} à l'arrêt  {c(f'({en_marche}/{total})', GRIS)}")
        else:
            ligne("État", f"{puce(ROUGE)} Arrêté  {c('(relancer : ./installer.sh demarrer)', GRIS)}")

    cx = etat.get("connectivite")
    central = etat.get("central_url") or "?"
    if cx is None:
        ligne("Central", f"{puce(GRIS)} état inconnu  {c(central, GRIS)}")
    elif cx.get("en_ligne"):
        ligne("Central", f"{puce(VERT)} Joignable depuis {duree(maintenant - cx.get('depuis', maintenant))}  {c(central, GRIS)}")
    else:
        ligne("Central", f"{puce(ROUGE)} Injoignable depuis {duree(maintenant - cx.get('depuis', maintenant))}"
                         f" — le satellite travaille seul  {c(central, GRIS)}")
    lignes.append("")

    # Accès
    adresses = etat.get("adresses") or []
    port = str(etat.get("port_web") or "80")
    suffixe = "" if port == "80" else f":{port}"
    if etat.get("profil") == "full":
        lignes.append(" " + c("Ouvrir l'application", GRAS) + " depuis un téléphone ou un PC du même réseau :")
        for _, adresse in adresses[:3]:
            lignes.append(f"     {c(f'http://{adresse}{suffixe}/', GRAS)}")
        if not adresses:
            lignes.append(f"     {c('aucune adresse réseau : vérifiez le câble ou le Wi-Fi', ROUGE)}")
    else:
        lignes.append(" Passerelle radio : pas d'application locale sur ce profil.")
    ligne("Adresse IP", "  ".join(f"{a} ({i})" for i, a in adresses) or c("aucune", ROUGE))
    lignes.append("")

    # Machine
    ligne("Machine", f"{etat.get('hote', '?')} · allumée depuis {duree(etat.get('allumee_depuis'))}")
    ligne("Système", systeme_court(etat.get("systeme")))
    systeme = []
    if etat.get("disque_go") is not None:
        couleur = ROUGE if etat["disque_go"] < 5 else (ORANGE if etat["disque_go"] < 15 else None)
        texte = f"{etat['disque_go']:.0f} Go libres"
        systeme.append(c(texte, couleur) if couleur else texte)
    if etat.get("temperature") is not None:
        couleur = ROUGE if etat["temperature"] >= 80 else (ORANGE if etat["temperature"] >= 70 else None)
        texte = f"température {etat['temperature']:.0f} °C"
        systeme.append(c(texte, couleur) if couleur else texte)
    if systeme:
        ligne("Disque", " ; ".join(systeme))
    lignes.append("")

    # Version et mises à jour
    date_version = etat.get("date_version") or ""
    if len(date_version) == 10:
        date_version = f"du {date_version[8:10]}/{date_version[5:7]}/{date_version[:4]}"
    ligne("Version", f"{etat.get('version') or '?'} {date_version}".rstrip())
    passage = agent_etat.get("dernier_passage")
    if not etat.get("agent_actif"):
        ligne("Mises à jour", f"{puce(ORANGE)} agent arrêté, pas de mise à jour à distance")
        lignes.append(f" {'':<15} {c('Le remettre en service : ./installer.sh demarrer', GRIS)}")
    elif passage:
        ligne("Mises à jour", f"{puce(VERT if agent_etat.get('central_joint', True) else ORANGE)} agent actif · "
                              f"dernier passage il y a {duree(maintenant - passage)} ({agent_etat.get('resultat', '?')})")
    else:
        ligne("Mises à jour", f"{puce(GRIS)} agent actif · pas encore passé")
    if en_cours:
        lignes.append(f" {'':<15} {c('En cours', ORANGE)} : {en_cours.get('version', '')} — {en_cours.get('etape', '')}"
                      f" (depuis {duree(maintenant - en_cours.get('depuis', maintenant))})")
    derniere = agent_etat.get("derniere_operation")
    if derniere:
        libelle, couleur = STATUTS.get(derniere.get("statut", ""), (derniere.get("statut", "?").lower(), GRIS))
        quoi = "Mise à jour" if derniere.get("quoi") == "MISE_A_JOUR" else derniere.get("quoi", "").capitalize()
        version = f" vers {derniere['version']}" if derniere.get("version") else ""
        lignes.append(f" {'':<15} Dernière : {quoi}{version} {c(libelle, couleur)} le {_date(derniere.get('fin'))}")
        if derniere.get("statut") != "REUSSIE" and derniere.get("etape"):
            lignes.append(f" {'':<15} {c(derniere['etape'][:LARGEUR - 18], GRIS)}")

    lignes.append(trait)
    lignes.append(c(" Compte admin local : ./installer.sh acces-web      Autre console : Alt+F2", GRIS))
    lignes.append(c(f" Actualisé le {time.strftime('%d/%m/%Y à %H:%M:%S', time.localtime(maintenant))}", GRIS))
    return [couper(l) for l in lignes]


def couper(ligne, largeur=LARGEUR + 2):
    """Coupe une ligne à `largeur` caractères VISIBLES (les codes de couleur ne comptent pas) :
    une ligne trop longue repasserait à la ligne et décalerait tout l'écran."""
    visibles, sortie, i = 0, [], 0
    while i < len(ligne):
        if ligne[i] == "\033":
            fin = ligne.find("m", i)
            if fin == -1:
                break
            sortie.append(ligne[i:fin + 1])
            i = fin + 1
            continue
        if visibles >= largeur - 1 and len(ligne[i:].replace(FIN, "")) > 1:
            sortie.append("…" + (FIN if "\033" in ligne else ""))
            return "".join(sortie)
        sortie.append(ligne[i])
        visibles += 1
        i += 1
    return "".join(sortie)


def afficher(lignes, effacer):
    sortie = ("\033[H\033[2J" if effacer else "") + "\n".join(lignes) + "\n"
    sys.stdout.write(sortie)
    sys.stdout.flush()


def principal(arguments=None):
    options = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    options.add_argument("--boucle", action="store_true", help="actualiser en continu")
    options.add_argument("--intervalle", type=int, default=30, help="secondes entre deux actualisations")
    options.add_argument("--sans-couleur", action="store_true")
    options = options.parse_args(arguments)
    couleurs = not options.sans_couleur and (sys.stdout.isatty() or options.boucle)
    if not options.boucle:
        afficher(composer(collecter(), couleurs=couleurs), effacer=False)
        return 0
    os.environ.setdefault("TERM", "linux")
    while True:
        try:
            afficher(composer(collecter(), couleurs=couleurs), effacer=True)
        except Exception as erreur:  # noqa: BLE001 -- l'écran ne doit jamais s'éteindre
            afficher([f" Écran d'état : erreur de lecture ({erreur}). Nouvel essai dans {options.intervalle} s."], True)
        time.sleep(options.intervalle)


if __name__ == "__main__":
    sys.exit(principal())
