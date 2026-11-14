"""Relais série par le navigateur : un poste verrouillé devient passerelle radio.

Demande de Sylvain du 13/11/2026, sur un cas présenté le soir même : **une urgence sur un poste
où l'on ne peut rien installer** — PC de mairie sous contrôle informatique, pas de Docker, pas
d'exécutable, pas de pilote — **mais dont l'USB fonctionne**, et quelqu'un a un nœud LoRa.

Le profil `gw` du satellite répond déjà à « un PC qui sert de passerelle », et en mieux : c'est
un service, il survit au redémarrage, il gère les deux radios et le Wi-Fi. **Mais il exige
Docker.** Sur ce poste-là il est hors d'atteinte. C'est la seule situation qui justifie une
seconde voie, et elle ne la remplace pas.

**Ce que ce relais n'est pas** : un satellite. Il ajoute de la portée radio au central, il
n'ajoute **aucune résilience** — si internet tombe, le navigateur ne joint plus l'API non plus.
Les deux répondent à des besoins opposés.

## Deux protocoles, trois transports (14/11/2026)

| | USB (Web Serial) | Bluetooth (Web Bluetooth) | Réseau local |
|---|---|---|---|
| **MeshCore** | oui | oui (service UART Nordic) | **impossible** : TCP brut |
| **Meshtastic** | oui | oui | oui, par l'API HTTP du nœud |

MeshCore en Wi-Fi parle du TCP brut sur le port 5000, et aucune API de navigateur n'ouvre une
connexion TCP. Meshtastic expose en plus une API HTTP (`/api/v1/toradio`, `/api/v1/fromradio`)
avec `Access-Control-Allow-Origin: *` ; Chrome autorise une page HTTPS à l'appeler sur une IP
privée après une autorisation « réseau local » donnée par l'utilisateur.

## La radio dit qui elle est

Le navigateur lit l'identité de la radio **sur la radio elle-même** — clé publique MeshCore dans
`SELF_INFO`, `my_node_num` Meshtastic dans `MyNodeInfo` — avant d'ouvrir la moindre session. Le
serveur retrouve le companion correspondant, ou le crée (`identifier`). C'est ce qui permet le
« un bouton, et hop » demandé, et c'est aussi un garde-fou : choisir « radio A » dans une liste
puis brancher la radio B attribuerait le trafic de B à A.

## Pourquoi le navigateur est le pont, et non un tuyau

La première conception passait par une WebSocket transportant des octets bruts, le central
branchant le pont existant derrière. Écartée après vérification : **le projet est en WSGI pur**
(gunicorn, ni Channels ni serveur ASGI). Une WebSocket demanderait une dépendance, un processus
et une infrastructure nouvelle, et un tuyau d'octets imposerait en plus un état long par session
sur le central. Disproportionné.

Le navigateur appelle donc **les mêmes endpoints HTTP que `meshcore-bridge`** — ils existent
déjà et sont éprouvés — et ne parle du protocole companion que le strict nécessaire : ouvrir le
port, découper les trames, envoyer un message, relever ceux en attente.

## La frontière de sécurité, et elle est stricte

Un navigateur **n'entre jamais** dans la catégorie `EstComptePont`, qui garde les endpoints
livrant les secrets radio en clair — PSK de canal, clé privée du companion. Le commentaire de
cette permission est explicite : « un compte qui peut lire tous les secrets radio ne doit pas
pouvoir être fabriqué par une requête HTTP ». Donc :

- **le relais ne provisionne aucun canal** et ne lit aucune clé. La radio qu'on branche est
  déjà configurée, c'est son propriétaire qui l'apporte ;
- il se limite aux messages directs, à l'état et aux contacts.

**Et il ferme un trou préexistant.** `MessageMeshLogViewSet` accordait `create`,
`partial_update` et `a-envoyer` à tout compte authentifié, en supposant dans un commentaire que
l'appelant était un compte de service — sans le vérifier. N'importe quel citoyen inscrit pouvait
donc lire la file sortante d'un companion, et y déposer un faux message entrant. Définir qui
peut agir pour un companion était nécessaire pour ce relais ; ça l'était déjà avant.
"""
from django.utils import timezone

#: Au-delà de ce silence, une session est réputée morte. Le navigateur bat la mesure à chaque
#: cycle de relais (quelques secondes) : deux minutes laissent passer une reconnexion Wi-Fi ou
#: une mise en veille brève sans libérer le companion trop tôt.
SECONDES_AVANT_SESSION_MORTE = 120

