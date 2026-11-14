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


def _est_mon_noeud(utilisateur, compagnon):
    """Ce companion est-il la radio personnelle de cette personne ?

    Le rattachement se fait par la **clé publique**, parce que c'est la seule chose que les
    deux modèles ont en commun : `NoeudMeshUtilisateur` dit « cette clé est à moi »,
    `CompagnonMeshCore` dit « cette clé est une passerelle ». Un même appareil peut être les
    deux à la fois, et c'est précisément le cas du relais navigateur.
    """
    from .models import NoeudMeshUtilisateur

    if compagnon is None or not compagnon.pubkey_hex:
        return False
    return NoeudMeshUtilisateur.objects.filter(
        utilisateur=utilisateur, pubkey_hex=compagnon.pubkey_hex, actif=True,
    ).exists()


def peut_relayer(utilisateur, compagnon):
    """Cette personne peut-elle relayer ce companion ?

    **Correction du 14/11/2026.** La première version exigeait l'appartenance à l'institution
    propriétaire d'un companion déjà déclaré, et rien d'autre ne passait. C'était un contresens
    sur le besoin : le cas visé est « quelqu'un **sans** satellite branche **son** nœud en USB ».
    Par construction cette personne n'a pas de companion institutionnel — on lui demandait donc
    d'avoir déjà ce que le relais est censé fournir. Pire, la liste servie à l'écran
    pré-filtrait sur `ContactInstitution`, ce qui contredisait cette fonction : un
    administrateur acceptable ici voyait quand même une liste vide.

    Trois titres, et un seul suffit :

    1. **l'administrateur au sens du rôle RÉEL** — jamais le rôle effectif : un `demo_role`
       prêté le temps d'une démonstration ne donne pas la main sur une radio réelle, même
       raisonnement que `EstComptePont` ;
    2. **le propriétaire du nœud** : la clé publique du companion est déclarée comme sienne
       dans `NoeudMeshUtilisateur`. C'est le cas central du relais navigateur ;
    3. **un membre actif de l'institution** propriétaire du companion, pour les passerelles
       institutionnelles déjà déclarées.

    Dans tous les cas la **possession physique** de la radio reste exigée de fait par l'USB :
    aucun de ces titres ne permet de relayer une radio qu'on n'a pas en main.
    """
    from .models import ContactInstitution, UserRole

    if not getattr(utilisateur, "is_authenticated", False):
        return False
    if getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR:
        return True
    if _est_mon_noeud(utilisateur, compagnon):
        return True
    if compagnon is None or compagnon.institution_id is None:
        # Un companion sans institution n'appartient à personne : on ne devine pas à qui le
        # confier. Mieux vaut un relais refusé qu'un relais accordé au hasard.
        return False
    return ContactInstitution.objects.filter(
        utilisateur=utilisateur, institution_id=compagnon.institution_id, actif=True,
    ).exists()


def radios_relayables(utilisateur):
    """Les radios proposées à l'écran : `(companions, noeuds_personnels)`.

    Deux listes parce qu'il y a deux situations, et que les confondre était l'erreur de la
    première version :

    - les **companions** déjà déclarés que cette personne a le droit de relayer ;
    - ses **nœuds personnels** qui ne sont pas encore companions. Ceux-là n'ont rien à déclarer
      d'avance : au démarrage du relais, `compagnon_pour_noeud` les promeut en companion série.

    Un nœud personnel déjà promu n'apparaît que dans la première liste — sa clé publique est
    celle du companion, et on ne propose pas deux fois la même radio.
    """
    from .models import CompagnonMeshCore, ContactInstitution, NoeudMeshUtilisateur, UserRole

    candidats = CompagnonMeshCore.objects.filter(actif=True).select_related("institution")
    if getattr(utilisateur, "type", None) != UserRole.ADMINISTRATOR:
        # Un non-administrateur ne voit que ce qu'il peut relayer. On restreint en base plutôt
        # que d'appeler `peut_relayer` sur toute la table : à l'échelle d'un département la
        # liste des companions reste petite, mais la règle doit rester la même aux deux
        # endroits — d'où le filtre final ci-dessous, qui est l'autorité.
        miennes = list(ContactInstitution.objects.filter(
            utilisateur=utilisateur, actif=True,
        ).values_list("institution_id", flat=True))
        mes_cles = list(NoeudMeshUtilisateur.objects.filter(
            utilisateur=utilisateur, actif=True,
        ).values_list("pubkey_hex", flat=True))
        from django.db.models import Q
        candidats = candidats.filter(
            Q(institution_id__in=miennes) | Q(pubkey_hex__in=mes_cles),
        )

    compagnons = [c for c in candidats.order_by("nom") if peut_relayer(utilisateur, c)]
    deja = {c.pubkey_hex for c in compagnons if c.pubkey_hex}

    noeuds = [
        n for n in NoeudMeshUtilisateur.objects.filter(utilisateur=utilisateur, actif=True)
        if n.pubkey_hex not in deja
    ]
    return compagnons, noeuds


