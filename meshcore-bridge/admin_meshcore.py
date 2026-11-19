"""Administration à distance des répéteurs MeshCore, exécutée par le pont.

Jumeau de `meshtastic-bridge/admin_meshtastic.py`, et la comparaison est instructive : les deux
protocoles répondent au même besoin avec des sécurités opposées.

**Ce que le firmware MeshCore garantit** (lu dans `meshcore-dev/MeshCore`,
`src/helpers/CommonCLI.cpp`, le 10/11/2026) :

- trois commandes sont **refusées à distance** par le firmware lui-même (garde
  `sender_timestamp == 0`) : `erase` (l. 280), `set freq` (l. 607, donc le changement de
  fréquence PERMANENT) et `set prv.key` (l. 711). On ne peut donc pas, par radio, rendre un
  répéteur définitivement sourd — ce qui était le cauchemar côté Meshtastic ;
- `tempradio <freq> <bw> <sf> <cr> <minutes>` (l. 252-266) applique des paramètres radio
  **temporairement**, avec un délai de retour obligatoire. C'est l'essai qui se rattrape tout
  seul, et c'est pourquoi toute modification radio passe par là.

**Ce qu'il ne garantit pas** : l'autorisation est un mot de passe (ou l'appartenance à l'ACL du
répéteur, `examples/simple_repeater/MyMesh.cpp:92-104`). Il n'y a aucun équivalent de
`security.admin_key` : qui a le mot de passe écrit. C'est pour cette raison que Django exige une
**preuve de contrôle** avant toute écriture, et que `VERIFIER_ACCES` existe.

Le mot de passe arrive avec la tâche, servi par l'API au seul pont qui vient de la verrouiller
pour son companion : le chercher lui-même l'obligerait à lire les rattachements des autres.
"""
import asyncio
import logging

logger = logging.getLogger("meshcore-bridge.admin")

#: Type de texte d'un message MeshCore portant la réponse d'une commande (`txt_type` 1, voir
#: meshcore/reader.py) : c'est par là que revient « OK », « > 869.525,62.5,8,5 » ou une erreur.
TXT_TYPE_CLI = 1
#: Délai d'attente de cette réponse : elle traverse la radio, aller et retour.
DELAI_REPONSE_CLI_S = 25

# Types de tâche, miroir de TypeTacheAdminMeshCore côté Django.
VERIFIER_ACCES = "VERIFIER_ACCES"
LIRE_STATUT = "LIRE_STATUT"
LIRE_VOISINS = "LIRE_VOISINS"
LIRE_REGIONS = "LIRE_REGIONS"
LIRE_TELEMETRIE = "LIRE_TELEMETRIE"
RADIO_TEMPORAIRE = "RADIO_TEMPORAIRE"
DEFINIR_REGLAGE = "DEFINIR_REGLAGE"
ANNONCER = "ANNONCER"
REDEMARRER = "REDEMARRER"
# 19/11/2026 : le reste de ce que MeshCore permet (miroir de TypeTacheAdminMeshCore).
LIRE_REGLAGE = "LIRE_REGLAGE"
LIRE_VERSION = "LIRE_VERSION"
LIRE_HORLOGE = "LIRE_HORLOGE"
LIRE_ACL = "LIRE_ACL"
LIRE_PROPRIETAIRE = "LIRE_PROPRIETAIRE"
SYNCHRO_HORLOGE = "SYNCHRO_HORLOGE"
CONNEXION_ROOM = "CONNEXION_ROOM"
DECONNECTER = "DECONNECTER"
LOCAL_STATISTIQUES = "LOCAL_STATISTIQUES"
LOCAL_REGLAGES = "LOCAL_REGLAGES"
LOCAL_CHEMIN_ANNONCE = "LOCAL_CHEMIN_ANNONCE"
LOCAL_DECOUVRIR_CHEMIN = "LOCAL_DECOUVRIR_CHEMIN"
LOCAL_NOM = "LOCAL_NOM"
LOCAL_POSITION = "LOCAL_POSITION"
LOCAL_PUISSANCE = "LOCAL_PUISSANCE"
LOCAL_RADIO = "LOCAL_RADIO"
LOCAL_SUPPRIMER_CONTACT = "LOCAL_SUPPRIMER_CONTACT"
LOCAL_REINIT_CHEMIN = "LOCAL_REINIT_CHEMIN"