#: Plafond de sessions simultanées pour un même companion. Un seul relais à la fois : deux
#: navigateurs qui dépileraient la même file enverraient chaque message deux fois.
SESSIONS_MAX_PAR_COMPAGNON = 1

#: Un pont qui a rapporté CONNECTE depuis moins longtemps que ça tient la radio : un relais
#: navigateur en parallèle dépilerait la même file et doublerait chaque message.
SECONDES_PONT_VIVANT = 120

MESHCORE = "MESHCORE"
MESHTASTIC = "MESHTASTIC"
PROTOCOLES = (MESHCORE, MESHTASTIC)


class RelaisRefuse(Exception):
    """Refus explicable, fait pour être lu à l'écran tel quel."""


# ══ Les deux protocoles ═══════════════════════════════════════════════════════

def modele_compagnon(protocole):
    from .models import CompagnonMeshCore, CompagnonMeshtastic

    if protocole == MESHTASTIC:
        return CompagnonMeshtastic
    if protocole == MESHCORE:
        return CompagnonMeshCore
    raise RelaisRefuse("Protocole radio inconnu.")


def protocole_de(compagnon):
    from .models import CompagnonMeshtastic

    return MESHTASTIC if isinstance(compagnon, CompagnonMeshtastic) else MESHCORE


def _champ_session(compagnon):
    """Le nom du champ de `SessionRelaisNavigateur` qui désigne ce companion."""
    return "compagnon_meshtastic" if protocole_de(compagnon) == MESHTASTIC else "compagnon"


def compagnon_par_id(compagnon_id, protocole=None):
    """Retrouve un companion par son identifiant. Sans protocole, essaie les deux : les
    identifiants sont des UUID, une collision entre les deux tables n'existe pas en pratique."""
    from .models import CompagnonMeshCore, CompagnonMeshtastic

    if not compagnon_id:
        return None
    modeles = [modele_compagnon(protocole)] if protocole else [CompagnonMeshCore,
                                                                CompagnonMeshtastic]
    for modele in modeles:
        try:
            trouve = modele.objects.filter(pk=compagnon_id).first()
        except (ValueError, Exception):  # identifiant mal formé : pas une radio
            trouve = None
        if trouve is not None:
            return trouve
    return None


# ══ Qui a la main ═════════════════════════════════════════════════════════════

def _est_mon_noeud(utilisateur, compagnon):
    """Ce companion est-il la radio personnelle de cette personne ?

    Rapprochement par l'identité radio, seule chose que les deux modèles ont en commun : la
    **clé publique** côté MeshCore (`NoeudMeshUtilisateur`), le **numéro de nœud** côté
    Meshtastic (`NoeudUtilisateurMeshtastic`). Un même appareil peut être à la fois « mon nœud »
    et « une passerelle » — c'est précisément le cas du relais navigateur.
    """
    from .models import NoeudMeshUtilisateur, NoeudUtilisateurMeshtastic

    if compagnon is None:
        return False
    if protocole_de(compagnon) == MESHTASTIC:
        return NoeudUtilisateurMeshtastic.objects.filter(
            utilisateur=utilisateur, node_num=compagnon.node_num, actif=True,
        ).exists()
    if not compagnon.pubkey_hex:
        return False
    return NoeudMeshUtilisateur.objects.filter(
        utilisateur=utilisateur, pubkey_hex=compagnon.pubkey_hex, actif=True,
    ).exists()


