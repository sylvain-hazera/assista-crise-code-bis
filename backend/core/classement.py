"""Le classement « quoi + pour qui » (27/11/2026).

Demande de Sylvain : « transport d'animaux » revenait à « animaux à évacuer », et chaque
nouvelle catégorie recréait une boucle. Désormais :

- la **famille** dit l'action (Évacuation / transport, Hébergement, Soins, Nourriture...) :
  c'est le type de demande ou d'offre racine, repéré par son `code` ;
- le **pour qui** (`Beneficiaire` : personnes, animaux, biens) n'est demandé que si la famille
  en admet plusieurs ;
- la **catégorie d'animaux** (compagnie, équidés, bétail...) n'est demandée que pour des animaux.

Chaque situation n'a qu'un chemin : animaux à évacuer = Évacuation + animaux ; animaux blessés
= Soins + animaux ; animaux à nourrir = Nourriture + animaux.

Le rapprochement va du plus précis au plus général (`competences_pour_demande`) : une équipe
« Évacuation d'équidés » reçoit les chevaux, sans elle l'équipe « Évacuation d'animaux », puis
l'équipe de transport.
"""
from .models import Beneficiaire

P, A, B = Beneficiaire.PERSONNES.value, Beneficiaire.ANIMAUX.value, Beneficiaire.BIENS.value

#: Les « pour qui » admis par famille, côté demande et côté offre. Une demande de soins pour une
#: personne n'existe pas (retirée le 01/09/2026 : une urgence médicale, c'est le 15) ; une offre
#: de soins pour des personnes, si (professionnels de santé).
FAMILLES = {
    "EVAC": {"demande": [P, A, B], "offre": [P, A, B], "libelle": "Évacuation / transport"},
    "ABRI": {"demande": [P, A], "offre": [P, A], "libelle": "Hébergement"},
    "SOIN": {"demande": [A], "offre": [P, A], "libelle": "Soins"},
    "NOUR": {"demande": [P, A], "offre": [P, A], "libelle": "Nourriture et eau"},
    "PSY": {"demande": [P], "offre": [P], "libelle": "Soutien psychologique"},
    "ADMIN": {"demande": [P], "offre": [P], "libelle": "Accompagnement administratif"},
    "LANG": {"demande": [], "offre": [], "libelle": "Interprétariat / traduction"},
    "NETT": {"demande": [B], "offre": [B], "libelle": "Nettoyage / déblaiement"},
    "MAT": {"demande": [], "offre": [], "libelle": "Matériel et engins"},
    "AUTRE": {"demande": [P, A, B], "offre": [P, A, B], "libelle": "Autre"},
}

#: Libellés courts pour la radio et les compteurs.
COURT = {P: "personnes", A: "animaux", B: "biens"}


def code_du_type(type_obj):
    """Le code de la famille : celui du type, sinon celui de son parent (une précision comme
    « Groupe électrogène » hérite de « Matériel »)."""
    if type_obj is None:
        return None
    code = getattr(type_obj, "code", None)
    if code:
        return code
    parent = getattr(type_obj, "parent", None) if getattr(type_obj, "parent_id", None) else None
    return getattr(parent, "code", None) if parent is not None else None


def beneficiaires_admis(type_obj, axe):
    """Les « pour qui » admis pour ce type, sur l'axe "demande" ou "offre". Vide : sans objet."""
    famille = FAMILLES.get(code_du_type(type_obj) or "")
    return list(famille[axe]) if famille else []


