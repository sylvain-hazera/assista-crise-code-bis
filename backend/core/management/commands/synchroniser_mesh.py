"""Récupère du central les messages mesh que CE satellite doit émettre sur sa radio, et lui
rapporte ce qui est parti — voir `SatelliteViewSet.mesh_a_emettre` / `mesh_emis`.

Pourquoi une commande distincte de `synchroniser_entrant` : celui-ci tourne toutes les 300 s, ce
qui est très bien pour rafraîchir des crises et des dossiers, et inacceptable pour envoyer un
message en crise. Cette commande ne transporte que des ordres d'envoi, elle est donc assez légère
pour tourner toutes les 30 s sans multiplier par dix le coût de la synchronisation complète.

Pourquoi pas un pont MQTT entre le broker du satellite et celui du central (décision du
06/11/2026) : il faudrait exposer le broker du central sur Internet, et il n'éviterait aucun
travail — ce qui arrive doit de toute façon être écrit dans ces modèles pour être exploitable.
Ici, c'est le satellite qui appelle : rien à exposer, ça traverse le NAT, et ça tolère une
liaison médiocre (un satellite peut être à La Réunion).

Enchaînement complet d'un message envoyé depuis le central :
    central: MessageCanalMeshtastic(SORTANT, EN_ATTENTE)
      -> cette commande le crée à l'identique en local (même uuid)
      -> le pont local le voit par l'action `a-envoyer` habituelle et l'émet sur la radio
      -> le pont met le statut local à ENVOYE
      -> cette commande rapporte ce statut au central, qui cesse de le proposer

Idempotent de bout en bout : un rapport perdu laisse le message dans la liste du central, qui
sera recréé en local (déjà présent) puis rapporté à nouveau.
"""
import logging

import requests
from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand

from core.models import CanalMeshtastic, StatutMessageMesh

logger = logging.getLogger(__name__)

# Mêmes modèles que `SatelliteViewSet._MODELES_MESH_DESCENDANTS`. Meshtastic seulement : le
# rattachement à un satellite passe par `CompagnonMeshtastic.satellite`, et `CompagnonMeshCore`
# n'a pas ce champ.
MODELES_ATTENDUS = ("MessageMeshtasticLog", "MessageCanalMeshtastic")

CHAMPS_CANAL = (
    "institution_id", "crise_id", "equipe_id", "nom", "psk_hex", "compagnon_id",
    "principal", "actif",
)


