"""Filtres, libellés et recherche de fiches de la page Main courante (AuditLogViewSet, mode
consultation globale) -- demande du 21/10/2026 : pouvoir enquêter (« qui a vu cette fiche ? »,
« qu'a fait cette personne, sauf depuis tel poste ? ») avec des critères cumulables.

Règle de combinaison, la même pour tous les critères :
- chaque critère a une liste « inclure » (?ip=...) et une liste « exclure » (?ip_exclu=...),
  les deux pouvant servir en même temps (tout un réseau SAUF une machine) ;
- plusieurs valeurs incluses : l'une OU l'autre suffit ; plusieurs exclues : toutes écartées ;
- critères différents : tous doivent être vrais (ET).
Une exclusion ne fait jamais disparaître les lignes où la valeur est absente (exclure une IP
garde les lignes sans IP, exclure un utilisateur garde les actions anonymes).

Toutes les colonnes filtrées ici sont indexées (voir AuditLog.Meta.indexes), pour que la page
reste rapide sur plusieurs millions de lignes -- y compris les plages d'adresses IP.
"""
import datetime
import uuid

from django.db.models import GenericIPAddressField, Lookup, Q, TextField
from django.db.models.functions import Cast
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import ValidationError

from .tracabilite import reseau_ip


@GenericIPAddressField.register_lookup
class DansReseau(Lookup):
    """adresse_ip__dans_reseau='192.168.0.0/16' : l'adresse appartient à la plage (ou est égale
    à l'adresse donnée). Opérateur Postgres `<<=` sur le type inet, servi par un index B-tree
    ordinaire (Postgres le traduit en bornes de plage)."""
    lookup_name = 'dans_reseau'

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        return f'{lhs} <<= %s::inet', [*lhs_params, self.rhs]


def _uuid(valeur):
    try:
        return uuid.UUID(str(valeur).strip())
    except (ValueError, TypeError, AttributeError):
        return None


def _valeurs(params, cle):
    return [v.strip() for v in params.getlist(cle) if v and v.strip()]


def _date(valeur, fin=False):
    """Date seule (« 2026-10-21 ») ou date et heure (« 2026-10-21T14:30 », saisie à la minute) ;
    une date seule en borne de FIN couvre toute la journée."""
    if not valeur:
        return None
    # Date seule testée d'abord : parse_datetime l'accepte aussi (minuit), ce qui ferait
    # exclure toute la journée d'une borne de fin.
    try:
        jour = datetime.date.fromisoformat(valeur)
    except ValueError:
        jour = None
    if jour is not None:
        moment = datetime.datetime.combine(jour + datetime.timedelta(days=1) if fin else jour, datetime.time.min)
        if fin:
            moment -= datetime.timedelta(microseconds=1)
    else:
        try:
            moment = parse_datetime(valeur)
        except ValueError:
            moment = None
        if moment is None:
            raise ValidationError({'date': f"Date invalide : « {valeur} »."})
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return moment


# ── Résolution des valeurs saisies en identifiants ────────────────────────────────────────

def comptes_correspondants(valeurs):
    """Ids des comptes dont l'email, le nom ou l'identifiant contient l'une des valeurs (ou dont
    l'id est la valeur). L'email est chiffré : le déchiffrement porte sur les comptes (quelques
    dizaines), jamais sur les lignes du journal."""
    from .models import User
    ids = {_uuid(v) for v in valeurs} - {None}
    termes = [v.lower() for v in valeurs if _uuid(v) is None]
    if termes:
        for compte in User.objects.only('id', 'email', 'username', 'first_name', 'last_name'):
            texte = ' '.join(filter(None, [
                compte.email, compte.username, compte.first_name, compte.last_name,
                f'{compte.first_name} {compte.last_name}',
            ])).lower()
            if any(t in texte for t in termes):
                ids.add(compte.id)
    return ids


def institutions_correspondantes(valeurs):
    from .models import Institution
    ids = {_uuid(v) for v in valeurs} - {None}
    termes = [v for v in valeurs if _uuid(v) is None]
    if termes:
        condition = Q()
        for terme in termes:
            condition |= Q(nom__icontains=terme)
        ids.update(Institution.objects.filter(condition).values_list('id', flat=True))
    return ids


def _uuids(valeurs, critere):
    ids = []
    for valeur in valeurs:
        ident = _uuid(valeur)
        if ident is None:
            raise ValidationError({critere: f"Identifiant invalide : « {valeur} »."})
        ids.append(ident)
    return ids


def _reseaux(valeurs):
    reseaux = []
    for valeur in valeurs:
        try:
            reseaux.append(reseau_ip(valeur))
        except ValueError:
            raise ValidationError({'ip': f"Adresse ou plage IP invalide : « {valeur} » (ex. 82.64.29.195 ou 192.168.0.0/16)."})
    return reseaux


