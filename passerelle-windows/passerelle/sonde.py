"""Interroger une radio pour savoir ce qu'elle est : protocole, identité, nom.

Exécuté dans un PROCESSUS À PART (`python -m passerelle.sonde …`, une ligne JSON en sortie) et
non dans l'application : les bibliothèques radio peuvent rester bloquées très longtemps face à un
appareil qui ne parle pas leur protocole, et un processus se tue proprement à l'échéance — un fil
d'exécution, non. C'est aussi ce qui garde la fenêtre réactive.

Mêmes séquences que `satellite/detecter_noeud_serie.py` et `MeshLocalDetecterView`, déjà
éprouvées : MeshCore d'abord (rapide à écarter), Meshtastic ensuite.

Demande de Sylvain du 15/11/2026 : **pas de recherche automatique en Bluetooth ni sur le
réseau** — c'est la personne qui dit « cette radio-là » ou « cette adresse-là ». Seul l'USB est
listé tout seul, parce que c'est simple et sans ambiguïté.
"""
import asyncio
import json
import sys
import threading

DELAI_SONDE = 8.0
PORT_MESHTASTIC = 4403
PORT_MESHCORE = 5000

SERVICE_BLE_MESHTASTIC = "6ba1b218-15a8-461f-9fa8-5dcae273eafd"
SERVICE_BLE_MESHCORE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"


# ══ MeshCore ══════════════════════════════════════════════════════════════════

async def _meshcore(creer, delai):
    from meshcore import EventType

    async def essai():
        mc = await creer()
        try:
            resultat = await mc.commands.send_appstart()
            if resultat and resultat.type == EventType.SELF_INFO:
                infos = resultat.payload or {}
                cle = infos.get("public_key") or infos.get("pubkey")
                if cle:
                    return {"protocole": "MESHCORE", "identite": {"pubkey_hex": cle},
                            "nom": (infos.get("name") or "").strip()}
        finally:
            await mc.disconnect()
        return None

    try:
        return await asyncio.wait_for(essai(), timeout=delai + 2)
    except Exception:
        return None


def sonder_meshcore(transport, adresse, delai=DELAI_SONDE):
    from meshcore import MeshCore

    if transport == "USB":
        creer = lambda: MeshCore.create_serial(adresse, 115200, default_timeout=delai)   # noqa: E731
    elif transport == "BLE":
        creer = lambda: MeshCore.create_ble(adresse)                                    # noqa: E731
    else:
        hote, port = adresse
        creer = lambda: MeshCore.create_tcp(hote, port, default_timeout=delai)           # noqa: E731
    return asyncio.run(_meshcore(creer, delai))


# ══ Meshtastic ════════════════════════════════════════════════════════════════

def sonder_meshtastic(transport, adresse, delai=DELAI_SONDE):
    """Dans un fil borné : la bibliothèque officielle attend jusqu'à 300 s un appareil qui ne
    répond pas."""
    resultat = {}

    def essai():
        iface = None
        try:
            if transport == "USB":
                from meshtastic.serial_interface import SerialInterface
                iface = SerialInterface(devPath=adresse)
            elif transport == "BLE":
                from meshtastic.ble_interface import BLEInterface
                iface = BLEInterface(address=adresse)
            else:
                from meshtastic.tcp_interface import TCPInterface
                hote, port = adresse
                iface = TCPInterface(hostname=hote, portNumber=port, timeout=int(delai))
            info = iface.myInfo
            if info is not None and getattr(info, "my_node_num", None):
                resultat["node_num"] = info.my_node_num
                try:
                    resultat["nom"] = iface.getLongName() or ""
                except Exception:
                    resultat["nom"] = ""
        except Exception:
            pass
        finally:
            if iface is not None:
                try:
                    iface.close()
                except Exception:
                    pass

    fil = threading.Thread(target=essai, daemon=True)
    fil.start()
    # Le Bluetooth est lent à s'établir : on lui laisse le double.
    fil.join(timeout=delai * (2 if transport == "BLE" else 1))
    if not resultat.get("node_num"):
        return None
    return {"protocole": "MESHTASTIC", "identite": {"node_num": resultat["node_num"]},
            "nom": resultat.get("nom", "")}


