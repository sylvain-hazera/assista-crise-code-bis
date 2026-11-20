"""Rattacher chaque personne du registre à une adresse de la commune.

Jusqu'ici l'adresse d'une personne vulnérable était un texte libre, retrouvé à chaque affichage
par comparaison avec le relevé de la commune. « 12 rue de l'Eglise » se retrouvait, « 12 r. de
l'Eglise » non, et rien ne le disait à celui qui saisissait.

Le lien est maintenant **enregistré une fois** : la fiche garde l'identifiant de l'adresse dans
la Base Adresse Nationale (`PersonneVulnerable.adresse_ban_id`). Ce lien sert ensuite partout où
la question est « chez qui aller » : le niveau d'eau qui atteint l'adresse (simulation), le
cercle sur la carte, et pendant une crise l'état des dégâts constaté sur l'habitation de cette
adresse (`Habitation.ban_id`).

**D'où viennent les adresses de la commune.** De trois sources, mises ensemble : le relevé que
la simulation d'inondation rapatrie de la Base Adresse Nationale (`AdresseSimuleeInondation`) ;
les habitations référencées pour le suivi des dégâts d'une crise, quel que soit le sinistre —
feu, tempête, eau (`Habitation`) ; et, à défaut des deux, un relevé simple sans simulation
(`relever_les_adresses`), demandé AUTOMATIQUEMENT dès que la carte ou le registre constate
qu'aucune adresse n'est connue (`demander_le_releve`, 20/11/2026). Le rattachement ne dépend donc pas du risque
d'inondation. Aucune adresse de personne vulnérable ne part vers un service de recherche
d'adresses, pas même ce que l'agent tape : la recherche se fait dans ce relevé, sur notre serveur.

**L'identifiant est chiffré**, comme l'adresse : il la désigne aussi sûrement qu'elle. Le
rapprochement se fait donc en mémoire, pour les seules personnes habilitées, jamais par une
jointure en base que n'importe quelle requête pourrait rejouer.

Une fiche dont l'adresse n'est dans aucun relevé (lieu-dit non référencé, relevé pas encore
fait) reste utilisable : le rattachement est proposé, jamais exigé.
"""
import difflib

from .models import AdresseSimuleeInondation, Habitation
from .secteurs_vulnerables import cle_d_adresse

#: En deçà, deux adresses ne se ressemblent pas assez pour être proposées l'une pour l'autre.
RESSEMBLANCE_MIN = 0.72
MAX_PROPOSITIONS = 5
MAX_RESULTATS = 8


class AdresseDeHabitation:
    """Une habitation référencée, vue comme une adresse du relevé. Pas de niveau d'eau : elle
    ne vient pas de la simulation (`simulee` faux)."""
    seuil_inondation_metres = None
    altitude_metres = None

    def __init__(self, habitation):
        self.ban_id, self.adresse, self.location = habitation.ban_id, habitation.adresse, habitation.location


def relever_les_adresses(commune_code: str, environment) -> int:
    """Rapatrie les adresses de la commune depuis la Base Adresse Nationale, sans rien simuler.

    Pour les communes qui n'ont pas lancé (ou pas besoin) de simulation d'inondation : sans
    cela, on ne pouvait rattacher une personne à son adresse que là où l'eau avait été simulée.
    Les adresses sont gardées dans la même table que celles de la simulation, sans altitude ni
    niveau d'eau ; une simulation lancée plus tard les remplace par les siennes, et les liens
    tiennent puisqu'ils portent l'identifiant national de l'adresse. Seul le code de la commune
    part vers la Base Adresse Nationale. Ne touche à rien si un relevé existe déjà."""
    from django.contrib.gis.geos import Point

    from .habitations import scanner_ban_commune

    if AdresseSimuleeInondation.objects.filter(commune_code=commune_code, environment=environment).exists():
        return 0
    resultat = scanner_ban_commune(commune_code)
    if resultat["erreur"]:
        raise RuntimeError(f"Relevé des adresses impossible pour {commune_code} : {resultat['erreur']}")
    lignes = [AdresseSimuleeInondation(
        commune_code=commune_code, ban_id=a.get("ban_id"), adresse=a["adresse"],
        location=Point(a["lon"], a["lat"], srid=4326), environment=environment) for a in resultat["adresses"]]
    AdresseSimuleeInondation.objects.bulk_create(lignes)
    return len(lignes)


#: Une demande de relevé par commune et par demi-heure au plus : la carte et le registre la
#: refont à chaque affichage tant qu'aucune adresse n'est connue.
DELAI_ENTRE_DEMANDES_S = 1800


def cle_de_demande(commune_code: str, environment) -> str:
    return f"releve-adresses:{environment}:{commune_code}"


def demander_le_releve(commune_code: str, environment) -> bool:
    """Demande en tâche de fond le relevé simple des adresses de la commune (voir
    `relever_les_adresses`), une fois par demi-heure au plus. Appelé quand la carte ou le
    registre constate qu'aucune adresse n'est connue : une personne vulnérable l'est quel que
    soit le risque -- tempête, coupure d'électricité, canicule, inondation --, et ses secteurs ne
    doivent pas attendre qu'une simulation d'inondation ait été lancée. Seul le code de la
    commune part vers la Base Adresse Nationale. Rend vrai : un relevé est en cours."""
    from django.core.cache import cache

    from .tasks import relever_adresses_commune_task

    if cache.add(cle_de_demande(commune_code, environment), 1, DELAI_ENTRE_DEMANDES_S):
        relever_adresses_commune_task.delay(commune_code, environment)
    return True