# ── Application des filtres ───────────────────────────────────────────────────────────────

PERIMETRE_INCONNU = 'INCONNU'


def appliquer_filtres(queryset, params):
    """Applique à `queryset` (AuditLog) tous les critères de la page Main courante, voir
    l'en-tête du module pour la règle de combinaison. ValidationError (400) sur une saisie
    invalide plutôt qu'un filtre silencieusement ignoré : un enquêteur doit savoir que son
    critère n'a pas été pris en compte."""

    debut = _date(params.get('date_debut'))
    if debut:
        queryset = queryset.filter(date_action__gte=debut)
    fin = _date(params.get('date_fin'), fin=True)
    if fin:
        queryset = queryset.filter(date_action__lte=fin)

    if params.get('masquer_systeme') in ('1', 'true'):
        queryset = queryset.filter(compte_systeme=False)
    if params.get('succes') in ('true', 'false'):
        queryset = queryset.filter(succes=(params['succes'] == 'true'))

    def inclure_exclure(cle, condition_pour):
        """condition_pour(valeurs) -> Q ; inclusion puis exclusion du même critère."""
        nonlocal queryset
        inclus, exclus = _valeurs(params, cle), _valeurs(params, f'{cle}_exclu')
        if inclus:
            queryset = queryset.filter(condition_pour(inclus))
        if exclus:
            queryset = queryset.exclude(condition_pour(exclus))

    inclure_exclure('action', lambda v: Q(action__code__in=v))
    inclure_exclure('objet_type', lambda v: Q(objet_type__in=v))
    inclure_exclure('exposition', lambda v: Q(exposition__in=v))
    inclure_exclure('crise', lambda v: Q(crise_id__in=_uuids(v, 'crise')))
    inclure_exclure('utilisateur', lambda v: Q(utilisateur_id__in=comptes_correspondants(v)))
    inclure_exclure('institution', lambda v: Q(institution_id__in=institutions_correspondantes(v)))

    def objets(valeurs):
        # La fiche elle-même (objet_id) OU une liste/un export qui la contenait (objets_ids).
        ids = _uuids(valeurs, 'objet')
        return Q(objet_id__in=ids) | Q(objets_ids__overlap=ids)
    inclure_exclure('objet', objets)

    def reseaux(valeurs):
        condition = Q()
        for reseau in _reseaux(valeurs):
            condition |= Q(adresse_ip__dans_reseau=reseau)
        return condition
    inclure_exclure('ip', reseaux)

    def perimetres(valeurs):
        connus = [v for v in valeurs if v != PERIMETRE_INCONNU]
        condition = Q(perimetre__in=connus) if connus else Q()
        if PERIMETRE_INCONNU in valeurs:
            condition = condition | Q(perimetre__isnull=True) if connus else Q(perimetre__isnull=True)
        return condition
    inclure_exclure('perimetre', perimetres)

    termes_inclus, termes_exclus = _valeurs(params, 'recherche'), _valeurs(params, 'recherche_exclu')
    if termes_inclus or termes_exclus:
        # Les termes sont dans un JSON ({"search": "dupont", "commune": "42218"}) : recherche
        # dans sa forme texte, limitée aux seules lignes qui en ont (index partiel).
        queryset = queryset.annotate(recherche_texte=Cast('recherche', TextField()))
        if termes_inclus:
            condition = Q()
            for terme in termes_inclus:
                condition |= Q(recherche_texte__icontains=terme)
            queryset = queryset.filter(recherche__isnull=False).filter(condition)
        for terme in termes_exclus:
            queryset = queryset.exclude(recherche_texte__icontains=terme)

    return queryset


# ── Fiches : types, libellés, recherche ───────────────────────────────────────────────────

