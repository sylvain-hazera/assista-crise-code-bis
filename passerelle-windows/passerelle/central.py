"""Les échanges de la passerelle avec le central.

Tous existent déjà pour les satellites Docker : la passerelle Windows EST un satellite de profil
« passerelle ». Enrôlement par jeton (`/satellites/enroler/`), attente de la validation d'un
administrateur (`/recuperer-identifiants/`), puis enregistrement de chaque radio sous son
identité (`/enregistrer-depuis-satellite/`).

Erreurs : `ErreurCentral` porte un message fait pour être affiché tel quel à quelqu'un qui n'est
pas informaticien.
"""
import httpx

from . import VERSION

DELAI = 20.0


class ErreurCentral(Exception):
    pass


def normaliser_url(url: str) -> str:
    """« assista-crise.fr », « https://assista-crise.fr/ » → « https://assista-crise.fr »."""
    url = (url or "").strip().rstrip("/")
    if not url:
        raise ErreurCentral("Indiquez l'adresse du site Assista-Crise.")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if url.endswith("/api"):
        url = url[:-4]
    return url


def _message(reponse: httpx.Response, defaut: str) -> str:
    try:
        corps = reponse.json()
    except ValueError:
        return defaut
    if isinstance(corps, dict):
        return str(corps.get("error") or corps.get("detail") or defaut)
    return defaut


def _appeler(client: httpx.Client, methode: str, url: str, **kw) -> httpx.Response:
    try:
        return client.request(methode, url, **kw)
    except httpx.HTTPError:
        raise ErreurCentral(
            "Le site Assista-Crise ne répond pas. Vérifiez la connexion internet de ce poste, "
            "puis réessayez.") from None


def enroler(central: str, jeton: str, nom: str, client: httpx.Client = None) -> dict:
    """Échange le code d'installation contre une place de passerelle, en attente de validation.
    Renvoie `{satellite_id, secret_recuperation, institution_nom, nom}`."""
    client = client or httpx.Client(timeout=DELAI)
    reponse = _appeler(client, "POST", f"{central}/api/satellites/enroler/", json={
        "jeton": (jeton or "").strip(), "nom": nom, "version_logicielle": f"windows-{VERSION}",
    })
    if reponse.status_code != 201:
        raise ErreurCentral(_message(
            reponse, "Code d'installation refusé : il a peut-être expiré ou déjà servi. "
                     "Demandez-en un nouveau à votre administrateur."))
    return reponse.json()


def recuperer_identifiants(central: str, satellite_id: str, secret: str,
                           client: httpx.Client = None):
    """`None` tant qu'un administrateur n'a pas validé la passerelle ; sinon `(email, mot de
    passe)` du compte de service — donnés UNE seule fois par le central."""
    client = client or httpx.Client(timeout=DELAI)
    reponse = _appeler(client, "POST",
                       f"{central}/api/satellites/{satellite_id}/recuperer-identifiants/",
                       json={"secret": secret})
    if reponse.status_code == 202:
        return None
    if reponse.status_code == 200:
        corps = reponse.json()
        return corps["email"], corps["password"]
    if reponse.status_code == 410:
        raise ErreurCentral("Cette passerelle a été révoquée par un administrateur.")
    raise ErreurCentral(_message(
        reponse, "Le central ne reconnaît plus cette passerelle. Demandez un nouveau code "
                 "d'installation à votre administrateur."))


def derniere_version(central: str, client: httpx.Client = None):
    """La version de l'application que le central distribue, ou None si on ne sait pas. Jamais
    bloquant : une vérification de mise à jour ne doit pas empêcher de relayer."""
    client = client or httpx.Client(timeout=5.0)
    try:
        reponse = client.get(f"{central}/passerelle/version.json")
        return str(reponse.json()["version"]) if reponse.status_code == 200 else None
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return None


class Session:
    """Appels authentifiés avec le compte de service de la passerelle."""

    def __init__(self, central: str, email: str, mot_de_passe: str, client: httpx.Client = None):
        self.api = f"{central}/api"
        self.email = email
        self.mot_de_passe = mot_de_passe
        self.client = client or httpx.Client(timeout=DELAI)
        self._jeton = None

    def _connecter(self) -> None:
        reponse = _appeler(self.client, "POST", f"{self.api}/token/",
                           json={"email": self.email, "password": self.mot_de_passe})
        if reponse.status_code != 200:
            raise ErreurCentral(
                "Le central refuse les identifiants de cette passerelle : elle a peut-être été "
                "révoquée. Demandez un nouveau code d'installation à votre administrateur.")
        self._jeton = reponse.json()["access"]

    def _requete(self, methode: str, chemin: str, **kw) -> httpx.Response:
        if self._jeton is None:
            self._connecter()
        for essai in (1, 2):
            reponse = _appeler(self.client, methode, f"{self.api}{chemin}",
                               headers={"Authorization": f"Bearer {self._jeton}"}, **kw)
            if reponse.status_code != 401 or essai == 2:
                return reponse
            self._connecter()       # jeton expiré : on se reconnecte une fois
        return reponse

    @staticmethod
    def _ressource(protocole: str) -> str:
        return "compagnons-meshtastic" if protocole == "MESHTASTIC" else "compagnons-meshcore"

    def enregistrer_radio(self, protocole: str, identite: dict, transport: str, adresse: str,
                          nom: str = "") -> str:
        """Déclare (ou retrouve) la radio sur le central, sous son identité. Renvoie son
        identifiant. Idempotent : rebrancher la même radio ne crée pas de doublon."""
        corps = {"nom": nom or None}
        if protocole == "MESHTASTIC":
            corps["node_num"] = identite["node_num"]
        else:
            corps["pubkey_hex"] = identite["pubkey_hex"]
        if transport == "USB":
            corps.update(connexion_type="SERIE", serie_device=adresse)
        elif transport == "BLE":
            corps.update(connexion_type="BLE", ble_adresse=adresse)
        else:
            hote, _, port = adresse.rpartition(":")
            corps.update(connexion_type="TCP", tcp_host=hote, tcp_port=int(port))
        reponse = self._requete(
            "POST", f"/{self._ressource(protocole)}/enregistrer-depuis-satellite/", json=corps)
        if reponse.status_code not in (200, 201):
            raise ErreurCentral(_message(reponse, "Le central a refusé cette radio."))
        return reponse.json()["id"]

    def retirer_radio(self, protocole: str, compagnon_id: str) -> None:
        reponse = self._requete(
            "POST", f"/{self._ressource(protocole)}/{compagnon_id}/retirer-du-satellite/")
        if reponse.status_code not in (200, 404):
            raise ErreurCentral(_message(reponse, "Le central n'a pas pu retirer cette radio."))

    def signaler_arret(self, protocole: str, compagnon_id: str) -> None:
        """À la fermeture : dit au central que la radio n'est plus tenue. Sans cela elle
        resterait affichée « connectée » jusqu'au prochain lancement. Jamais bloquant."""
        try:
            self._requete("POST", f"/{self._ressource(protocole)}/{compagnon_id}/rapporter-etat/",
                          json={"etat": "DECONNECTE"})
        except ErreurCentral:
            pass
