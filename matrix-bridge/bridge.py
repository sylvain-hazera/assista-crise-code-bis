"""Service-pont Matrix <-> assista-crise (voir doc de conception "Matrix / Element", demande de
Sylvain 23/09) : provisionne UN salon Matrix privé par équipe (même principe que
meshcore-bridge/bridge.py pour les canaux MeshCore, mais indépendant -- MeshCore reste en place
pour son propre usage, ne pas le démonter), synchronise en continu les membres du salon sur
`equipe.members`, et relaie les balises de position live Element (MSC3489, "positionnement
permanent") vers l'API assista-crise pour que les régulateurs suivent leurs équipes sur la
carte (PositionsEquipesView, déjà alimentée par DernierePositionUtilisateur).

IMPORTANT — non vérifié sur un vrai client Element : la forme exacte des événements de balise
de position (m.beacon_info / m.beacon, MSC3489) vient de la spécification, pas d'un test avec
un client réel. Les payloads bruts sont journalisés en DEBUG pour ajuster rapidement si un nom
de champ diffère en pratique (même posture que meshcore-bridge, voir son propre avertissement).

Authentification :
  - vers Django : compte de service dédié (JWT), même pattern que meshcore-bridge.DjangoClient.
  - vers Synapse : un seul compte "bot" du pont, admin Synapse, obtenu une fois par
    enregistrement HMAC (registration_shared_secret) puis persisté sur disque (TOKEN_FILE) --
    les comptes humains, eux, ne se connectent JAMAIS par mot de passe (SSO OIDC uniquement,
    voir homeserver.yaml password_config.enabled: false), donc le bot ne peut pas se
    ré-authentifier par /login après un redémarrage : le token DOIT survivre (volume monté).
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sys
from pathlib import Path

import httpx

logger = logging.getLogger("matrix-bridge")

DJANGO_API_URL = os.environ["DJANGO_API_URL"]
DJANGO_BRIDGE_EMAIL = os.environ["DJANGO_BRIDGE_EMAIL"]
DJANGO_BRIDGE_PASSWORD = os.environ["DJANGO_BRIDGE_PASSWORD"]

SYNAPSE_URL = os.environ.get("SYNAPSE_URL", "http://synapse:8008")
SYNAPSE_SERVER_NAME = os.environ["SYNAPSE_SERVER_NAME"]
SYNAPSE_REGISTRATION_SHARED_SECRET = os.environ["SYNAPSE_REGISTRATION_SHARED_SECRET"]
SYNAPSE_BOT_LOCALPART = os.environ.get("SYNAPSE_BOT_LOCALPART", "pont-matrix")
SYNAPSE_BOT_PASSWORD = os.environ.get("SYNAPSE_BOT_PASSWORD") or SYNAPSE_REGISTRATION_SHARED_SECRET

TOKEN_FILE = Path(os.environ.get("TOKEN_FILE", "/data/bridge_token.json"))
SYNC_STATE_FILE = Path(os.environ.get("SYNC_STATE_FILE", "/data/bridge_sync_since.txt"))

SALONS_POLL_INTERVAL_SECONDS = int(os.environ.get("SALONS_POLL_INTERVAL_SECONDS", "30"))
SYNC_TIMEOUT_MS = int(os.environ.get("SYNC_TIMEOUT_MS", "30000"))

GEO_URI_RE = re.compile(r"^geo:(-?[0-9.]+),(-?[0-9.]+)")

# Les salons sont des modèles isolés par environnement (EnvironmentScopedViewSetMixin côté
# Django) : sans en-tête X-Environment, le pont ne voyait que PROD -- constaté le 22/10/2026,
# aucun des 12 salons d'équipe de démo n'avait jamais été créé côté Synapse.
ENVIRONNEMENTS = ("PROD", "DEMO")
PREFIXE_NOM_SALON = {"PROD": "", "DEMO": "[Démo] "}


# --- Django -----------------------------------------------------------------------------------

class DjangoClient:
    """Même principe d'authentification que meshcore-bridge.DjangoClient, sans la bascule
    central/local (ce pont ne tourne que sur l'assista-crise auquel il est rattaché, pas de
    scénario satellite ici)."""

    def __init__(self, base_url, email, password):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.access_token = None
        self._client = httpx.AsyncClient(timeout=15)

    async def _authenticate(self):
        response = await self._client.post(f"{self.base_url}/token/", json={"email": self.email, "password": self.password})
        response.raise_for_status()
        self.access_token = response.json()["access"]
        logger.info("Authentifié auprès de Django.")

    async def _request(self, method, path, environnement="PROD", **kwargs):
        if self.access_token is None:
            await self._authenticate()
        headers = {"Authorization": f"Bearer {self.access_token}", "X-Environment": environnement}
        response = await self._client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        if response.status_code == 401:
            await self._authenticate()
            headers = {"Authorization": f"Bearer {self.access_token}", "X-Environment": environnement}
            response = await self._client.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)
        response.raise_for_status()
        return response

    async def salons_a_synchroniser(self, environnement):
        response = await self._request("GET", "/salons-matrix/", environnement)
        data = response.json()
        return data["results"] if isinstance(data, dict) else data  # pagination éventuelle

    async def rapporter_salon(self, salon_id, room_id, environnement):
        await self._request("PATCH", f"/salons-matrix/{salon_id}/", environnement, json={"room_id": room_id})

    async def salons_institution_a_synchroniser(self, environnement):
        response = await self._request("GET", "/salons-matrix-institution/", environnement)
        data = response.json()
        return data["results"] if isinstance(data, dict) else data

    async def rapporter_salon_institution(self, salon_id, room_id, environnement):
        await self._request("PATCH", f"/salons-matrix-institution/{salon_id}/", environnement, json={"room_id": room_id})

    async def rapporter_position(self, matrix_user_id, latitude, longitude, horodatage_iso):
        await self._request("POST", "/matrix/positions/", json={
            "matrix_user_id": matrix_user_id, "latitude": latitude, "longitude": longitude,
            "horodatage": horodatage_iso,
        })

    async def aclose(self):
        await self._client.aclose()


# --- Synapse ------------------------------------------------------------------------------------

class SynapseClient:

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.access_token = None
        self.user_id = None
        self._client = httpx.AsyncClient(timeout=35)  # > SYNC_TIMEOUT_MS pour le long-poll /sync

    def _headers(self):
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _enregistrer_bot(self):
        """Enregistrement HMAC (registration_shared_secret) -- seule façon de créer un compte
        admin sans passer par une inscription publique (désactivée, voir enable_registration:
        false côté homeserver.yaml). Algorithme documenté par Synapse (register_new_matrix_user)."""
        nonce = (await self._client.get(f"{self.base_url}/_synapse/admin/v1/register")).json()["nonce"]
        mac = hmac.new(SYNAPSE_REGISTRATION_SHARED_SECRET.encode(), digestmod=hashlib.sha1)
        mac.update(nonce.encode())
        mac.update(b"\x00")
        mac.update(SYNAPSE_BOT_LOCALPART.encode())
        mac.update(b"\x00")
        mac.update(SYNAPSE_BOT_PASSWORD.encode())
        mac.update(b"\x00")
        mac.update(b"admin")
        response = await self._client.post(f"{self.base_url}/_synapse/admin/v1/register", json={
            "nonce": nonce, "username": SYNAPSE_BOT_LOCALPART, "password": SYNAPSE_BOT_PASSWORD,
            "mac": mac.hexdigest(), "admin": True,
        })
        response.raise_for_status()
        data = response.json()
        return data["access_token"], data["user_id"]

    async def assurer_authentification(self):
        """Charge le token persisté (TOKEN_FILE) s'il est encore valide (whoami), sinon
        enregistre le bot -- une seule fois dans la vie du volume monté, voir docstring de
        module pour pourquoi le bot ne peut pas simplement se reconnecter par mot de passe."""
        if TOKEN_FILE.exists():
            try:
                data = json.loads(TOKEN_FILE.read_text())
                self.access_token = data["access_token"]
                self.user_id = data["user_id"]
                whoami = await self._client.get(f"{self.base_url}/_matrix/client/v3/account/whoami", headers=self._headers())
                if whoami.status_code == 200:
                    logger.info("Session bot Matrix restaurée (%s).", self.user_id)
                    return
                logger.warning("Token bot persisté invalide (%s) -- ré-enregistrement.", whoami.status_code)
            except Exception:
                logger.exception("Échec de lecture du token persisté -- ré-enregistrement.")

        self.access_token, self.user_id = await self._enregistrer_bot()
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(json.dumps({"access_token": self.access_token, "user_id": self.user_id}))
        logger.info("Bot Matrix enregistré (%s).", self.user_id)

    async def assurer_compte(self, matrix_user_id, displayname) -> bool:
        """Met à jour le displayname SI le compte existe déjà -- ne le crée JAMAIS ici (incident
        réel du 17/10, voir Laura, et le même correctif côté Django, core/matrix.py::
        _compte_matrix_existe pour le détail). Avec la délégation MAS active, MAS (pas Synapse)
        est la source d'autorité des comptes (`external_ids`) -- un compte créé à l'aveugle via
        cette API admin legacy reste orphelin et bloque la première connexion SSO réelle de la
        personne avec "Localpart not available". Renvoie False (rien fait) tant que la personne
        ne s'est jamais connectée au moins une fois via MAS -- normal, pas une erreur : les
        appelants (boucle_provisionnement_salons/_institution) doivent alors renoncer à
        l'inviter au salon pour CE passage, elle le sera automatiquement dès qu'elle aura son
        compte (prochain passage après sa première connexion)."""
        existant = await self._client.get(
            f"{self.base_url}/_synapse/admin/v2/users/{matrix_user_id}", headers=self._headers(),
        )
        if existant.status_code != 200:
            return False
        # Réécrire un nom INCHANGÉ n'est pas gratuit : Synapse republie alors la fiche de membre
        # de la personne dans tous ses salons (tâche update_join_states). Fait à chaque cycle de
        # 30 s pour chaque membre de chaque salon, ça a accumulé 342 000 tâches et fini en
        # limitation de débit (429) le 22/10/2026 -- même correctif que core/matrix.py.
        if existant.json().get("displayname") == displayname:
            return True
        response = await self._client.put(
            f"{self.base_url}/_synapse/admin/v2/users/{matrix_user_id}",
            headers=self._headers(), json={"displayname": displayname},
        )
        if response.status_code not in (200, 201):
            logger.warning("Échec de provisionnement du compte %s : %s %s", matrix_user_id, response.status_code, response.text[:200])
            return False
        return True

    async def creer_salon(self, nom):
        # power_level_content_override : le preset "private_chat" laisse state_default à 50,
        # donc par défaut seul le bot (power level 100) pourrait poser un événement d'état --
        # or m.beacon_info (MSC3489, partage de position en direct) EST un événement d'état,
        # keyé par l'utilisateur qui partage. Sans cette dérogation, Element refuse le partage
        # de position à tout membre normal (power level 0) avec une erreur de permission,
        # constaté avec Sylvain le 24/09.
        response = await self._client.post(
            f"{self.base_url}/_matrix/client/v3/createRoom", headers=self._headers(),
            json={
                "name": nom, "preset": "private_chat", "visibility": "private",
                "power_level_content_override": {
                    "events": {
                        "m.beacon_info": 0,
                        "org.matrix.msc3672.beacon_info": 0,
                    },
                },
            },
        )
        response.raise_for_status()
        return response.json()["room_id"]

    async def definir_sujet(self, room_id, sujet):
        """Sujet du salon (m.room.topic) -- affiché en en-tête par la quasi-totalité des
        clients Matrix, dont Element. Reposé à chaque cycle (idempotent, PUT d'état -- pas de
        détection de changement côté pont, plus simple et sans risque de rester périmé si le
        régulateur change)."""
        response = await self._client.put(
            f"{self.base_url}/_matrix/client/v3/rooms/{room_id}/state/m.room.topic",
            headers=self._headers(), json={"topic": sujet},
        )
        if response.status_code != 200:
            logger.warning("Échec de pose du sujet du salon %s : %s", room_id, response.status_code)

    async def membres_actuels(self, room_id):
        response = await self._client.get(
            f"{self.base_url}/_matrix/client/v3/rooms/{room_id}/joined_members", headers=self._headers(),
        )
        if response.status_code != 200:
            logger.warning("Échec de lecture des membres du salon %s : %s", room_id, response.status_code)
            return set()
        return set(response.json().get("joined", {}).keys())

    async def rejoindre_de_force(self, room_id, matrix_user_id):
        response = await self._client.post(
            f"{self.base_url}/_synapse/admin/v1/join/{room_id}", headers=self._headers(),
            json={"user_id": matrix_user_id},
        )
        if response.status_code != 200:
            logger.warning("Échec d'ajout de %s au salon %s : %s %s", matrix_user_id, room_id, response.status_code, response.text[:200])

    async def expulser(self, room_id, matrix_user_id):
        response = await self._client.post(
            f"{self.base_url}/_matrix/client/v3/rooms/{room_id}/kick", headers=self._headers(),
            json={"user_id": matrix_user_id, "reason": "Ne fait plus partie de l'équipe."},
        )
        if response.status_code != 200:
            logger.warning("Échec de retrait de %s du salon %s : %s %s", matrix_user_id, room_id, response.status_code, response.text[:200])

    async def sync(self, since=None):
        params = {"timeout": SYNC_TIMEOUT_MS, "set_presence": "offline"}
        if since:
            params["since"] = since
        response = await self._client.get(
            f"{self.base_url}/_matrix/client/v3/sync", headers=self._headers(), params=params,
        )
        response.raise_for_status()
        return response.json()


# --- Boucles --------------------------------------------------------------------------------

async def boucle_provisionnement_salons(django, synapse):
    """Crée les salons pas encore côté Synapse, et resynchronise en continu les membres de
    CHAQUE salon déjà créé (ajout des nouveaux membres d'équipe, retrait de ceux partis) --
    contrairement à MeshCore (canal figé après provisionnement, révocation manuelle par
    régénération de clé), une invitation Matrix se retire tout aussi facilement qu'elle
    s'accorde, donc rien n'empêche une resynchronisation permanente et automatique."""
    while True:
        for environnement in ENVIRONNEMENTS:
            try:
                await _synchroniser_salons_equipe(django, synapse, environnement)
            except Exception:
                logger.exception("Échec du cycle de provisionnement des salons (%s).", environnement)
        await asyncio.sleep(SALONS_POLL_INTERVAL_SECONDS)


async def _synchroniser_salons_equipe(django, synapse, environnement):
    salons = await django.salons_a_synchroniser(environnement)
    for salon in salons:
        # Un membre dont le compte n'existe pas encore (jamais connecté via MAS, voir
        # assurer_compte) est exclu de `cibles` -- il ne doit pas être invité/expulsé ce
        # passage-ci, seulement dès qu'il aura son compte (prochain passage après sa
        # première connexion).
        tous_cibles = {m["matrix_user_id"]: m["nom"] for m in salon["membres"]}
        cibles = {
            matrix_id: nom for matrix_id, nom in tous_cibles.items()
            if await synapse.assurer_compte(matrix_id, nom)
        }

        room_id = salon.get("room_id")
        if not room_id:
            nom_salon = f"{PREFIXE_NOM_SALON[environnement]}Équipe {salon['equipe_nom']}"
            room_id = await synapse.creer_salon(nom_salon[:64])
            await django.rapporter_salon(salon["id"], room_id, environnement)
            logger.info("Salon créé pour l'équipe « %s » : %s", salon["equipe_nom"], room_id)

        if salon.get("sujet_salon"):
            await synapse.definir_sujet(room_id, salon["sujet_salon"])

        actuels = await synapse.membres_actuels(room_id)
        for matrix_id in cibles:
            if matrix_id not in actuels:
                await synapse.rejoindre_de_force(room_id, matrix_id)
                logger.info("Membre %s ajouté au salon de « %s ».", matrix_id, salon["equipe_nom"])
        # `expulsion_activee=False` (équipe "cellule de crise", voir
        # SalonMatrixEquipeSerializer.get_expulsion_activee côté Django) : n'importe qui
        # peut y entrer via assurer_membre_salon au premier accès (matrix.py), jamais
        # expulsé au cycle suivant faute d'être un membre formel de l'équipe -- constaté
        # en direct le 2026-09-28 (rejoint puis aussitôt exclu "Ne fait plus partie de
        # l'équipe"), corrigé ici plutôt que de rendre ce salon un cas particulier
        # ailleurs dans le pont.
        if salon.get("expulsion_activee", True):
            for matrix_id in actuels:
                if matrix_id != synapse.user_id and matrix_id not in cibles:
                    await synapse.expulser(room_id, matrix_id)
                    logger.info("Membre %s retiré du salon de « %s ».", matrix_id, salon["equipe_nom"])


TYPE_SALON_INSTITUTION_LIBELLE = {"PERMANENTS": "Permanents", "BENEVOLES": "Bénévoles mobilisés"}


async def boucle_provisionnement_salons_institution(django, synapse):
    """Même logique que boucle_provisionnement_salons, pour les deux salons généraux par
    institution (voir SalonMatrixInstitution côté Django -- personnel permanent / bénévoles
    actuellement mobilisés sur les équipes actives, composition recalculée à chaque cycle)."""
    while True:
        for environnement in ENVIRONNEMENTS:
            try:
                await _synchroniser_salons_institution(django, synapse, environnement)
            except Exception:
                logger.exception("Échec du cycle de provisionnement des salons d'institution (%s).", environnement)
        await asyncio.sleep(SALONS_POLL_INTERVAL_SECONDS)


async def _synchroniser_salons_institution(django, synapse, environnement):
    salons = await django.salons_institution_a_synchroniser(environnement)
    for salon in salons:
        # Voir le même filtrage dans boucle_provisionnement_salons ci-dessus.
        tous_cibles = {m["matrix_user_id"]: m["nom"] for m in salon["membres"]}
        cibles = {
            matrix_id: nom for matrix_id, nom in tous_cibles.items()
            if await synapse.assurer_compte(matrix_id, nom)
        }

        libelle = TYPE_SALON_INSTITUTION_LIBELLE.get(salon["type"], salon["type"])
        nom_salon = f"{PREFIXE_NOM_SALON[environnement]}{salon['institution_nom']} — {libelle}"

        room_id = salon.get("room_id")
        if not room_id:
            room_id = await synapse.creer_salon(nom_salon[:64])
            await django.rapporter_salon_institution(salon["id"], room_id, environnement)
            logger.info("Salon institution créé pour « %s » : %s", nom_salon, room_id)

        actuels = await synapse.membres_actuels(room_id)
        for matrix_id in cibles:
            if matrix_id not in actuels:
                await synapse.rejoindre_de_force(room_id, matrix_id)
                logger.info("Membre %s ajouté au salon « %s ».", matrix_id, nom_salon)
        for matrix_id in actuels:
            if matrix_id != synapse.user_id and matrix_id not in cibles:
                await synapse.expulser(room_id, matrix_id)
                logger.info("Membre %s retiré du salon « %s ».", matrix_id, nom_salon)


def _lire_since():
    if SYNC_STATE_FILE.exists():
        return SYNC_STATE_FILE.read_text().strip() or None
    return None


def _ecrire_since(since):
    SYNC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SYNC_STATE_FILE.write_text(since)


def _extraire_beacons(sync_response):
    """Parcourt les timelines de tous les salons de la réponse /sync pour en extraire les
    événements de balise de position live (MSC3489) -- voir avertissement en tête de module,
    non vérifié sur un vrai client Element. `m.beacon`/`org.matrix.msc3672.beacon` selon la
    version du client qui a émis l'événement, les deux sont tolérés."""
    beacons = []
    rooms = sync_response.get("rooms", {}).get("join", {})
    for room_id, room_data in rooms.items():
        for event in room_data.get("timeline", {}).get("events", []):
            event_type = event.get("type")
            if event_type not in ("m.beacon", "org.matrix.msc3672.beacon"):
                continue
            content = event.get("content", {})
            logger.debug("Événement de balise brut (%s) : %r", room_id, content)
            uri = (content.get("m.location") or {}).get("uri", "")
            match = GEO_URI_RE.match(uri)
            if not match:
                continue
            lat, lon = float(match.group(1)), float(match.group(2))
            ts_ms = content.get("m.ts")
            beacons.append({
                "sender": event.get("sender"),
                "latitude": lat,
                "longitude": lon,
                "ts_ms": ts_ms,
            })
    return beacons


async def boucle_positions(django, synapse):
    """Long-poll /sync en continu (positionnement PERMANENT tant qu'un membre partage sa
    position dans le salon de son équipe, demande explicite de Sylvain -- contrairement au
    suivi MeshCore volontairement limité aux missions EN_COURS)."""
    import datetime

    since = _lire_since()
    while True:
        try:
            data = await synapse.sync(since=since)
            since = data.get("next_batch", since)
            _ecrire_since(since)
            for beacon in _extraire_beacons(data):
                horodatage_iso = (
                    datetime.datetime.fromtimestamp(beacon["ts_ms"] / 1000, tz=datetime.timezone.utc).isoformat()
                    if beacon.get("ts_ms") else None
                )
                try:
                    await django.rapporter_position(beacon["sender"], beacon["latitude"], beacon["longitude"], horodatage_iso)
                    logger.info("Position rapportée pour %s.", beacon["sender"])
                except Exception:
                    logger.exception("Échec du rapport de position pour %s.", beacon["sender"])
        except Exception:
            logger.exception("Échec d'un cycle /sync -- nouvelle tentative après une pause.")
            await asyncio.sleep(10)


async def main():
    django = DjangoClient(DJANGO_API_URL, DJANGO_BRIDGE_EMAIL, DJANGO_BRIDGE_PASSWORD)
    synapse = SynapseClient(SYNAPSE_URL)
    await synapse.assurer_authentification()
    logger.info("Démarrage du pont Matrix (bot %s).", synapse.user_id)
    try:
        await asyncio.gather(
            boucle_provisionnement_salons(django, synapse),
            boucle_provisionnement_salons_institution(django, synapse),
            boucle_positions(django, synapse),
        )
    finally:
        await django.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