# type -> (libellé du type, champs composant le libellé, champs en clair cherchables en SQL,
#          champs chiffrés cherchables après déchiffrement -- coordonnées comprises : une
#          victime connaît son numéro, pas l'identifiant de sa fiche)
TYPES_FICHES = {
    'Offer': ("Offre", ('title',), ('title',),
              ('first_name_offer', 'last_name_offer', 'email_offer', 'phone_offer')),
    'Request': ("Demande", ('title',), ('title',),
                ('first_name_request', 'last_name_request', 'email_request', 'phone_request')),
    'Information': ("Information", ('title',), ('title',),
                    ('first_name_information', 'last_name_information', 'email_information', 'phone_information')),
    'Crisis': ("Crise", ('name',), ('name',), ()),
    'User': ("Compte", ('first_name', 'last_name'), ('first_name', 'last_name', 'username'), ('email', 'phone_number')),
    'Team': ("Équipe", ('name',), ('name',), ()),
    'Dossier': ("Dossier", ('numero', 'titre'), ('numero', 'titre'), ()),
    'Mission': ("Mission", ('titre',), ('titre',), ()),
    'RecherchePersonne': ("Recherche de personne", ('prenom', 'nom'), (), ('nom', 'prenom', 'contact_email', 'contact_telephone')),
    'PersonneVulnerable': ("Personne vulnérable", ('prenom', 'nom'), (), ('nom', 'prenom', 'telephone')),
    'Habitation': ("Habitation", ('adresse',), (), ('adresse',)),
    'Institution': ("Institution", ('nom',), ('nom',), ()),
    'PointOperationnel': ("Point opérationnel", ('nom',), ('nom',), ()),
    'DeclarationSecurite': ("Déclaration de sécurité", ('nom_referent',), (), ('nom_referent', 'contact_referent')),
    'InterlocuteurAlertePCS': ("Interlocuteur PCS", ('nom',), (), ('nom', 'email', 'telephone')),
}
FICHE_SUPPRIMEE = "fiche supprimée"
# Plafond du déchiffrement pour une recherche sur champ chiffré (les plus récentes d'abord
# quand le modèle a une date de création) :
# borne le temps de réponse, largement au-dessus des volumes actuels (7 250 offres).
MAX_DECHIFFREMENTS = 20_000
MAX_RESULTATS = 25


def _modele(nom):
    from django.apps import apps
    return apps.get_model('core', nom)


def _libelle(fiche, nom_type):
    _, champs, _, _ = TYPES_FICHES[nom_type]
    texte = ' '.join(str(getattr(fiche, c) or '').strip() for c in champs).strip()
    if not texte and nom_type == 'User':
        texte = fiche.email or ''
    return texte or str(fiche.pk)


def libelles(paires):
    """{(type, id): libellé} pour les fiches citées par des lignes de journal -- une requête par
    type. Une fiche disparue (purge RGPD, suppression) est signalée comme telle : le journal ne
    recopie jamais le libellé, pour ne pas conserver de donnée personnelle au-delà de la fiche."""
    par_type = {}
    for nom_type, ident in paires:
        if nom_type in TYPES_FICHES and ident:
            par_type.setdefault(nom_type, set()).add(ident)
    resultat = {}
    for nom_type, ids in par_type.items():
        trouves = {f.pk: _libelle(f, nom_type) for f in _modele(nom_type).objects.filter(pk__in=ids)}
        for ident in ids:
            resultat[(nom_type, str(ident))] = trouves.get(ident, FICHE_SUPPRIMEE)
    return resultat


def rechercher_fiches(terme, types=None, environnement=None):
    """Fiches dont le libellé ou les coordonnées contiennent `terme` (ou dont l'id est `terme`),
    pour le critère « Objet » de la main courante. [{type, type_libelle, id, libelle}]."""
    terme = (terme or '').strip()
    if not terme:
        return []
    types = [t for t in (types or TYPES_FICHES) if t in TYPES_FICHES]
    ident = _uuid(terme)
    resultats = []

    for nom_type in types:
        type_libelle, _, champs_sql, champs_chiffres = TYPES_FICHES[nom_type]
        modele = _modele(nom_type)
        qs = modele.objects.all()
        if environnement and any(f.name == 'environment' for f in modele._meta.concrete_fields):
            qs = qs.filter(environment=environnement)

        trouvees = []
        if ident:
            trouvees = list(qs.filter(pk=ident))
        else:
            if champs_sql:
                condition = Q()
                for champ in champs_sql:
                    condition |= Q(**{f'{champ}__icontains': terme})
                trouvees = list(qs.filter(condition)[:MAX_RESULTATS])
            if champs_chiffres and len(trouvees) < MAX_RESULTATS:
                deja = {f.pk for f in trouvees}
                bas = terme.lower()
                noms = {f.name for f in modele._meta.concrete_fields}
                tri = next((c for c in ('created_at', 'date_creation', 'date_joined') if c in noms), None)
                lot = qs.only(modele._meta.pk.name, *champs_chiffres, *TYPES_FICHES[nom_type][1])
                lot = lot.order_by(f'-{tri}') if tri else lot
                for fiche in lot[:MAX_DECHIFFREMENTS]:
                    if fiche.pk in deja:
                        continue
                    if any(bas in str(getattr(fiche, c) or '').lower() for c in champs_chiffres):
                        trouvees.append(fiche)
                        if len(trouvees) >= MAX_RESULTATS:
                            break
        for fiche in trouvees:
            resultats.append({
                'type': nom_type, 'type_libelle': type_libelle,
                'id': str(fiche.pk), 'libelle': _libelle(fiche, nom_type),
            })
        if len(resultats) >= MAX_RESULTATS:
            break
    return resultats[:MAX_RESULTATS]