MOYEN_MOT_DE_PASSE = "MOT_DE_PASSE"

# Opérations qui exigent une session ouverte sur le répéteur. Les requêtes binaires (`req_*`)
# n'en demandent pas : le firmware y répond à qui est dans l'ACL.
TACHES_PAR_COMMANDE = {
    RADIO_TEMPORAIRE: None,      # commande construite à partir des paramètres
    DEFINIR_REGLAGE: None,
    LIRE_REGLAGE: None,
    ANNONCER: "advert",
    REDEMARRER: "reboot",
    LIRE_VERSION: "ver",
    LIRE_HORLOGE: "clock",
    SYNCHRO_HORLOGE: "clock sync",
}
#: Commandes après lesquelles le répéteur ne répond pas toujours (il redémarre) : une absence de
#: réponse n'y est pas un échec.
SANS_REPONSE_ATTENDUE = {"reboot"}
#: Réglages jamais relus ni écrits : ils changent l'identité du nœud ou transportent un secret
#: (miroir de REGLAGES_MESHCORE_INTERDITS côté Django, revérifié ici).
REGLAGES_INTERDITS = {"prv.key", "public.key", "guest.password", "password"}


class ErreurAdminMeshCore(Exception):
    """Échec attendu et explicable : il remonte tel quel dans `erreur` de la tâche."""


def _nombre(valeur):
    """Format sans notation scientifique ni virgule décimale.

    Le firmware lit la fréquence avec `strtof` : une virgule française ou un `8.695e2` ne
    seraient pas compris, et la commande partirait quand même — pour revenir en
    « Error, invalid params » une minute plus tard."""
    texte = f"{float(valeur):.6f}".rstrip("0").rstrip(".")
    return texte or "0"


def construire_commande(tache):
    """Texte exact de la commande CLI à envoyer, ou None si la tâche n'en utilise pas.

    Isolée pour être testable sans appareil : c'est la seule partie où une erreur se traduit
    par un réglage faux sur du matériel réel."""
    type_tache = tache["type_tache"]
    parametres = tache.get("parametres") or {}

    if type_tache == RADIO_TEMPORAIRE:
        minutes = int(parametres["minutes"])
        if minutes <= 0:
            # Déjà refusé par l'API ; revérifié ici parce que c'est la garde qui fait qu'un
            # essai raté se rattrape tout seul, et qu'elle ne doit dépendre d'aucun appelant.
            raise ErreurAdminMeshCore(
                "Délai de retour obligatoire : sans lui, un essai radio raté ne revient pas."
            )
        return (
            f"tempradio {_nombre(parametres['frequence_mhz'])} "
            f"{_nombre(parametres['bande_khz'])} "
            f"{int(parametres['facteur_etalement'])} "
            f"{int(parametres['taux_codage'])} {minutes}"
        )

    if type_tache == DEFINIR_REGLAGE:
        cle = str(parametres["cle"]).strip()
        valeur = str(parametres["valeur"]).strip()
        if not cle or " " in cle or cle in REGLAGES_INTERDITS:
            raise ErreurAdminMeshCore(f"Clé de réglage invalide : {cle!r}.")
        return f"set {cle} {valeur}"

    if type_tache == LIRE_REGLAGE:
        cle = str(parametres.get("cle", "")).strip()
        if not cle or " " in cle or cle in REGLAGES_INTERDITS:
            raise ErreurAdminMeshCore(f"Clé de réglage invalide : {cle!r}.")
        return f"get {cle}"

    return TACHES_PAR_COMMANDE.get(type_tache)


def _lisible(evenement):
    """Rend l'événement de la bibliothèque sérialisable en JSON, sans le supposer d'une forme
    précise : les charges utiles varient d'une requête binaire à l'autre."""
    if evenement is None:
        return None
    charge = getattr(evenement, "payload", None)
    if charge is None:
        return {"brut": str(evenement)}
    if isinstance(charge, (dict, list, str, int, float, bool)):
        return charge
    if isinstance(charge, (bytes, bytearray)):
        return {"hex": bytes(charge).hex()}
    return {"brut": str(charge)}