# ══ Par liaison ═══════════════════════════════════════════════════════════════

def lister_ports():
    """Les ports série présents, avec la description que Windows en donne (« USB-SERIAL CH340 »,
    « Silicon Labs CP210x »…) : c'est elle qui aide un non-averti à reconnaître sa radio."""
    from serial.tools import list_ports

    return [{"port": p.device, "description": (p.description or "").strip()}
            for p in sorted(list_ports.comports(), key=lambda p: p.device)]


def sonder_usb(port, meshcore=sonder_meshcore, meshtastic=sonder_meshtastic):
    return meshcore("USB", port) or meshtastic("USB", port)


def sonder_ble(adresse, protocole, meshcore=sonder_meshcore, meshtastic=sonder_meshtastic):
    """Le protocole est connu d'avance : la recherche Bluetooth l'a lu dans l'annonce de la
    radio. Inutile, et lent, d'essayer l'autre."""
    return (meshtastic if protocole == "MESHTASTIC" else meshcore)("BLE", adresse)


def sonder_ip(hote, port=None, meshcore=sonder_meshcore, meshtastic=sonder_meshtastic):
    """Sans port, on essaie celui de chaque protocole : 4403 (Meshtastic) puis 5000 (MeshCore).
    Renvoie aussi le port retenu — c'est lui qu'il faudra donner au pont."""
    essais = ([(meshtastic, PORT_MESHTASTIC), (meshcore, PORT_MESHCORE)] if not port
              else [(meshtastic, int(port)), (meshcore, int(port))])
    for sonde, p in essais:
        resultat = sonde("TCP", (hote, p))
        if resultat:
            return {**resultat, "port": p}
    return None


def protocole_ble(nom, services):
    """Le protocole d'une radio d'après son annonce Bluetooth, ou None si ce n'en est pas une.

    Le service UART Nordic qu'utilise MeshCore est générique (d'autres appareils l'exposent) :
    on ne s'y fie que si le nom annonce aussi « MeshCore »."""
    services = {s.lower() for s in (services or [])}
    if SERVICE_BLE_MESHTASTIC in services:
        return "MESHTASTIC"
    if (nom or "").lower().startswith("meshcore"):
        return "MESHCORE"
    return None


def chercher_ble(duree=8.0):
    """Les radios Bluetooth à portée — à la demande seulement, jamais en tâche de fond."""
    from bleak import BleakScanner

    async def chercher():
        trouves = await BleakScanner.discover(timeout=duree, return_adv=True)
        radios = []
        for appareil, annonce in trouves.values():
            nom = annonce.local_name or appareil.name or ""
            protocole = protocole_ble(nom, annonce.service_uuids)
            if protocole:
                radios.append({"adresse": appareil.address, "nom": nom or appareil.address,
                               "protocole": protocole, "signal": annonce.rssi})
        return sorted(radios, key=lambda r: -(r["signal"] or -999))

    return asyncio.run(chercher())


# ══ Ligne de commande ═════════════════════════════════════════════════════════

def executer(arguments):
    commande, reste = arguments[0], arguments[1:]
    if commande == "ports":
        return lister_ports()
    if commande == "usb":
        return sonder_usb(reste[0])
    if commande == "ble-chercher":
        return chercher_ble()
    if commande == "ble":
        return sonder_ble(reste[0], reste[1])
    if commande == "ip":
        return sonder_ip(reste[0], reste[1] if len(reste) > 1 and reste[1] else None)
    raise ValueError(f"commande inconnue : {commande}")


if __name__ == "__main__":
    try:
        sortie = {"ok": True, "resultat": executer(sys.argv[1:])}
    except Exception as erreur:   # tout est rapporté à l'application, rien ne s'affiche ici
        sortie = {"ok": False, "erreur": str(erreur) or type(erreur).__name__}
    sys.stdout.write(json.dumps(sortie) + "\n")
    sys.stdout.flush()
    # Certaines bibliothèques laissent des fils non-démons : on sort sans les attendre.
    import os
    os._exit(0)
