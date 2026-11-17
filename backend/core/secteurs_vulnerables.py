"""« Une personne vulnérable dans le secteur » : un cercle sur la carte, jamais un point.

Demande de Sylvain du 16/11/2026 : « au lieu de mettre un point précis sur la carte, prévoir un
cercle de zone de 100 m, orange transparent, signalant une personne vulnérable dans le secteur ».

Un point désigne une maison ; le registre des personnes vulnérables ne se montre pas maison par
maison à toute une cellule de crise. Un cercle dit ce dont l'équipe a besoin — « il y a quelqu'un
à aller voir par ici » — sans dire qui ni à quelle porte.

**Le centre du cercle n'est pas le domicile.** Un cercle centré sur la maison la désignerait
aussi sûrement qu'un point : il suffirait de viser le milieu. Le centre est donc DÉCALÉ, d'une
distance et dans une direction tirées d'une empreinte secrète de la fiche :

- le décalage (60 m au plus) est plus petit que le rayon (100 m) : la personne est toujours
  quelque part dans le cercle ;
- il est le même à chaque affichage : un décalage tiré au hasard à chaque fois se laisserait
  retrouver en superposant dix affichages et en prenant la moyenne ;
- il dépend d'un secret du serveur : connaître la méthode ne permet pas de la défaire.

**En habitat isolé, le cercle s'élargit.** Là où il n'y a qu'une maison dans cent mètres, le
cercle la désignerait quand même. On compte donc les adresses voisines dans le cercle, d'après
le relevé de la Base Adresse Nationale déjà présent sur le serveur : s'il y en a moins de
`VOISINS_MIN`, le rayon double (200, 400, 800 m) jusqu'à ce que la personne ne soit plus seule
dedans. Un grand cercle dit « habitat isolé », pas « cette maison ».

**Visible de tous les acteurs institutionnels** (décision de Sylvain, 16/11/2026, revenue sur
une première consigne « habilités seulement »), jamais du public. C'est tenable parce que le
cercle ne porte RIEN : pas de nom, pas de besoin, pas d'identifiant. Qui clique dessus lit « Personne sensible dans les
environs », et rien d'autre. Chaque consultation est inscrite à la main courante.

**Aucune adresse ne sort du serveur.** Le registre ne porte pas de coordonnées, seulement une
adresse chiffrée. Plutôt que de l'envoyer à un service de géocodage, on la rapproche des
adresses que la simulation d'inondation a déjà relevées pour la commune
(`AdresseSimuleeInondation`, issues de la Base Adresse Nationale). Une fiche dont l'adresse ne
s'y retrouve pas n'est pas située : elle est comptée, pas devinée.
"""
import math
import re
import unicodedata

from django.utils.crypto import salted_hmac

from .models import AdresseSimuleeInondation

#: Rayons essayés tour à tour : le premier où la personne a assez de voisins dans le cercle.
RAYONS_M = (100, 200, 400, 800)
RAYON_M = RAYONS_M[0]
#: Part du rayon dont le centre peut s'écarter du domicile. Strictement inférieure à 1 : la
#: personne est toujours dans le cercle.
PART_DE_DECALAGE = 0.6
#: Adresses voisines qu'il faut dans le cercle pour qu'il ne désigne pas une maison.
VOISINS_MIN = 4
#: Ce que la carte affiche au clic sur un cercle. Rien d'autre ne sort.
LIBELLE = "Personne sensible dans les environs"
_SOMMETS = 40
_METRES_PAR_DEGRE = 111_320.0


def cle_d_adresse(adresse: str) -> str:
    """Ce qui permet de reconnaître la même adresse écrite de deux façons : numéro et voie, sans
    accents, sans ponctuation, sans code postal ni commune (la recherche est déjà bornée à une
    commune). « 12 bis, rue de l'Église 42400 Saint-Chamond » -> « 12 bis rue de l eglise »."""
    texte = unicodedata.normalize("NFKD", adresse or "").encode("ascii", "ignore").decode().lower()
    texte = re.split(r"\b\d{5}\b", texte, maxsplit=1)[0]          # tout ce qui suit le code postal
    texte = re.sub(r"(\d)(bis|ter|quater)\b", r"\1 \2", texte)     # « 12bis » -> « 12 bis »
    return " ".join(re.sub(r"[^a-z0-9]+", " ", texte).split())


def situer(personnes, commune_code: str, environment) -> dict:
    """`{identifiant de fiche: adresse relevée}` pour les fiches dont l'adresse se retrouve dans
    le relevé de la commune. Les autres n'y figurent pas."""
    releve = {}
    for adresse in AdresseSimuleeInondation.objects.filter(commune_code=commune_code, environment=environment):
        releve.setdefault(cle_d_adresse(adresse.adresse), adresse)
    situees = {}
    for personne in personnes:
        cle = cle_d_adresse(personne.adresse)
        if cle and cle in releve:
            situees[personne.id] = releve[cle]
    return situees


