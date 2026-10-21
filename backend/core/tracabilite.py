"""Traçabilité des consultations dans la main courante (AuditLog) -- demande du 21/10/2026 :
partir de n'importe quelle fiche (une annonce, une personne, une crise...) et retrouver QUI l'a
vue, QUAND, depuis QUELLE adresse IP et COMMENT (fiche ouverte, apparition dans une liste,
export) -- typiquement pour remonter jusqu'à quelqu'un qui aurait consulté des fiches pour en
récupérer les coordonnées.

Avant, une consultation de liste ne laissait qu'une ligne « Consultation (offer-list) », sans
dire quelles fiches avaient été renvoyées, et ouvrir une annonce depuis la page Signalements
n'envoyait aucune requête (les données venaient de la liste) : rien ne permettait de répondre.

Ce module rassemble les règles ; c'est AuditTraceMiddleware (core/middleware.py) qui les
applique à chaque réponse /api/, sans rien à ajouter vue par vue :
- `objets_exposes` lit dans la réponse les identifiants des fiches renvoyées (liste, page ou
  fiche seule) -- la trace est faite côté serveur, elle vaut donc aussi pour quelqu'un qui
  appellerait l'API directement avec son jeton, sans passer par l'interface ;
- `perimetre_de` rattache la ligne à une crise (ou au fonctionnement général du site) d'après
  ces mêmes fiches ;
- `parametres_recherche` conserve les termes et filtres de recherche (chercher un nom est
  souvent le premier geste d'une collecte malveillante) ;
- `retirer_coordonnees` enlève email et téléphone des LISTES d'annonces : ils ne viennent plus
  qu'avec la fiche ouverte, dont la consultation est alors tracée précisément.
"""
import ipaddress
import uuid
from functools import lru_cache

from .models import AuditLog

# Comptes de service (ponts radio, satellites, automates) : pont-…@assista-crise.local,
# satellite-…@service.assista-crise.local. Même règle qu'AuditTraceMiddleware pour ne pas
# journaliser leurs lectures en boucle ; sert ici à la case « Masquer les comptes système ».
SUFFIXES_COMPTES_SYSTEME = ('@assista-crise.local', '.assista-crise.local')


def est_compte_systeme(utilisateur):
    if utilisateur is None or not getattr(utilisateur, 'is_authenticated', False):
        return False
    return (utilisateur.username or '').lower().endswith(SUFFIXES_COMPTES_SYSTEME)


# ── Coordonnées retirées des listes d'annonces ────────────────────────────────────────────
#
# Une liste d'annonces renvoyait email et téléphone de chaque fiche : ouvrir la page
# Signalements (ou appeler l'API) récupérait d'un coup les coordonnées de toute la zone. Elles
# ne viennent désormais qu'avec la fiche (`retrieve`), dont l'ouverture est tracée objet par
# objet. Les écrans qui affichent légitimement les coordonnées DANS un tableau (cellule de crise,
# logement des intervenants, équipes, « mes signalements ») les demandent explicitement par
# ?avec_coordonnees=1 -- leur consultation est alors tracée comme une liste AVEC coordonnées,
# ce qui permet à l'enquête de distinguer les deux cas. Les actions dédiées (vue_secteur,
# vue_mairie...) ne sont pas des `list` et gardent leur comportement.

CHAMPS_COORDONNEES = {
    'Offer': ('email_offer', 'phone_offer', 'author_email', 'author_phone'),
    'Request': ('email_request', 'phone_request', 'author_email'),
    'Information': ('email_information', 'phone_information', 'author_email'),
}
PARAM_AVEC_COORDONNEES = 'avec_coordonnees'
# ?motif=export : la liste est relue pour produire un fichier (export CSV de la page
# Signalements) -- tracée comme EXPORT plutôt que comme simple consultation de liste.
PARAM_MOTIF = 'motif'


def motif_export(request):
    return request is not None and (request.GET.get(PARAM_MOTIF) or '').lower() == 'export'


def coordonnees_demandees(request):
    return (request.GET.get(PARAM_AVEC_COORDONNEES) or '').lower() in ('1', 'true', 'oui')