class Command(BaseCommand):
    help = "Récupère et rapporte les messages mesh à émettre pour ce satellite."

    def handle(self, *args, **options):
        central_url = settings.SATELLITE_CENTRAL_URL
        satellite_id = settings.SATELLITE_ID
        email = settings.SATELLITE_EMAIL
        password = settings.SATELLITE_PASSWORD
        if not all([central_url, satellite_id, email, password]):
            self.stdout.write(
                "SATELLITE_CENTRAL_URL/SATELLITE_ID/SATELLITE_EMAIL/SATELLITE_PASSWORD non "
                "configurés — récupération des messages mesh inactive."
            )
            return

        base = central_url.rstrip('/')
        try:
            reponse_token = requests.post(
                f"{base}/api/token/", json={"email": email, "password": password}, timeout=15,
            )
            reponse_token.raise_for_status()
            jeton = reponse_token.json()["access"]
            entetes = {"Authorization": f"Bearer {jeton}"}

            reponse = requests.get(
                f"{base}/api/satellites/{satellite_id}/mesh-a-emettre/", headers=entetes, timeout=30,
            )
            reponse.raise_for_status()
            donnees = reponse.json()
        except requests.RequestException as exc:
            # Central injoignable : rien à faire, on retentera. Jamais bloquant — le satellite
            # doit continuer à fonctionner coupé, c'est sa raison d'être.
            logger.warning("Récupération des messages mesh échouée (%s) — retentée au prochain passage.", exc)
            self.stdout.write(f"Échec de connexion au central : {exc}")
            return

        crees = self._creer_localement(donnees)
        rapportes = self._rapporter(base, satellite_id, entetes, donnees.get("messages", []))
        self.stdout.write(f"Messages mesh : {crees} créé(s) en local, {rapportes} rapporté(s) au central.")

    def _creer_localement(self, donnees):
        """Crée les canaux PUIS les messages : l'inverse échouerait sur la clé étrangère `canal`,
        que le satellite ne reçoit par aucun autre canal."""
        for canal in donnees.get("canaux", []):
            if CanalMeshtastic.objects.filter(pk=canal["id"]).exists():
                continue
            try:
                self._creer_sans_echo(
                    CanalMeshtastic, canal["id"], {c: canal.get(c) for c in CHAMPS_CANAL},
                )
            except Exception as exc:
                # `equipe` est un OneToOneField : si ce satellite a déjà un canal pour la même
                # équipe sous un autre uuid, la création échoue. On l'ignore (ses messages seront
                # reproposés), plutôt que de faire échouer tout le lot.
                logger.warning("Canal Meshtastic %s non créé localement (%s).", canal.get("nom"), exc)
                continue
            logger.info("Canal Meshtastic %s créé localement depuis le central.", canal.get("nom"))

        crees = 0
        for message in donnees.get("messages", []):
            nom_modele = message.get("modele")
            if nom_modele not in MODELES_ATTENDUS:
                logger.warning("Modèle inattendu reçu du central : %s — ignoré.", nom_modele)
                continue
            Modele = apps.get_model('core', nom_modele)
            if Modele.objects.filter(pk=message["id"]).exists():
                continue
            champs = {c: v for c, v in message.items() if c not in ("modele", "id")}
            try:
                self._creer_sans_echo(Modele, message["id"], champs)
            except Exception as exc:
                # Typiquement une FK encore inconnue localement (companion pas encore enregistré) :
                # on ignore ce message, le central continuera de le proposer au passage suivant.
                logger.warning("Message mesh %s non créé localement (%s).", message.get("id"), exc)
                continue
            crees += 1
        return crees

    @staticmethod
    def _creer_sans_echo(Modele, objet_id, champs):
        """Création locale d'un objet venu du central, SANS le repousser vers lui.

        `_synchronisation_entrante` est le marqueur que lit `core/sync_outbox.py` pour ne pas
        enregistrer d'événement sortant : sans lui, chaque descente provoquerait une remontée du
        même objet, indéfiniment. Il doit être posé sur l'instance AVANT `save()`, donc jamais par
        `get_or_create` (qui ne laisse pas la main sur l'instance) — même motif que
        `synchroniser_entrant._appliquer`."""
        objet = Modele(id=objet_id, **champs)
        objet._synchronisation_entrante = True
        objet.save(force_insert=True)
        return objet

    def _rapporter(self, base, satellite_id, entetes, messages):
        """Rapporte l'état local des messages que le central propose encore mais qui ne sont plus
        en attente chez nous : c'est l'accusé d'émission."""
        rapports = []
        for message in messages:
            nom_modele = message.get("modele")
            if nom_modele not in MODELES_ATTENDUS:
                continue
            Modele = apps.get_model('core', nom_modele)
            local = Modele.objects.filter(id=message["id"]).only("statut", "erreur").first()
            if local is None or local.statut == StatutMessageMesh.EN_ATTENTE:
                continue
            rapports.append({
                "modele": nom_modele, "id": message["id"],
                "statut": local.statut, "erreur": local.erreur or "",
            })
        if not rapports:
            return 0
        try:
            reponse = requests.post(
                f"{base}/api/satellites/{satellite_id}/mesh-emis/",
                json={"rapports": rapports}, headers=entetes, timeout=30,
            )
            reponse.raise_for_status()
        except requests.RequestException as exc:
            # Rapport perdu : sans conséquence, le central reproposera le message et on le
            # rapportera à nouveau (l'opération est idempotente des deux côtés).
            logger.warning("Rapport d'émission mesh échoué (%s) — retenté au prochain passage.", exc)
            return 0
        return len(rapports)