def peut_relayer(utilisateur, compagnon):
    """Cette personne peut-elle relayer ce companion ?

    **Correction du 14/11/2026.** La première version exigeait l'appartenance à l'institution
    propriétaire d'un companion déjà déclaré, et rien d'autre ne passait. C'était un contresens
    sur le besoin : le cas visé est « quelqu'un **sans** satellite branche **son** nœud en USB ».
    Pire, la liste servie à l'écran pré-filtrait sur `ContactInstitution`, ce qui contredisait
    cette fonction : un administrateur accepté ici voyait quand même une liste vide.

    Trois titres, et un seul suffit :

    1. **l'administrateur au sens du rôle RÉEL** — jamais le rôle effectif : un `demo_role`
       prêté le temps d'une démonstration ne donne pas la main sur une radio réelle, même
       raisonnement que `EstComptePont` ;
    2. **le propriétaire du nœud** (voir `_est_mon_noeud`) ;
    3. **un membre actif de l'institution** propriétaire du companion.

    Dans tous les cas la **possession physique** de la radio reste exigée de fait : USB,
    appairage Bluetooth ou réseau local, aucun ne permet de relayer une radio qu'on n'a pas à
    portée.
    """
    from .models import ContactInstitution, UserRole

    if not getattr(utilisateur, "is_authenticated", False) or compagnon is None:
        return False
    if getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR:
        return True
    if _est_mon_noeud(utilisateur, compagnon):
        return True
    if compagnon.institution_id is None:
        # Un companion sans institution n'appartient à personne : on ne devine pas à qui le
        # confier. Mieux vaut un relais refusé qu'un relais accordé au hasard.
        return False
    return ContactInstitution.objects.filter(
        utilisateur=utilisateur, institution_id=compagnon.institution_id, actif=True,
    ).exists()


def tenu_par_un_pont(compagnon):
    """Un pont Python tient-il déjà cette radio ?

    Deux relais sur la même radio dépileraient la même file sortante : chaque message partirait
    deux fois. On se fie au dernier état rapporté par le pont — `CONNECTE` récent — et on
    ignore les companions créés par un navigateur, qu'aucun pont n'ouvre jamais."""
    from .models import MeshCoreConnexionType

    if compagnon.connexion_type == MeshCoreConnexionType.NAVIGATEUR:
        return False
    if (compagnon.dernier_etat or "") != "CONNECTE" or not compagnon.derniere_connexion:
        return False
    limite = timezone.now() - timezone.timedelta(seconds=SECONDES_PONT_VIVANT)
    return compagnon.derniere_connexion >= limite


# ══ Sessions ══════════════════════════════════════════════════════════════════

def _limite_vivante():
    return timezone.now() - timezone.timedelta(seconds=SECONDES_AVANT_SESSION_MORTE)


def session_active(utilisateur, compagnon):
    """La session de relais ouverte par CETTE personne pour CE companion, ou None.

    Accepte le companion lui-même ou son identifiant (les deux protocoles sont essayés)."""
    from .models import SessionRelaisNavigateur

    if not getattr(utilisateur, "is_authenticated", False):
        return None
    if not hasattr(compagnon, "pk"):
        compagnon = compagnon_par_id(compagnon)
    if compagnon is None:
        return None
    return SessionRelaisNavigateur.objects.filter(
        utilisateur=utilisateur, fermee_le__isnull=True, dernier_contact__gte=_limite_vivante(),
        **{_champ_session(compagnon): compagnon},
    ).first()


def sessions_vivantes(compagnon):
    from .models import SessionRelaisNavigateur

    return SessionRelaisNavigateur.objects.filter(
        fermee_le__isnull=True, dernier_contact__gte=_limite_vivante(),
        **{_champ_session(compagnon): compagnon},
    )


def mes_sessions(utilisateur):
    """Les relais vivants de cette personne, tous protocoles confondus."""
    from .models import SessionRelaisNavigateur

    return SessionRelaisNavigateur.objects.filter(
        utilisateur=utilisateur, fermee_le__isnull=True, dernier_contact__gte=_limite_vivante(),
    ).select_related("compagnon", "compagnon_meshtastic")


def ouvrir(utilisateur, compagnon, environnement, user_agent="", transport="USB"):
    """Ouvre une session de relais. Renvoie `(session, erreur)`.

    Reprend une session déjà ouverte par la même personne plutôt que d'en empiler : recharger
    la page ne doit pas consommer le plafond, ni laisser une session fantôme derrière soi."""
    from .models import SessionRelaisNavigateur, TransportRelais

    if not peut_relayer(utilisateur, compagnon):
        return None, ("Vous n'avez pas la main sur cette radio : elle n'est ni la vôtre, ni "
                      "celle d'une institution dont vous êtes membre.")

    existante = session_active(utilisateur, compagnon)
    if existante is not None:
        existante.dernier_contact = timezone.now()
        existante.save(update_fields=["dernier_contact"])
        return existante, None

    if tenu_par_un_pont(compagnon):
        return None, ("Cette radio est déjà tenue par un pont (dernier état : connecté). La "
                      "relayer aussi depuis ce poste enverrait chaque message en double.")

    # Les sessions mortes sont fermées AVANT de compter : sinon un navigateur fermé brutalement
    # bloquerait la radio jusqu'au passage d'une purge.
    fermer_sessions_mortes(compagnon)
    if sessions_vivantes(compagnon).count() >= SESSIONS_MAX_PAR_COMPAGNON:
        return None, ("Cette radio est déjà relayée depuis un autre poste. Deux relais "
                      "enverraient chaque message en double.")

    if transport not in TransportRelais.values:
        transport = TransportRelais.USB
    session = SessionRelaisNavigateur.objects.create(
        utilisateur=utilisateur, environment=environnement, transport=transport,
        user_agent=(user_agent or "")[:255], **{_champ_session(compagnon): compagnon},
    )
    return session, None