async def _ouvrir_session(meshcore, tache):
    """Connexion au répéteur quand la tâche s'accompagne d'un mot de passe.

    Refaite à chaque tâche plutôt que mémorisée : une session MeshCore expire, le pont peut
    redémarrer entre deux opérations, et une session qu'on croit ouverte produit un échec
    silencieux bien plus coûteux qu'une connexion de trop."""
    if tache.get("moyen_admin") != MOYEN_MOT_DE_PASSE:
        return
    mot_de_passe = tache.get("mot_de_passe") or ""
    if not mot_de_passe:
        raise ErreurAdminMeshCore(
            "Ce répéteur est déclaré avec un mot de passe, mais l'API n'en a pas fourni."
        )
    resultat = await meshcore.commands.send_login_sync(tache["pubkey_cible"], mot_de_passe)
    if resultat is None:
        raise ErreurAdminMeshCore(
            "Connexion refusée par le répéteur : mot de passe faux, ou aucune réponse."
        )


async def _commande_texte(meshcore, cible, commande):
    """Envoie une commande au répéteur ET attend sa réponse texte (`txt_type` 1, venant de lui).

    L'attente est posée AVANT l'envoi : la réponse peut revenir avant que `send_cmd` ait rendu
    la main, et une attente posée après la manquerait. `send_cmd` ne rend qu'un accusé d'envoi :
    c'était ce qu'on rapportait jusqu'ici, jamais ce que le répéteur avait répondu."""
    from meshcore import EventType

    attente = asyncio.ensure_future(meshcore.wait_for_event(
        EventType.CONTACT_MSG_RECV,
        attribute_filters={"pubkey_prefix": cible[:12], "txt_type": TXT_TYPE_CLI},
        timeout=DELAI_REPONSE_CLI_S,
    ))
    try:
        envoi = await meshcore.commands.send_cmd(cible, commande)
    except Exception:
        attente.cancel()
        raise
    if envoi is None:
        attente.cancel()
        raise ErreurAdminMeshCore("Commande non partie : le companion ne l'a pas acceptée.")
    reponse = await attente
    texte = ((reponse.payload or {}).get("text") if reponse is not None else None)
    if texte is None and commande not in SANS_REPONSE_ATTENDUE:
        raise ErreurAdminMeshCore(
            f"« {commande} » est partie, mais le répéteur n'a pas répondu dans les "
            f"{DELAI_REPONSE_CLI_S} s.")
    return texte


def _cle_contact(tache):
    pubkey = str((tache.get("parametres") or {}).get("pubkey") or "").strip().lower()
    if len(pubkey) != 64:
        raise ErreurAdminMeshCore("Clé publique du contact manquante.")
    return pubkey


async def _executer_locale(meshcore, tache):
    """Opérations sur le nœud LOCAL (la passerelle qui exécute) : rien ne traverse la radio,
    sauf la découverte de chemin, qui l'interroge justement."""
    t = tache["type_tache"]
    p = tache.get("parametres") or {}
    c = meshcore.commands
    if t == LOCAL_STATISTIQUES:
        return {"systeme": _lisible(await c.get_stats_core()), "radio": _lisible(await c.get_stats_radio()),
                "paquets": _lisible(await c.get_stats_packets())}
    if t == LOCAL_REGLAGES:
        return {"appareil": _lisible(await c.send_device_query()), "reglages_fins": _lisible(await c.get_tuning()),
                "variables": _lisible(await c.get_custom_vars()), "telemetrie": _lisible(await c.get_self_telemetry())}
    if t == LOCAL_CHEMIN_ANNONCE:
        return _lisible(await c.get_advert_path(_cle_contact(tache)))
    if t == LOCAL_DECOUVRIR_CHEMIN:
        resultat = await c.send_path_discovery_sync(_cle_contact(tache))
        if resultat is None:
            raise ErreurAdminMeshCore("Aucun chemin trouvé : le contact n'a pas répondu.")
        return _lisible(resultat)
    if t == LOCAL_NOM:
        return _lisible(await c.set_name(str(p["nom"])))
    if t == LOCAL_POSITION:
        return _lisible(await c.set_coords(float(p["latitude"]), float(p["longitude"])))
    if t == LOCAL_PUISSANCE:
        return _lisible(await c.set_tx_power(int(p["dbm"])))
    if t == LOCAL_RADIO:
        if p.get("confirme") is not True:
            raise ErreurAdminMeshCore("Changement radio non confirmé : rien n'a été fait.")
        return _lisible(await c.set_radio(float(p["frequence_mhz"]), float(p["bande_khz"]),
                                          int(p["facteur_etalement"]), int(p["taux_codage"])))
    if t == LOCAL_SUPPRIMER_CONTACT:
        return _lisible(await c.remove_contact(_cle_contact(tache)))
    if t == LOCAL_REINIT_CHEMIN:
        return _lisible(await c.reset_path(_cle_contact(tache)))
    raise ErreurAdminMeshCore(f"Opération locale inconnue du pont : {t}.")


