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
import logging

logger = logging.getLogger("meshcore-bridge.admin")

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

MOYEN_MOT_DE_PASSE = "MOT_DE_PASSE"

# Opérations qui exigent une session ouverte sur le répéteur. Les requêtes binaires (`req_*`)
# n'en demandent pas : le firmware y répond à qui est dans l'ACL.
TACHES_PAR_COMMANDE = {
    RADIO_TEMPORAIRE: None,      # commande construite à partir des paramètres
    DEFINIR_REGLAGE: None,
    ANNONCER: "advert",
    REDEMARRER: "reboot",
}


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
        if not cle or " " in cle:
            raise ErreurAdminMeshCore(f"Clé de réglage invalide : {cle!r}.")
        return f"set {cle} {valeur}"

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

        if type_tache in (LIRE_STATUT, LIRE_VOISINS, LIRE_REGIONS, LIRE_TELEMETRIE):
            lecture = {
                LIRE_STATUT: meshcore.commands.req_status_sync,
                LIRE_VOISINS: meshcore.commands.req_neighbours_sync,
                LIRE_REGIONS: meshcore.commands.req_regions_sync,
                LIRE_TELEMETRIE: meshcore.commands.req_telemetry_sync,
            }[type_tache]
            resultat = await lecture(cible)
            if resultat is None:
                raise ErreurAdminMeshCore("Aucune réponse du répéteur.")
            return _lisible(resultat), None

        commande = construire_commande(tache)
        if commande is None:
            raise ErreurAdminMeshCore(f"Type de tâche inconnu du pont : {type_tache}.")

        await _ouvrir_session(meshcore, tache)
        resultat = await meshcore.commands.send_cmd(cible, commande)
        if resultat is None:
            raise ErreurAdminMeshCore("Commande envoyée sans réponse du répéteur.")
        return {"commande": commande, "reponse": _lisible(resultat)}, None

    except ErreurAdminMeshCore as erreur:
        return None, str(erreur)
    except Exception as erreur:            # noqa: BLE001 — remonté tel quel dans la tâche
        logger.exception("Échec d'une tâche d'administration MeshCore (%s).", type_tache)
        return None, f"{type(erreur).__name__}: {erreur}"
