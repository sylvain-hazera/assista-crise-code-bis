"""Les services d'adresses de l'État, en UN seul endroit (18/11/2026).

Constat du tour des doublons : la même donnée était demandée à trois services, depuis cinq
modules, chacun avec son adresse écrite en dur —

- `api-adresse.data.gouv.fr` pour retrouver la commune d'un point (geo_lookup) et pour situer
  une adresse importée (imports) ;
- `data.geopf.fr/geocodage` pour le champ d'adresse des formulaires (views_adresses) ;
- `plateforme.adresse.data.gouv.fr/lookup` pour les rues et les numéros d'une commune
  (habitations, inondation).

Les deux premiers sont le MÊME service : la Géoplateforme de l'IGN est le successeur officiel
d'api-adresse.data.gouv.fr, avec les mêmes paramètres et la même réponse — vérifié le
18/11/2026 sur un point et une adresse réels, réponses identiques. Tout le géocodage passe
donc désormais par la Géoplateforme. Le troisième est autre chose (le détail de la Base
Adresse Nationale, rue par rue) : il reste, mais son adresse n'est plus écrite qu'ici.

Ce module ne fait AUCUN appel : il dit où appeler et comment lire la réponse. Chaque module
garde sa façon d'appeler (délais, mise en cache, journalisation sans l'adresse cherchée), ce
qui laisse intacts leurs essais.

Rappel de la règle du projet : aucune adresse du registre des personnes vulnérables ne part
vers un géocodeur. Rien ici ne change cela.
"""
import urllib.parse

#: Géocodage : chercher une adresse, ou trouver l'adresse la plus proche d'un point.
GEOCODAGE = "https://data.geopf.fr/geocodage"
#: Base Adresse Nationale : les rues d'une commune, les numéros d'une rue.
BAN = "https://plateforme.adresse.data.gouv.fr/lookup"


def url_recherche(texte: str, limite: int = 1) -> str:
    return f"{GEOCODAGE}/search?" + urllib.parse.urlencode({"q": texte, "limit": limite})


def url_inverse(lon, lat, limite: int = 1) -> str:
    return f"{GEOCODAGE}/reverse?" + urllib.parse.urlencode({"lon": lon, "lat": lat, "limit": limite})


def url_ban(identifiant: str) -> str:
    """`identifiant` : un code de commune (ses rues) ou l'identifiant d'une rue (ses numéros)."""
    return f"{BAN}/{urllib.parse.quote(str(identifiant))}"


def premiere_adresse(donnees) -> dict | None:
    """La première adresse d'une réponse de géocodage, mise à plat :
    `{latitude, longitude, citycode, commune, libelle}` — ou None s'il n'y en a pas."""
    if not isinstance(donnees, dict):
        return None
    objets = donnees.get("features") or []
    if not objets:
        return None
    try:
        longitude, latitude = objets[0]["geometry"]["coordinates"][:2]
    except (KeyError, TypeError, ValueError):
        return None
    proprietes = objets[0].get("properties") or {}
    return {"latitude": latitude, "longitude": longitude, "citycode": proprietes.get("citycode"),
            "commune": proprietes.get("city") or proprietes.get("label"), "libelle": proprietes.get("label")}
