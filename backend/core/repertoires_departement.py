"""Répertoires de crise redistribués du département vers les EPCI et les communes (22/11/2026).

Demande de Sylvain, après l'amorçage de la Gironde : « à mesure de l'import, il faut redispatcher
les éléments en les partageant entre le département, les EPCI et les communes. Il faut aussi
compléter les répertoires de crise des communes avec les coordonnées trouvées pour elles, pour
leurs services, mais leur EPCI, leur SDIS, leurs communes voisines… »

Les données territoriales (adresses, risques, servitudes, sites sensibles) sont déjà partagées par
leur code commune : rien à redistribuer. Le répertoire de crise, lui, est une liste de fiches
(`InterlocuteurAlertePCS`) rattachées à des institutions : on les rattache aussi aux mairies et aux
EPCI concernés.

Qui reçoit quoi :
- service d'échelle départementale (préfecture, SDIS, SAMU, ARS, DDT, groupement de gendarmerie) :
  toutes les mairies et tous les EPCI du département ;
- sous-préfecture : les mairies de son arrondissement (Code officiel géographique de l'INSEE) ;
- autres services (gendarmerie, commissariat, CCAS, police municipale) : les communes de leur
  compétence telle que l'Annuaire la publie (`pivot[].code_insee_commune`, vérifié le 22/11/2026 :
  la brigade de Langon en couvre 26), à défaut leur commune d'implantation ;
- et chaque fois, l'EPCI des communes servies.
Puis (`distribuer`) : la fiche de l'EPCI à ses mairies, celles des mairies à leur EPCI et au
conseil départemental, celle des EPCI au conseil départemental, et à chaque mairie ses voisines.

Rejouable sans doublon : chaque fiche créée ici porte `cle_source` (identifiant Annuaire, ou
`institution:` / `voisine:` + l'identifiant de la collectivité copiée). Les rattachements sont
ajoutés, jamais retirés ; une fiche saisie à la main n'est jamais touchée.
"""
import csv
import io
import json
import logging
import urllib.request

from django.core.cache import cache

logger = logging.getLogger(__name__)

#: Services qui servent tout le département.
ECHELLE_DEPARTEMENT = {"prefecture", "sdis", "samu", "ddt", "ars_antenne", "gendarmerie_departementale"}

COG_COMMUNES = "https://www.insee.fr/fr/statistiques/fichier/8377162/v_commune_2025.csv"
COG_ARRONDISSEMENTS = "https://www.insee.fr/fr/statistiques/fichier/8377162/v_arrondissement_2025.csv"
CONTOURS = "https://geo.api.gouv.fr/departements/{dep}/communes?fields=code,contour&format=json"


def _lire(url, timeout=60):
    requete = urllib.request.Request(url, headers={"User-Agent": "assista-crise"})
    with urllib.request.urlopen(requete, timeout=timeout) as reponse:
        return reponse.read()


def competence(record: dict, type_service: str) -> list:
    """Les communes que l'Annuaire déclare servies par ce service (vide s'il ne le dit pas)."""
    f = (record or {}).get("fields", record) or {}
    pivot = f.get("pivot")
    if isinstance(pivot, str):
        try:
            pivot = json.loads(pivot)
        except ValueError:
            pivot = []
    codes = []
    for entree in pivot or []:
        if isinstance(entree, dict) and entree.get("type_service_local") == type_service:
            codes += [c for c in (entree.get("code_insee_commune") or []) if c]
    return sorted(set(codes))


def arrondissements(departement: str, lire=_lire) -> dict:
    """{code commune: code arrondissement} pour le département, d'après le COG (mis en cache une
    semaine). Vide si le fichier ne se lit pas : la sous-préfecture n'est alors rattachée qu'à sa
    commune, ce que l'étape signale."""
    cle = f"cog:arrondissements:{departement}"
    resultat = cache.get(cle)
    if resultat is not None:
        return resultat
    try:
        lignes = csv.DictReader(io.StringIO(lire(COG_COMMUNES).decode("utf-8")))
        resultat = {l["COM"]: l["ARR"] for l in lignes
                    if l.get("TYPECOM") == "COM" and l.get("DEP") == departement and l.get("ARR")}
    except Exception:  # noqa: BLE001
        logger.exception("Code officiel géographique illisible")
        return {}
    cache.set(cle, resultat, 7 * 24 * 3600)
    return resultat