def compagnon_pour_noeud(utilisateur, noeud, environnement):
    """Rend le companion correspondant à ce nœud personnel, en le créant au besoin.

    **Idempotent par clé publique** : rebrancher la radio demain ne crée pas un second
    companion. C'est ce qui rend l'écran utilisable sans rien préparer — on branche, on démarre.

    Aucun secret n'est lu ni écrit ici : ni clé de canal, ni clé privée, ni mot de passe MQTT.
    La frontière de `EstComptePont` reste entière — on déclare l'existence d'une radio, pas de
    quoi la déchiffrer.
    """
    from .models import CompagnonMeshCore, MeshCoreConnexionType

    if noeud.utilisateur_id != utilisateur.id:
        return None, "Ce nœud n'est pas le vôtre."

    existant = CompagnonMeshCore.objects.filter(pubkey_hex=noeud.pubkey_hex).first()
    if existant is not None:
        if not existant.actif:
            existant.actif = True
            existant.save(update_fields=["actif"])
        return existant, None

    from .institution_courante import institution_courante

    nom = (noeud.nom_noeud or "").strip() or f"Radio de {utilisateur.get_full_name() or utilisateur.email}"
    compagnon = CompagnonMeshCore.objects.create(
        environment=environnement,
        institution=institution_courante(utilisateur),
        nom=nom[:100],
        connexion_type=MeshCoreConnexionType.SERIE,
        # La radio n'est pas branchée sur le serveur mais sur le poste de la personne. Le dire
        # explicitement évite qu'un pont Python essaie un jour d'ouvrir ce périphérique.
        serie_device="navigateur",
        pubkey_hex=noeud.pubkey_hex,
    )
    return compagnon, None


def session_active(utilisateur, compagnon_id):
    """La session de relais ouverte par CETTE personne pour CE companion, ou None."""
    from .models import SessionRelaisNavigateur

    if not compagnon_id or not getattr(utilisateur, "is_authenticated", False):
        return None
    limite = timezone.now() - timezone.timedelta(seconds=SECONDES_AVANT_SESSION_MORTE)
    return SessionRelaisNavigateur.objects.filter(
        utilisateur=utilisateur, compagnon_id=compagnon_id, fermee_le__isnull=True,
        dernier_contact__gte=limite,
    ).first()


def sessions_vivantes(compagnon_id):
    from .models import SessionRelaisNavigateur

    limite = timezone.now() - timezone.timedelta(seconds=SECONDES_AVANT_SESSION_MORTE)
    return SessionRelaisNavigateur.objects.filter(
        compagnon_id=compagnon_id, fermee_le__isnull=True, dernier_contact__gte=limite,
    )


def ouvrir(utilisateur, compagnon, environnement, user_agent=""):
    """Ouvre une session de relais. Renvoie `(session, erreur)`.

    Reprend une session déjà ouverte par la même personne plutôt que d'en empiler : recharger
    la page ne doit pas consommer le plafond, ni laisser une session fantôme derrière soi."""
    from .models import SessionRelaisNavigateur

    if not peut_relayer(utilisateur, compagnon):
        return None, ("Vous n'avez pas la main sur cette radio : elle n'est ni la vôtre, ni "
                      "celle d'une institution dont vous êtes membre.")

    existante = session_active(utilisateur, compagnon.id)
    if existante is not None:
        existante.dernier_contact = timezone.now()
        existante.save(update_fields=["dernier_contact"])
        return existante, None

    # Les sessions mortes sont fermées AVANT de compter : sinon un navigateur fermé brutalement
    # bloquerait la radio jusqu'au passage d'une purge.
    fermer_sessions_mortes(compagnon.id)
    if sessions_vivantes(compagnon.id).count() >= SESSIONS_MAX_PAR_COMPAGNON:
        return None, ("Cette radio est déjà relayée depuis un autre poste. Deux relais "
                      "enverraient chaque message en double.")

    session = SessionRelaisNavigateur.objects.create(
        utilisateur=utilisateur, compagnon=compagnon, environment=environnement,
        user_agent=(user_agent or "")[:255],
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


def fermer_sessions_mortes(compagnon_id=None):
    """Ferme les sessions silencieuses depuis trop longtemps. Renvoie le nombre fermé.

    Une page web n'annonce pas sa fermeture de façon fiable — onglet tué, portable en veille,
    Wi-Fi coupé. Sans ce ménage, une radio resterait marquée relayée indéfiniment."""
    from .models import SessionRelaisNavigateur

    limite = timezone.now() - timezone.timedelta(seconds=SECONDES_AVANT_SESSION_MORTE)
    qs = SessionRelaisNavigateur.objects.filter(
        fermee_le__isnull=True, dernier_contact__lt=limite,
    )
    if compagnon_id:
        qs = qs.filter(compagnon_id=compagnon_id)
    return qs.update(fermee_le=timezone.now(), motif_fermeture="Silence prolongé")