def battre(session):
    """Marque la session vivante. Appelé à chaque cycle de relais du navigateur."""
    session.dernier_contact = timezone.now()
    session.save(update_fields=["dernier_contact"])


def fermer(session, motif=""):
    session.fermee_le = timezone.now()
    session.motif_fermeture = (motif or "")[:120]
    session.save(update_fields=["fermee_le", "motif_fermeture"])
    reattribuer_file(session.radio)


def fermer_sessions_mortes(compagnon=None):
    """Ferme les sessions silencieuses depuis trop longtemps. Renvoie le nombre fermé.

    Une page web n'annonce pas sa fermeture de façon fiable — onglet tué, portable en veille,
    Wi-Fi coupé. Sans ce ménage, une radio resterait marquée relayée indéfiniment."""
    from .models import SessionRelaisNavigateur

    qs = SessionRelaisNavigateur.objects.filter(
        fermee_le__isnull=True, dernier_contact__lt=_limite_vivante(),
    )
    if compagnon is not None:
        if not hasattr(compagnon, "pk"):
            compagnon = compagnon_par_id(compagnon)
        if compagnon is None:
            return 0
        qs = qs.filter(**{_champ_session(compagnon): compagnon})
    mortes = list(qs.select_related("compagnon", "compagnon_meshtastic"))
    if not mortes:
        return 0
    nombre = qs.update(fermee_le=timezone.now(), motif_fermeture="Silence prolongé")
    # Une radio dont le relais vient de mourir ne doit pas garder des messages en otage.
    for radio in {s.radio for s in mortes}:
        reattribuer_file(radio)
    return nombre


# ══ Ce qu'on propose à l'écran ════════════════════════════════════════════════

def radios_relayables(utilisateur):
    """Les radios proposées à l'écran : `(companions, noeuds_personnels)`, deux protocoles.

    Deux listes parce qu'il y a deux situations :

    - les **companions** déjà déclarés que cette personne a le droit de relayer ;
    - ses **nœuds personnels** pas encore companions. Ils n'ont rien à déclarer d'avance : au
      branchement, `identifier` les promeut en companion.

    Un nœud déjà promu n'apparaît que dans la première liste — même identité radio, même radio.
    """
    from django.db.models import Q

    from .models import (
        CompagnonMeshCore, CompagnonMeshtastic, ContactInstitution, NoeudMeshUtilisateur,
        NoeudUtilisateurMeshtastic, UserRole,
    )

    est_admin = getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR
    miennes = list(ContactInstitution.objects.filter(
        utilisateur=utilisateur, actif=True,
    ).values_list("institution_id", flat=True))
    mes_cles = list(NoeudMeshUtilisateur.objects.filter(
        utilisateur=utilisateur, actif=True,
    ).values_list("pubkey_hex", flat=True))
    mes_nums = list(NoeudUtilisateurMeshtastic.objects.filter(
        utilisateur=utilisateur, actif=True,
    ).values_list("node_num", flat=True))

    meshcore = CompagnonMeshCore.objects.filter(actif=True).select_related("institution")
    meshtastic = CompagnonMeshtastic.objects.filter(actif=True).select_related("institution")
    if not est_admin:
        # Restreint en base plutôt que d'appeler `peut_relayer` sur toute la table ; le filtre
        # final reste l'autorité, pour que la règle soit la même aux deux endroits.
        meshcore = meshcore.filter(Q(institution_id__in=miennes) | Q(pubkey_hex__in=mes_cles))
        meshtastic = meshtastic.filter(Q(institution_id__in=miennes) | Q(node_num__in=mes_nums))
    # Un companion MQTT Meshtastic n'est pas un appareil : il n'y a rien à brancher.
    meshtastic = meshtastic.exclude(connexion_type="MQTT")

    compagnons = [c for c in list(meshcore.order_by("nom")) + list(meshtastic.order_by("nom"))
                  if peut_relayer(utilisateur, c)]
    cles_prises = {c.pubkey_hex for c in compagnons
                   if protocole_de(c) == MESHCORE and c.pubkey_hex}
    nums_pris = {c.node_num for c in compagnons if protocole_de(c) == MESHTASTIC}

    noeuds = [n for n in NoeudMeshUtilisateur.objects.filter(utilisateur=utilisateur, actif=True)
              if n.pubkey_hex not in cles_prises]
    noeuds += [n for n in NoeudUtilisateurMeshtastic.objects.filter(
        utilisateur=utilisateur, actif=True) if n.node_num not in nums_pris]
    return compagnons, noeuds