def voisines(departement: str, lire=_lire) -> dict:
    """{code commune: {codes des communes dont le contour touche le sien}}, dans le département."""
    from django.contrib.gis.geos import GEOSGeometry

    donnees = json.loads(lire(CONTOURS.format(dep=departement), timeout=120))
    formes = {}
    for c in donnees:
        if c.get("contour"):
            try:
                formes[c["code"]] = GEOSGeometry(json.dumps(c["contour"]), srid=4326)
            except Exception:  # noqa: BLE001
                continue
    emprises = {code: g.extent for code, g in formes.items()}
    resultat = {code: set() for code in formes}
    codes = sorted(formes)
    for i, a in enumerate(codes):
        ax0, ay0, ax1, ay1 = emprises[a]
        for b in codes[i + 1:]:
            bx0, by0, bx1, by1 = emprises[b]
            if bx0 > ax1 or bx1 < ax0 or by0 > ay1 or by1 < ay0:
                continue
            if formes[a].intersects(formes[b]):
                resultat[a].add(b)
                resultat[b].add(a)
    return resultat


class Territoire:
    """Les collectivités du département, chargées une fois."""

    def __init__(self, cg):
        from .models import Commune, Institution

        self.cg = cg
        dep = cg.departement_code
        self.epci_par_commune = dict(Commune.objects.filter(departement_code=dep).values_list("code", "epci_code"))
        self.mairies = {}
        for m in (Institution.objects.filter(type__code__iexact="mairie", commune_code__in=list(self.epci_par_commune),
                                             actif=True).order_by("date_creation")):
            self.mairies.setdefault(m.commune_code, m)
        codes_epci = {e for e in self.epci_par_commune.values() if e}
        self.epcis = {}
        for e in Institution.objects.filter(type__code__iexact="epci", epci_code__in=codes_epci, actif=True).order_by("date_creation"):
            self.epcis.setdefault(e.epci_code, e)
        self._arrondissements = None

    def arrondissement_de(self, code):
        if self._arrondissements is None:
            self._arrondissements = arrondissements(self.cg.departement_code)
        return self._arrondissements.get(code)

    def communes_de_l_arrondissement(self, code):
        arr = self.arrondissement_de(code)
        return [c for c, a in self._arrondissements.items() if a == arr] if arr else [code]

    def institutions_de(self, communes):
        cibles = set()
        for code in communes:
            if code in self.mairies:
                cibles.add(self.mairies[code])
            epci = self.epcis.get(self.epci_par_commune.get(code))
            if epci is not None:
                cibles.add(epci)
        return cibles

    def toutes(self):
        return set(self.mairies.values()) | set(self.epcis.values())


def cibles_du_service(territoire, type_service, implantation, servies) -> set:
    if type_service in ECHELLE_DEPARTEMENT:
        return territoire.toutes()
    if type_service == "sous_pref":
        return territoire.institutions_de(territoire.communes_de_l_arrondissement(implantation))
    return territoire.institutions_de(servies or [implantation])


def rattacher_services(cg, services) -> int:
    """`services` : liste de (fiche InterlocuteurAlertePCS, type, commune d'implantation, communes
    servies). Rend le nombre de rattachements nouveaux."""
    territoire = Territoire(cg)
    nouveaux = 0
    for contact, type_service, implantation, servies in services:
        cibles = cibles_du_service(territoire, type_service, implantation, servies) | {cg}
        deja = set(contact.institutions.values_list("id", flat=True))
        a_ajouter = [i for i in cibles if i.id not in deja]
        if a_ajouter:
            contact.institutions.add(*a_ajouter)
            nouveaux += len(a_ajouter)
    return nouveaux


