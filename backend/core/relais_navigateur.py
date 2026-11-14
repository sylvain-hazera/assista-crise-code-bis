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


def peut_relayer(utilisateur, compagnon):
    """Cette personne peut-elle relayer ce companion ?

    Deux conditions, et le cumul des deux est le garde-fou : **l'appartenance** à l'institution
    propriétaire du companion, et la **possession physique** de la radio, que l'USB impose de
    fait. Ni l'une ni l'autre ne suffit seule — un membre sans la radio ne peut rien relayer, et
    quelqu'un qui a la radio sans être membre n'est pas autorisé.

    L'administrateur au sens du rôle RÉEL est accepté pour le diagnostic — jamais le rôle
    effectif : un `demo_role=ADMIN` prêté le temps d'une démonstration ne donne pas la main sur
    une radio réelle. Même raisonnement que `EstComptePont`.
    """
    from .models import ContactInstitution, UserRole

    if not getattr(utilisateur, "is_authenticated", False):
        return False
    if getattr(utilisateur, "type", None) == UserRole.ADMINISTRATOR:
        return True
    if compagnon is None or compagnon.institution_id is None:
        # Un companion sans institution n'appartient à personne : on ne devine pas à qui le
        # confier. Mieux vaut un relais refusé qu'un relais accordé au hasard.
        return False
    return ContactInstitution.objects.filter(
        utilisateur=utilisateur, institution_id=compagnon.institution_id, actif=True,
    ).exists()


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
        return None, ("Vous n'êtes pas membre de l'institution propriétaire de cette radio. "
                      "Seuls ses membres peuvent la relayer.")

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