class Releve:
    """Le relevé d'adresses d'une commune, indexé pour les rapprochements."""

    def __init__(self, commune_code: str, environment):
        self.adresses = list(AdresseSimuleeInondation.objects.filter(commune_code=commune_code, environment=environment))
        # Les maisons référencées pour le suivi des dégâts d'une crise (relevé de la Base Adresse
        # Nationale ou pointage terrain) sont aussi des adresses de la commune : une commune
        # touchée par un incendie ou une tempête n'a pas forcément de simulation d'inondation.
        connues = {a.ban_id for a in self.adresses if a.ban_id}
        for habitation in (Habitation.objects.filter(commune_code=commune_code, environment=environment)
                           .exclude(ban_id__isnull=True).exclude(ban_id="").exclude(location__isnull=True)):
            if habitation.ban_id not in connues:
                connues.add(habitation.ban_id)
                self.adresses.append(AdresseDeHabitation(habitation))
        self.par_ban = {a.ban_id: a for a in self.adresses if a.ban_id}
        self.par_cle = {}
        for adresse in self.adresses:
            self.par_cle.setdefault(cle_d_adresse(adresse.adresse), adresse)

    @property
    def disponible(self) -> bool:
        return bool(self.adresses)

    def adresse_de(self, personne):
        """L'adresse relevée d'une fiche : par son lien enregistré d'abord, à défaut par le texte
        de son adresse (les fiches saisies avant le rattachement). None si on ne la retrouve pas."""
        if personne.adresse_ban_id and personne.adresse_ban_id in self.par_ban:
            return self.par_ban[personne.adresse_ban_id]
        cle = cle_d_adresse(personne.adresse)
        return self.par_cle.get(cle) if cle else None

    def chercher(self, texte: str) -> list:
        """Les adresses du relevé qui contiennent tous les mots tapés, les plus courtes d'abord."""
        mots = cle_d_adresse(texte).split()
        if not mots or len("".join(mots)) < 3:
            return []
        trouvees = [(cle, a) for cle, a in self.par_cle.items() if all(mot in cle for mot in mots)]
        # Le numéro tapé en entier passe devant « 12 » trouvé dans « 112 ».
        trouvees.sort(key=lambda paire: (not all(mot in paire[0].split() for mot in mots), len(paire[0]), paire[0]))
        return [a for _cle, a in trouvees[:MAX_RESULTATS]]

    def propositions(self, personne) -> list[dict]:
        """Ce qu'on propose pour une fiche non rattachée : l'adresse identique si elle existe,
        sinon celles qui lui ressemblent le plus."""
        cle = cle_d_adresse(personne.adresse)
        if not cle:
            return []
        if cle in self.par_cle:
            return [self._proposition(self.par_cle[cle], True)]
        proches = difflib.get_close_matches(cle, list(self.par_cle), n=MAX_PROPOSITIONS, cutoff=RESSEMBLANCE_MIN)
        return [self._proposition(self.par_cle[proche], False) for proche in proches]

    @staticmethod
    def _proposition(adresse, exacte: bool) -> dict:
        return {"ban_id": adresse.ban_id, "adresse": adresse.adresse, "exacte": exacte}


def etat_du_rattachement(personnes, releve: Releve) -> dict:
    """Où en est le registre d'une commune : combien de fiches sont rattachées, et pour les
    autres ce qu'on propose. Nominatif : à ne rendre qu'aux personnes habilitées."""
    a_rattacher, rattachees = [], 0
    for personne in personnes:
        if personne.adresse_ban_id and personne.adresse_ban_id in releve.par_ban:
            rattachees += 1
            continue
        propositions = [p for p in releve.propositions(personne) if p["ban_id"]]
        a_rattacher.append({
            "id": str(personne.id), "nom": f"{(personne.prenom or '').strip()} {(personne.nom or '').strip()}".strip(),
            "adresse": personne.adresse or "", "propositions": propositions,
            # Un lien vers une adresse qui a disparu du relevé (voie renommée, relevé refait).
            "lien_perdu": bool(personne.adresse_ban_id),
        })
    a_rattacher.sort(key=lambda fiche: (not fiche["propositions"], fiche["nom"].casefold()))
    return {
        "releve_disponible": releve.disponible, "fiches": rattachees + len(a_rattacher), "rattachees": rattachees,
        "exactes": sum(1 for fiche in a_rattacher if fiche["propositions"] and fiche["propositions"][0]["exacte"]),
        "a_rattacher": a_rattacher,
    }


def degats_constates(personnes, releve: Releve, environment) -> dict:
    """`{identifiant de fiche: état des dégâts}` pour les fiches dont l'adresse correspond à une
    habitation suivie (estimation des dégâts d'une crise). C'est ce que le rattachement apporte
    en crise : savoir, pour chaque personne du registre, ce qui a été constaté chez elle."""
    ban_des_fiches = {}
    for personne in personnes:
        adresse = releve.adresse_de(personne)
        if adresse is not None and adresse.ban_id:
            ban_des_fiches[personne.id] = adresse.ban_id
    if not ban_des_fiches:
        return {}
    etats = {}
    habitations = (Habitation.objects.filter(environment=environment, ban_id__in=set(ban_des_fiches.values()))
                   .order_by("modifie_le"))
    for habitation in habitations:     # la plus récemment modifiée l'emporte
        etats[habitation.ban_id] = habitation.get_statut_evaluation_display()
    return {fiche: etats[ban] for fiche, ban in ban_des_fiches.items() if ban in etats}