def normaliser(attrs, axe, instance=None):
    """Valide et complète `beneficiaire` et la catégorie d'animaux d'un dépôt. Un client ancien
    qui ne les envoie pas reçoit une valeur déduite. Rend un dict d'erreurs (vide si recevable)
    et modifie `attrs` en place."""
    champ_type = "request_type" if axe == "demande" else "offer_type"
    type_obj = attrs.get(champ_type) or (getattr(instance, champ_type, None) if instance else None)
    if type_obj is None:
        return {}
    admis = beneficiaires_admis(type_obj, axe)
    donne = attrs.get("beneficiaire", getattr(instance, "beneficiaire", None) if instance else None)
    erreurs = {}
    if not admis:
        attrs["beneficiaire"] = None
    elif donne:
        if donne not in admis:
            libelles = ", ".join(COURT[b] for b in admis)
            erreurs["beneficiaire"] = f"Pour ce besoin, choisissez parmi : {libelles}."
    else:
        attrs["beneficiaire"] = _deduire(attrs, axe, admis)
    beneficiaire = attrs.get("beneficiaire", donne)
    if beneficiaire != A:
        if axe == "demande":
            attrs["categorie_animaux"] = None
            attrs["nombre_animaux"] = None
        else:
            attrs["categories_animaux"] = []
    return erreurs


def _deduire(attrs, axe, admis):
    if axe == "offre":
        transport = attrs.get("transport_type")
        par_transport = {"PERSONNES": P, "ANIMAUX": A, "MATERIEL": B}.get(transport or "")
        if par_transport in admis:
            return par_transport
    if len(admis) == 1:
        return admis[0]
    return P if P in admis else admis[0]


def libelle_radio(type_obj, beneficiaire=None):
    """« Évacuation · animaux » : la famille et, s'il y a lieu, le pour qui. La radio n'a pas à
    en dire plus (décision du 27/11/2026)."""
    if type_obj is None:
        return ""
    racine = type_obj.parent if getattr(type_obj, "parent_id", None) else type_obj
    nom = str(racine)
    if beneficiaire and len(beneficiaires_admis(type_obj, "demande")) > 1:
        return f"{nom.split(' / ')[0]} · {COURT.get(beneficiaire, '')}".strip(" ·")
    return nom


def competences_pour(besoin, beneficiaire=None, categorie=None):
    """Les compétences d'un besoin, de la plus précise à la plus générale :
    (pour qui + catégorie), puis (pour qui), puis la correspondance générale."""
    from .models import BesoinCompetence

    if besoin is None:
        return []
    lignes = list(BesoinCompetence.objects.filter(besoin=besoin, competence__isnull=False).select_related("competence"))
    paliers = []
    if beneficiaire and categorie:
        paliers.append([l for l in lignes if l.beneficiaire == beneficiaire and l.categorie_animaux == categorie])
    if beneficiaire:
        paliers.append([l for l in lignes if l.beneficiaire == beneficiaire and not l.categorie_animaux])
    paliers.append([l for l in lignes if not l.beneficiaire and not l.categorie_animaux])
    vues, ordre = set(), []
    for palier in paliers:
        # Une compétence fine (« Évacuation d'animaux ») passe avant son groupe (« Soutien aux
        # animaux ») au même palier.
        for l in sorted(palier, key=lambda x: (x.competence.parent_id is None, x.competence.nom)):
            if l.competence_id not in vues:
                vues.add(l.competence_id)
                ordre.append(l.competence)
    return ordre


def competences_pour_demande(demande):
    from .models import RequestTypeBesoin

    pont = RequestTypeBesoin.objects.filter(request_type=demande.request_type).select_related("besoin").first()
    if pont is None:
        return []
    return competences_pour(pont.besoin, demande.beneficiaire, demande.categorie_animaux)


def choisir(crise, competences, objet):
    """(compétence, équipe) : la plus précise des compétences pour laquelle une équipe est
    trouvée. Sans équipe, la plus précise qu'une équipe surveille sur la crise, sinon la plus
    générale (celle que les régulateurs suivent)."""
    from .models import AffectationCompetence
    from .views import meilleure_equipe_pour_competence

    if not competences:
        return None, None
    if crise is not None:
        for competence in competences:
            equipe = meilleure_equipe_pour_competence(crise, competence, objet)
            if equipe is not None:
                return competence, equipe
        for competence in competences:
            if AffectationCompetence.objects.filter(crise=crise, competence=competence, active=True).exists():
                return competence, None
    return competences[-1], None