def protocole_du_noeud(noeud):
    from .models import NoeudUtilisateurMeshtastic

    return MESHTASTIC if isinstance(noeud, NoeudUtilisateurMeshtastic) else MESHCORE


# ══ Identification par la radio elle-même ═════════════════════════════════════

def _normaliser_identite(protocole, identite):
    """Valide l'identité rapportée par le navigateur. Lève `RelaisRefuse`."""
    identite = identite or {}
    nom = str(identite.get("nom") or "").strip()[:100]
    if protocole == MESHCORE:
        cle = str(identite.get("pubkey_hex") or "").strip().lower()
        if len(cle) != 64 or any(c not in "0123456789abcdef" for c in cle):
            raise RelaisRefuse("Identité MeshCore illisible : clé publique de 32 octets attendue.")
        return {"pubkey_hex": cle, "nom": nom}
    try:
        num = int(identite.get("node_num"))
    except (TypeError, ValueError):
        raise RelaisRefuse("Identité Meshtastic illisible : numéro de nœud attendu.") from None
    # 0 et 0xFFFFFFFF ne désignent pas un nœud : « aucun » et « tout le monde ».
    if not 0 < num < 0xFFFFFFFF:
        raise RelaisRefuse("Numéro de nœud Meshtastic invalide.")
    cle = str(identite.get("cle_publique_hex") or "").strip().lower()
    return {"node_num": num, "nom": nom, "cle_publique_hex": cle if len(cle) == 64 else ""}


def _compagnon_existant(protocole, identite):
    modele = modele_compagnon(protocole)
    if protocole == MESHCORE:
        return modele.objects.filter(pubkey_hex=identite["pubkey_hex"]).order_by(
            "date_creation").first()
    return modele.objects.filter(node_num=identite["node_num"]).first()


def _mon_noeud(utilisateur, protocole, identite):
    from .models import NoeudMeshUtilisateur, NoeudUtilisateurMeshtastic

    if protocole == MESHCORE:
        return NoeudMeshUtilisateur.objects.filter(
            utilisateur=utilisateur, pubkey_hex=identite["pubkey_hex"], actif=True).first()
    return NoeudUtilisateurMeshtastic.objects.filter(
        utilisateur=utilisateur, node_num=identite["node_num"], actif=True).first()


def _institution_pour_nouvelle_passerelle(utilisateur):
    """L'institution à laquelle rattacher une radio inconnue, ou None si on ne peut pas.

    Déclarer une passerelle pour une institution, c'est ajouter de l'infrastructure radio en
    son nom : réservé à l'administrateur (rôle RÉEL) et aux acteurs institutionnels membres
    actifs de leur institution courante. Un bénévole déclare d'abord SA radio comme son nœud —
    sinon n'importe quel compte inscrit pourrait enregistrer des passerelles."""
    from .institution_courante import est_membre, institution_courante
    from .models import UserRole
    from .permissions import INSTITUTIONAL_TYPES

    type_reel = getattr(utilisateur, "type", None)
    if type_reel not in INSTITUTIONAL_TYPES:
        return None, False
    institution = institution_courante(utilisateur)
    if type_reel == UserRole.ADMINISTRATOR:
        return institution, True
    if institution is None or not est_membre(utilisateur, institution.id):
        return None, False
    return institution, True