TACHES_LOCALES = {LOCAL_STATISTIQUES, LOCAL_REGLAGES, LOCAL_CHEMIN_ANNONCE, LOCAL_DECOUVRIR_CHEMIN,
                  LOCAL_NOM, LOCAL_POSITION, LOCAL_PUISSANCE, LOCAL_RADIO, LOCAL_SUPPRIMER_CONTACT,
                  LOCAL_REINIT_CHEMIN}


async def executer_tache(meshcore, tache):
    """Exécute une tâche et rend `(reponse, erreur)` — jamais les deux.

    `erreur` est un message destiné à l'exploitant : il s'affiche tel quel dans l'interface et
    il est le seul indice quand une opération échoue à trois minutes de distance."""
    type_tache = tache["type_tache"]
    cible = tache["pubkey_cible"]

    try:
        if type_tache == VERIFIER_ACCES:
            # La preuve elle-même. Deux voies, selon ce qui a été déclaré en réclamant le
            # répéteur : ouvrir une session, ou constater qu'il nous répond parce que notre
            # clé est dans son ACL.
            if tache.get("moyen_admin") == MOYEN_MOT_DE_PASSE:
                await _ouvrir_session(meshcore, tache)
                return {"preuve": "session ouverte"}, None
            resultat = await meshcore.commands.req_status_sync(cible)
            if resultat is None:
                raise ErreurAdminMeshCore(
                    "Le répéteur n'a pas répondu : notre clé publique n'est pas dans son ACL, "
                    "ou il est hors de portée."
                )
            return {"preuve": "repondu a une requete de statut", "statut": _lisible(resultat)}, None

        if type_tache in TACHES_LOCALES:
            return await _executer_locale(meshcore, tache), None

        if type_tache in (CONNEXION_ROOM, DECONNECTER, LIRE_ACL):
            if type_tache == DECONNECTER:
                return {"session": "fermée", "reponse": _lisible(await meshcore.commands.send_logout(cible))}, None
            await _ouvrir_session(meshcore, tache)
            if type_tache == CONNEXION_ROOM:
                # Le room server pousse alors ses messages à notre companion : ils arrivent
                # comme des messages directs, relayés par la boucle habituelle.
                return {"session": "ouverte"}, None
            resultat = await meshcore.commands.req_acl_sync(cible)
            if resultat is None:
                raise ErreurAdminMeshCore("Le répéteur n'a pas rendu sa liste d'accès (droits insuffisants ?).")
            return _lisible(resultat), None

        if type_tache in (LIRE_STATUT, LIRE_VOISINS, LIRE_REGIONS, LIRE_TELEMETRIE, LIRE_PROPRIETAIRE):
            # Par NOM, résolu au moment de l'appel : une table construite d'avance échouait dès
            # qu'une seule méthode manquait (bibliothèque plus ancienne), même pour lire un statut.
            lecture = getattr(meshcore.commands, {
                LIRE_STATUT: "req_status_sync",
                LIRE_VOISINS: "req_neighbours_sync",
                LIRE_REGIONS: "req_regions_sync",
                LIRE_TELEMETRIE: "req_telemetry_sync",
                LIRE_PROPRIETAIRE: "req_owner_sync",
            }[type_tache])
            resultat = await lecture(cible)
            if resultat is None:
                raise ErreurAdminMeshCore("Aucune réponse du répéteur.")
            return _lisible(resultat), None

        commande = construire_commande(tache)
        if commande is None:
            raise ErreurAdminMeshCore(f"Type de tâche inconnu du pont : {type_tache}.")

        await _ouvrir_session(meshcore, tache)
        texte = await _commande_texte(meshcore, cible, commande)
        return {"commande": commande, "reponse": texte}, None

    except ErreurAdminMeshCore as erreur:
        return None, str(erreur)
    except Exception as erreur:            # noqa: BLE001 — remonté tel quel dans la tâche
        logger.exception("Échec d'une tâche d'administration MeshCore (%s).", type_tache)
        return None, f"{type(erreur).__name__}: {erreur}"