def centre_decale(identifiant, longitude: float, latitude: float, rayon_m: float = RAYON_M) -> tuple[float, float]:
    """Le centre du cercle : le domicile, décalé d'une distance et d'une direction qui ne
    dépendent que de la fiche et d'un secret du serveur (voir le module). La direction est la
    même quel que soit le rayon ; seule la distance s'adapte."""
    empreinte = salted_hmac("secteurs-vulnerables", str(identifiant)).digest()
    angle = int.from_bytes(empreinte[:4], "big") / 2**32 * 2 * math.pi
    # Racine carrée : sans elle les centres se tasseraient près du domicile au lieu de se
    # répartir également sur tout le disque.
    distance = math.sqrt(int.from_bytes(empreinte[4:8], "big") / 2**32) * PART_DE_DECALAGE * rayon_m
    return _deplacer(longitude, latitude, distance * math.cos(angle), distance * math.sin(angle))


def _distance_m(a, b) -> float:
    """Distance entre deux points (longitude, latitude), à plat : juste à quelques centimètres
    près sur moins d'un kilomètre, et sans requête."""
    est = (a[0] - b[0]) * _METRES_PAR_DEGRE * math.cos(math.radians((a[1] + b[1]) / 2))
    nord = (a[1] - b[1]) * _METRES_PAR_DEGRE
    return math.hypot(est, nord)


def secteur_de(identifiant, domicile, adresses) -> tuple[tuple[float, float], int]:
    """Le cercle d'une fiche : `(centre, rayon)`. Le rayon grandit tant que le cercle ne contient
    pas assez d'adresses voisines pour ne pas désigner une maison (habitat isolé).

    `domicile` : (longitude, latitude) ; `adresses` : celles du relevé de la commune."""
    centre, rayon = domicile, RAYONS_M[-1]
    for rayon in RAYONS_M:
        centre = centre_decale(identifiant, domicile[0], domicile[1], rayon)
        # Les voisins : les adresses du cercle autres que le domicile lui-même.
        voisins = sum(1 for a in adresses if a != domicile and _distance_m(a, centre) <= rayon)
        if voisins >= VOISINS_MIN:
            break
    return centre, rayon


def _deplacer(longitude, latitude, est_m, nord_m):
    return (longitude + est_m / (_METRES_PAR_DEGRE * math.cos(math.radians(latitude))),
            latitude + nord_m / _METRES_PAR_DEGRE)


def cercle(longitude: float, latitude: float, rayon_m: float = RAYON_M) -> list:
    """Le contour d'un cercle de `rayon_m` mètres, en coordonnées (un polygone fermé) : la carte
    trace des surfaces en mètres, alors qu'un point y garderait la même taille à tout zoom."""
    contour = [
        list(_deplacer(longitude, latitude, rayon_m * math.cos(2 * math.pi * i / _SOMMETS),
                       rayon_m * math.sin(2 * math.pi * i / _SOMMETS)))
        for i in range(_SOMMETS)
    ]
    return [contour + [contour[0]]]


def secteurs(personnes, commune_code: str, environment) -> dict:
    """Les cercles à tracer, et le nombre de fiches qu'on n'a pas su situer.

    Aucune propriété sur les cercles : ni nom, ni besoin, ni identifiant, ni rayon. Deux
    personnes à la même adresse donnent deux cercles décalés différemment — on ne les fusionne
    pas, parce que « deux personnes ici » est une information que l'équipe doit avoir."""
    from .rattachement_adresses import Releve

    personnes = list(personnes)
    index = Releve(commune_code, environment)
    releve = index.adresses
    points = [(a.location.x, a.location.y) for a in releve]

    cercles, situees = [], []
    for personne in personnes:
        # Par le lien enregistré sur la fiche d'abord, à défaut par le texte de son adresse.
        adresse = index.adresse_de(personne)
        if adresse is None:
            continue
        centre, rayon = secteur_de(personne.id, (adresse.location.x, adresse.location.y), points)
        cercles.append({"type": "Feature", "properties": {},
                        "geometry": {"type": "Polygon", "coordinates": cercle(centre[0], centre[1], rayon)}})
        situees.append(personne.id)
    return {
        "type": "FeatureCollection", "features": cercles, "libelle": LIBELLE,
        "situees": len(cercles), "non_situees": len(personnes) - len(cercles),
        "releve_disponible": bool(releve),
        # Pour la main courante : quelles fiches ont été montrées (leurs identifiants, rien d'autre).
        "_fiches": situees,
    }