def _creer_compagnon(protocole, identite, institution, environnement, nom_par_defaut):
    from .models import MeshCoreConnexionType

    modele = modele_compagnon(protocole)
    nom = identite["nom"] or nom_par_defaut
    champs = dict(
        environment=environnement, institution=institution, nom=nom[:100],
        # Aucun pont ne doit essayer de l'ouvrir : elle est sur le poste de quelqu'un.
        connexion_type=MeshCoreConnexionType.NAVIGATEUR,
    )
    if protocole == MESHCORE:
        champs["pubkey_hex"] = identite["pubkey_hex"]
    else:
        champs["node_num"] = identite["node_num"]
        champs["long_name"] = (identite["nom"] or "")[:40]
        if identite.get("cle_publique_hex"):
            champs["cle_publique_appareil_hex"] = identite["cle_publique_hex"]
    return modele.objects.create(**champs)


def identifier(utilisateur, protocole, identite, environnement):
    """Le companion correspondant à la radio branchée, créé au besoin. Lève `RelaisRefuse`.

    Renvoie `(compagnon, cree)`. Trois cas, dans cet ordre :

    1. **la radio est déjà connue** (même clé / même numéro) → ce companion, si l'on a la main ;
    2. **c'est mon nœud déclaré** → promu en passerelle, rattaché à mon institution courante ;
    3. **radio inconnue** → créée pour l'institution courante, mais seulement par un acteur qui
       peut déclarer de l'infrastructure en son nom (voir `_institution_pour_nouvelle_passerelle`).

    Aucun secret n'est lu ni écrit : ni clé de canal, ni clé privée, ni mot de passe MQTT. La
    frontière de `EstComptePont` reste entière — on déclare l'existence d'une radio, pas de quoi
    la déchiffrer.
    """
    from .institution_courante import institution_courante

    identite = _normaliser_identite(protocole, identite)

    existant = _compagnon_existant(protocole, identite)
    if existant is not None:
        if not peut_relayer(utilisateur, existant):
            raise RelaisRefuse(
                f"Cette radio est déclarée comme « {existant.nom} », et vous n'avez pas la main "
                "dessus : elle n'est ni la vôtre, ni celle d'une institution dont vous êtes membre.")
        if not existant.actif:
            existant.actif = True
            existant.save(update_fields=["actif"])
        return existant, False

    noeud = _mon_noeud(utilisateur, protocole, identite)
    if noeud is not None:
        nom_noeud = (getattr(noeud, "nom_noeud", "") or "").strip()
        identite = {**identite, "nom": identite["nom"] or nom_noeud}
        nom = f"Radio de {utilisateur.get_full_name() or utilisateur.email}"
        return _creer_compagnon(protocole, identite, institution_courante(utilisateur),
                                environnement, nom), True

    institution, autorise = _institution_pour_nouvelle_passerelle(utilisateur)
    if not autorise:
        raise RelaisRefuse(
            "Radio inconnue. Déclarez-la d'abord comme votre nœud dans Mon espace › Mon compte, "
            "ou demandez à un responsable de votre institution de la connecter.")
    return _creer_compagnon(protocole, identite, institution, environnement,
                            "Passerelle navigateur"), True


def verifier_identite(compagnon, identite):
    """La radio branchée est-elle bien CE companion ? Lève `RelaisRefuse` sinon.

    Ne compare que ce qui est fiable : la clé publique MeshCore quand on la connaît (et on
    l'enregistre sinon, comme le pont à sa première connexion) ; le numéro Meshtastic seulement
    pour un companion créé par un navigateur — celui des companions plus anciens a pu être
    choisi à la main, pas lu sur l'appareil."""
    from .models import MeshCoreConnexionType

    protocole = protocole_de(compagnon)
    identite = _normaliser_identite(protocole, identite)
    if protocole == MESHCORE:
        if not compagnon.pubkey_hex:
            compagnon.pubkey_hex = identite["pubkey_hex"]
            compagnon.save(update_fields=["pubkey_hex"])
            return
        if compagnon.pubkey_hex.lower() != identite["pubkey_hex"]:
            raise RelaisRefuse(
                f"La radio branchée n'est pas « {compagnon.nom} » : sa clé publique est "
                f"{identite['pubkey_hex'][:12]}…, celle attendue {compagnon.pubkey_hex[:12]}….")
        return
    if (compagnon.connexion_type == MeshCoreConnexionType.NAVIGATEUR
            and compagnon.node_num != identite["node_num"]):
        raise RelaisRefuse(
            f"La radio branchée n'est pas « {compagnon.nom} » : elle annonce le nœud "
            f"!{identite['node_num']:08x}, celui attendu est !{compagnon.node_num:08x}.")