def coordonnees_retirees(request, view, nom_modele):
    """True si cette réponse doit sortir sans email/téléphone (voir l'en-tête de section)."""
    if nom_modele not in CHAMPS_COORDONNEES or request is None or view is None:
        return False
    # Seulement la liste de CE modèle : une annonce imbriquée dans la liste d'un autre objet
    # (équipes, missions...) garde ses coordonnées, comme avant.
    queryset = getattr(view, 'queryset', None)
    if queryset is None or queryset.model.__name__ != nom_modele:
        return False
    return getattr(view, 'action', None) == 'list' and not coordonnees_demandees(request)


def retirer_coordonnees(data, nom_modele):
    for champ in CHAMPS_COORDONNEES.get(nom_modele, ()):
        if champ in data:
            data[champ] = None
    return data


# ── Fiches exposées par une réponse ───────────────────────────────────────────────────────

Exposition = AuditLog.Exposition


# Référentiels (types, catalogues, compétences...) et tables techniques : les renvoyer n'expose
# personne, noter leurs identifiants à chaque lecture gonflerait la main courante pour rien.
MODELES_NON_TRACES = {
    'AuditLog', 'AuditAction', 'Notification', 'Besoin', 'BesoinCompetence', 'BesoinMateriel',
    'RequestTypeBesoin', 'OfferTypeBesoin', 'InformationTypeBesoin', 'Competence',
    'RisqueMajeurType', 'TypeVulnerabilite', 'RequestType', 'OfferType', 'InformationType',
    'MaterielCatalogue', 'InstitutionType', 'Commune', 'PointCommune',
}


def _identifiant(valeur):
    if isinstance(valeur, dict):
        valeur = valeur.get('id')
    if valeur is None:
        return None
    try:
        return str(uuid.UUID(str(valeur)))
    except (ValueError, TypeError, AttributeError):
        return None


def elements_de(data):
    """Les fiches d'une réponse DRF : page ({results: [...]}), liste brute, ou fiche seule.
    Renvoie (éléments, nature) ; ([], None) si la réponse n'en contient pas."""
    if isinstance(data, dict) and isinstance(data.get('results'), list):
        return data['results'], Exposition.LISTE
    if isinstance(data, list):
        return data, Exposition.LISTE
    if isinstance(data, dict) and _identifiant(data.get('id')):
        return [data], Exposition.FICHE
    return [], None


# Lignes « récapitulatives » sans `id` propre (ex. TeamViewSet.ressources_mobilisees : une ligne
# par personne ou matériel mobilisé) : les fiches qu'elles exposent sont désignées par ces clés.
# Lues seulement en l'absence d'`id` : sur une fiche ordinaire, l'auteur ou l'équipe liés ne
# sont pas « consultés » pour autant.
CLES_REFERENCES = ('user_id', 'utilisateur_id', 'membre_id', 'offre_id', 'offer_id', 'demande_id',
                   'request_id', 'information_id', 'proprietaire_id', 'personne_id')


def objets_exposes(data):
    """Identifiants (chaînes UUID, sans doublon, dans l'ordre) des fiches de la réponse."""
    elements, nature = elements_de(data)
    vus, ids = set(), []
    for element in elements:
        if not isinstance(element, dict):
            continue
        propre = _identifiant(element.get('id'))
        candidats = [propre] if propre else [_identifiant(element.get(cle)) for cle in CLES_REFERENCES]
        for ident in candidats:
            if ident and ident not in vus:
                vus.add(ident)
                ids.append(ident)
    return ids, nature


# ── Rattachement à une crise ──────────────────────────────────────────────────────────────

# CRISE : une seule crise concernée (AuditLog.crise renseignée) ; MULTI : plusieurs crises, ou
# crise et hors crise mêlées dans une même liste ; GENERAL : fonctionnement général du site.
Perimetre = AuditLog.Perimetre


