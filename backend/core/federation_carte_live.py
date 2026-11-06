"""Publication des relais au format de fédération de `carte-live-meshtastic`.

Chaque instance de carte live publie ses relais sur `/api/federation` et récupère ceux des
« bulles voisines » déclarées par son administrateur ; les relais voisins s'affichent alors sur
la carte et comptent dans les calculs de couverture près des limites de département. En exposant
le même format, Assista-Crise devient une bulle voisine pour **toute** instance déployée en
France — ce qui sert directement l'ambition multi-communes.

Format relevé dans `carte-live/src/federation.js` (GPL-3.0, sauveteur71 ; repris avec son
autorisation) :

    {"format": "carte-live-federation", "version": 1, "logiciel": "...",
     "instance": {"nom", "departement", "zone"}, "heure": <ms>,
     "relais": [{id, num, nom, role, lat, lon, alt, passerelle, dernierVu, hauteur, gain}],
     "liens":  [{a, b, snr, source, dernierVu}]}

Deux décisions de conception, toutes deux restrictives :

1. **Infrastructure seulement.** Ne sont publiés que des équipements fixes : `RelaisMeshCore`,
   les companions de l'institution (passerelles) et les `ContactMeshCore` de type REPEATER ou
   ROOM. Jamais un COMPANION ni un SENSOR : un companion peut être le terminal d'une personne
   (voir `NoeudMeshUtilisateur`, qui rattache une clé publique à un compte), et publier sa
   position publierait celle de quelqu'un. C'est la raison pour laquelle on ne se contente pas
   de republier tout ce qui a une position.

2. **Désactivé par défaut** (`settings.FEDERATION_CARTE_LIVE`). Publier les positions des relais
   d'un réseau de secours est une décision d'exploitation, pas un défaut technique : l'endpoint
   répond 503 tant qu'elle n'est pas prise explicitement.

`liens` est renvoyé vide : aucun modèle de liaison radio mesurée n'existe encore côté
Assista-Crise. Le champ reste présent parce que le format l'attend, et les consommateurs le
traitent comme optionnel (`j.liens || []` chez eux).
"""
import datetime

from django.conf import settings
from django.utils import timezone

FORMAT = "carte-live-federation"
VERSION = 1
# Même fenêtre que leur implémentation : un relais qui n'a rien émis depuis trois jours n'est
# plus une information utile pour un voisin, et le publier quand même donnerait une carte fausse.
FENETRE = datetime.timedelta(days=3)


def _entree(identifiant, nom, role, point, dernier_vu, passerelle=False):
    return {
        "id": identifiant,
        # `num` est le numéro de nœud Meshtastic : sans objet pour MeshCore, mais le format
        # l'attend et leurs consommateurs l'utilisent comme clé secondaire.
        "num": None,
        "nom": nom,
        "role": role,
        "lat": point.y,
        "lon": point.x,
        "alt": None,
        "passerelle": passerelle,
        "dernierVu": int(dernier_vu.timestamp() * 1000) if dernier_vu else None,
        # Renseignés par leur « fiche d'installation », que nous n'avons pas.
        "hauteur": None,
        "gain": None,
    }


def construire_payload(environment):
    """Relais publiables, pour une zone donnée (PROD ou DEMO)."""
    from .models import CompagnonMeshCore, ContactMeshCore, RelaisMeshCore, TypeContactMeshCore

    depuis = timezone.now() - FENETRE
    relais = []

    # Relais déclarés à la main : infrastructure par définition, pas de date de dernière écoute.
    for objet in RelaisMeshCore.objects.filter(
        actif=True, location__isnull=False, environment=environment,
    ):
        relais.append(_entree(
            objet.pubkey_hex or str(objet.id), objet.nom, "repeteur", objet.location, None,
        ))

    # Companions de l'institution : ce sont nos passerelles vers le reste du réseau.
    for objet in CompagnonMeshCore.objects.filter(
        actif=True, location__isnull=False, environment=environment,
    ):
        relais.append(_entree(
            objet.pubkey_hex or str(objet.id), objet.nom, "passerelle", objet.location,
            objet.derniere_connexion, passerelle=True,
        ))

    # Répéteurs et room servers entendus sur l'air. JAMAIS de COMPANION ni de SENSOR : un
    # companion peut être le terminal d'une personne.
    deja_vus = {entree["id"] for entree in relais}
    for objet in ContactMeshCore.objects.filter(
        type_contact__in=[TypeContactMeshCore.REPEATER, TypeContactMeshCore.ROOM],
        location__isnull=False, dernier_advert__gte=depuis, environment=environment,
    ).order_by('-dernier_advert'):
        if objet.pubkey_hex in deja_vus:
            continue
        deja_vus.add(objet.pubkey_hex)
        relais.append(_entree(
            objet.pubkey_hex,
            objet.nom or objet.pubkey_hex[:8],
            "repeteur" if objet.type_contact == TypeContactMeshCore.REPEATER else "salon",
            objet.location, objet.dernier_advert,
        ))

    return {
        "format": FORMAT,
        "version": VERSION,
        "logiciel": f"assista-crise ({environment})",
        "instance": {
            "nom": getattr(settings, "FEDERATION_CARTE_LIVE_NOM", "") or "Assista-Crise",
            "departement": getattr(settings, "FEDERATION_CARTE_LIVE_DEPARTEMENT", None),
            # `zone` est une emprise [sud, ouest, nord, est] chez eux ; on la laisse absente
            # plutôt que d'en inventer une : un voisin qui la lit s'en sert pour cadrer sa carte.
            "zone": None,
        },
        "heure": int(timezone.now().timestamp() * 1000),
        "relais": relais,
        "liens": [],
    }