# ══ Les radios de navigateur dans le choix automatique de l'émetteur ═══════════
#
# Correction du 14/11/2026, constatée en répondant à « quelle interaction avec les messages
# d'équipe ? ». Le serveur choisit seul la radio qui enverra un message (clé de canal d'équipe,
# message direct) — `_compagnon_pour_equipe`, `meilleur_compagnon_pour_contact`, et l'interface
# qui retombe sur « la première de la liste ». Aucun ne distinguait une radio de navigateur : une
# radio branchée une seule fois restait déclarée et active, donc éligible. Les messages lui
# étaient confiés et attendaient qu'on la rebranche, sans que personne ne le voie.
#
# Règle : une radio de navigateur n'est un émetteur que **tant qu'un relais est vivant dessus**.

def _ids_relayes(modele):
    """Identifiants des companions de ce modèle qui ont un relais vivant en ce moment."""
    from .models import CompagnonMeshtastic, SessionRelaisNavigateur

    champ = "compagnon_meshtastic_id" if modele is CompagnonMeshtastic else "compagnon_id"
    return SessionRelaisNavigateur.objects.filter(
        fermee_le__isnull=True, dernier_contact__gte=_limite_vivante(),
    ).exclude(**{f"{champ}__isnull": True}).values_list(champ, flat=True)


def emetteurs(queryset):
    """Restreint un queryset de companions à ceux qui peuvent émettre MAINTENANT : tous sauf les
    radios de navigateur sans relais vivant."""
    from django.db.models import Q

    from .models import MeshCoreConnexionType

    return queryset.exclude(
        Q(connexion_type=MeshCoreConnexionType.NAVIGATEUR) & ~Q(pk__in=_ids_relayes(queryset.model))
    )


def peut_emettre(compagnon):
    from .models import MeshCoreConnexionType

    if compagnon is None:
        return False
    if compagnon.connexion_type != MeshCoreConnexionType.NAVIGATEUR:
        return True
    return sessions_vivantes(compagnon).exists()


def reattribuer_file(compagnon):
    """Confie à un autre émetteur les messages directs restés en attente sur une radio de
    navigateur qui vient de perdre son dernier relais. Renvoie le nombre de messages déplacés.

    Sans cela, ce qui n'était pas encore parti au moment où l'on débranche restait bloqué
    jusqu'au prochain branchement de CETTE radio — peut-être jamais. Le nouvel émetteur est
    choisi par les mêmes règles que pour un nouveau message, dans la même institution ; s'il
    n'y en a aucun, les messages restent où ils sont plutôt que de partir d'une radio d'une
    autre institution.
    """
    from .models import (
        CompagnonMeshtastic, DirectionMessageMesh, MeshCoreConnexionType, MessageMeshLog,
        MessageMeshtasticLog, StatutMessageMesh,
    )

    if compagnon is None or compagnon.connexion_type != MeshCoreConnexionType.NAVIGATEUR:
        return 0
    if sessions_vivantes(compagnon).exists():
        return 0

    meshtastic = isinstance(compagnon, CompagnonMeshtastic)
    modele_message = MessageMeshtasticLog if meshtastic else MessageMeshLog
    en_attente = modele_message.objects.filter(
        compagnon=compagnon, direction=DirectionMessageMesh.SORTANT,
        statut=StatutMessageMesh.EN_ATTENTE,
    )
    deplaces = 0
    for message in en_attente:
        if meshtastic:
            candidats = emetteurs(type(compagnon).objects.filter(actif=True).exclude(pk=compagnon.pk))
            if compagnon.institution_id:
                candidats = candidats.filter(institution_id=compagnon.institution_id)
            remplacant = candidats.exclude(connexion_type="MQTT").order_by("-principal").first() \
                or candidats.order_by("-principal").first()
        else:
            from .routage_mesh import meilleur_compagnon_pour_contact
            remplacant = meilleur_compagnon_pour_contact(
                pubkey_hex=message.contact_pubkey_hex, institution=compagnon.institution,
                exclure=compagnon,
            ).compagnon if compagnon.institution_id else None
        if remplacant is not None:
            message.compagnon = remplacant
            message.save(update_fields=["compagnon"])
            deplaces += 1
    return deplaces