@lru_cache(maxsize=None)
def champ_crise(modele):
    """Nom du champ qui rattache `modele` à une crise (ForeignKey, ou ManyToMany pour Team),
    None si le modèle n'est pas lié aux crises. User.affected_crisis exclu : c'est une
    préférence d'affichage, pas l'appartenance de la personne à une crise."""
    from .models import Crisis
    if modele is None:
        return None
    for champ in modele._meta.get_fields():
        if getattr(champ, 'related_model', None) is not Crisis or getattr(champ, 'auto_created', False):
            continue
        if champ.name == 'affected_crisis' or modele.__name__ == 'AuditLog':
            continue
        if champ.many_to_one or champ.many_to_many:
            return champ.name
    return None


def crise_parametre(request):
    """Crise passée en filtre de la requête (?crise= / ?crisis= / ?crise_id=), si elle existe.
    Vérifiée en base : un identifiant saisi à la main qui ne correspond à aucune crise ferait
    échouer l'écriture de la ligne entière (clé étrangère AuditLog.crise)."""
    from .models import Crisis
    if request is None:
        return None
    for cle in ('crise', 'crisis', 'crise_id', 'crisis_id'):
        ident = _identifiant(request.GET.get(cle))
        if ident:
            return ident if Crisis.objects.filter(pk=ident).exists() else None
    return None


def perimetre_de(modele, data, request=None):
    """(perimetre, crise_id) d'une réponse, d'après les fiches qu'elle contient.
    perimetre None : impossible à dire (réponse sans fiche sur un modèle lié aux crises)."""
    from .models import Crisis
    elements, _ = elements_de(data)
    parametre = crise_parametre(request)

    if modele is Crisis:
        crises = {_identifiant(e.get('id')) for e in elements if isinstance(e, dict)} - {None}
        if parametre and not crises:
            crises = {parametre}
    else:
        champ = champ_crise(modele)
        if champ is None:
            return (Perimetre.CRISE, parametre) if parametre else (Perimetre.GENERAL, None)
        crises = set()
        for element in elements:
            if not isinstance(element, dict) or champ not in element:
                continue
            valeur = element[champ]
            if isinstance(valeur, list):     # ManyToMany (Team.assigned_crises)
                crises.update({_identifiant(v) for v in valeur} or {None})
            else:
                crises.add(_identifiant(valeur))
        if not crises:
            return (Perimetre.CRISE, parametre) if parametre else (None, None)

    reelles = crises - {None}
    if len(reelles) == 1 and None not in crises:
        return Perimetre.CRISE, next(iter(reelles))
    if not reelles:
        return Perimetre.GENERAL, None
    return Perimetre.MULTI, None


# ── Paramètres de recherche ───────────────────────────────────────────────────────────────

# Navigation pure (pas un critère de recherche) et paramètre technique ci-dessus.
PARAMETRES_NAVIGATION = {'page', 'page_size', 'format', 'ordering', PARAM_AVEC_COORDONNEES, PARAM_MOTIF, 'ids'}
# Jamais journalisé : un paramètre dont le nom évoque un secret (jeton dans une URL d'activation,
# signature...). Liste par fragments plutôt que par noms exacts pour couvrir les variantes.
FRAGMENTS_SECRETS = ('token', 'jeton', 'password', 'mot_de_passe', 'secret', 'signature', 'cle', 'key')
LONGUEUR_MAX_VALEUR = 200


def parametres_recherche(request):
    """Termes et filtres de recherche d'une requête GET, sans les secrets ni la navigation ;
    None s'il n'y en a pas. Les valeurs multiples (?type=A&type=B) restent des listes."""
    if request is None or request.method not in ('GET', 'HEAD'):
        return None
    resultat = {}
    for cle in request.GET.keys():
        cle_min = cle.lower()
        if cle_min in PARAMETRES_NAVIGATION or any(f in cle_min for f in FRAGMENTS_SECRETS):
            continue
        valeurs = [v[:LONGUEUR_MAX_VALEUR] for v in request.GET.getlist(cle) if v != '']
        if valeurs:
            resultat[cle] = valeurs[0] if len(valeurs) == 1 else valeurs
    return resultat or None


# ── Filtres de la main courante ───────────────────────────────────────────────────────────

def reseau_ip(valeur):
    """Adresse ou plage (« 82.64.29.195 », « 192.168.0.0/16 ») normalisée pour Postgres ;
    ValueError si la saisie n'en est pas une."""
    return str(ipaddress.ip_network(valeur.strip(), strict=False))