def _coordonnees(institution):
    """Le référent s'il est indiqué, sinon les coordonnées officielles."""
    from .models import ReferentCollectivite
    r = ReferentCollectivite.objects.filter(institution=institution).first()
    email = (r.email if r and r.email else None) or institution.email
    telephone = (r.telephone if r and r.telephone else None) or institution.telephone
    notes = institution.adresse or ""
    if r and (r.nom or r.fonction):
        notes = (f"Référent : {r.nom}{' (' + r.fonction + ')' if r.fonction else ''}\n" + notes).strip()
    return email, telephone, notes or None


def copie(institution, prefixe, categorie, organisme):
    """La fiche qui reproduit les coordonnées d'une collectivité dans les répertoires des autres
    (créée ou remise à jour)."""
    from .models import InterlocuteurAlertePCS
    email, telephone, notes = _coordonnees(institution)
    contact, creee = InterlocuteurAlertePCS.objects.update_or_create(
        cle_source=f"{prefixe}:{institution.id}", environment=institution.environment,
        defaults={"nom": institution.nom, "organisme": organisme, "categorie": categorie, "email": email,
                  "telephone": telephone, "notes": notes,
                  "departement_code": institution.departement_code or (institution.commune_code or "")[:2] or None})
    if creee:  # rien ne part tout seul : quelqu'un coche qui prévenir
        contact.prevenir_ouverture_crise = False
        contact.save(update_fields=["prevenir_ouverture_crise"])
    return contact


def resynchroniser(institution) -> int:
    """Après une modification des coordonnées : remet à jour les copies existantes."""
    from .models import InterlocuteurAlertePCS
    n = 0
    for prefixe in ("institution", "voisine"):
        existante = InterlocuteurAlertePCS.objects.filter(cle_source=f"{prefixe}:{institution.id}").first()
        if existante is not None:
            copie(institution, prefixe, existante.categorie, existante.organisme)
            n += 1
    return n


def _ajouter(contact, institutions) -> int:
    deja = set(contact.institutions.values_list("id", flat=True))
    a_ajouter = [i for i in institutions if i is not None and i.id not in deja]
    if a_ajouter:
        contact.institutions.add(*a_ajouter)
    return len(a_ajouter)


def distribuer(cg, lire_voisines=voisines) -> dict:
    """EPCI ↔ mairies, EPCI → conseil départemental, voisines. Rend les comptes."""
    from .models import CategorieInterlocuteurPCS as C

    territoire = Territoire(cg)
    comptes = {"fiches_epci": 0, "fiches_mairies": 0, "rattachements": 0, "voisinages": 0, "erreurs": []}
    copies_epci = {}
    for code_epci, epci in territoire.epcis.items():
        copies_epci[code_epci] = copie(epci, "institution", C.EPCI_INTERCOMMUNALITE, "epci")
        comptes["fiches_epci"] += 1
        comptes["rattachements"] += _ajouter(copies_epci[code_epci], [cg])
    for code, mairie in territoire.mairies.items():
        fiche = copie(mairie, "institution", C.ELU_PERSONNEL_COMMUNAL, "mairie")
        comptes["fiches_mairies"] += 1
        code_epci = territoire.epci_par_commune.get(code)
        comptes["rattachements"] += _ajouter(fiche, [territoire.epcis.get(code_epci), cg])
        if code_epci in copies_epci:
            comptes["rattachements"] += _ajouter(copies_epci[code_epci], [mairie])
    try:
        carte = lire_voisines(cg.departement_code)
    except Exception as exc:  # noqa: BLE001
        comptes["erreurs"].append(f"Communes voisines : contours illisibles ({exc})"[:200])
        carte = {}
    for code, autour in carte.items():
        if code not in territoire.mairies:
            continue
        fiche = copie(territoire.mairies[code], "voisine", C.COMMUNE_VOISINE, "mairie")
        ajoutes = _ajouter(fiche, [territoire.mairies.get(v) for v in autour])
        comptes["voisinages"] += ajoutes
        comptes["rattachements"] += ajoutes
    comptes["erreurs"] = comptes["erreurs"][:20]
    return comptes
