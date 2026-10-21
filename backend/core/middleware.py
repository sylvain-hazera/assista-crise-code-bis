import logging
import uuid

logger = logging.getLogger(__name__)


class GeoResolutionBudgetMiddleware:
    """Pose une seule fois par requête le budget de résolutions géo externes (voir
    core.geo_lookup.reset_resolution_budget) — évite qu'une liste touchant des milliers de
    communes/points jamais vus enchaîne autant d'appels HTTP synchrones et fasse dépasser le
    timeout du worker (voir le commentaire détaillé dans geo_lookup.py, incident du 14/09)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from .geo_lookup import reset_resolution_budget
        reset_resolution_budget()
        return self.get_response(request)


class AuditTraceMiddleware:
    """Filet de sécurité de la main courante (AuditLog) : garantit qu'AUCUNE requête /api/ ne
    reste sans trace, quelle que soit la méthode HTTP — pas seulement les endpoints où un
    appel audit_log() explicite a été pensé. Une vraie main courante ne doit rien laisser passer
    (consultation d'une fiche, ajout d'une mission à une équipe, upload d'une photo...), pas
    seulement les quelques actions qu'on a pris soin d'instrumenter une par une.

    Générique plutôt qu'ajouté vue par vue : instrumente automatiquement tout endpoint présent
    et futur. Une seule ligne par requête (jamais une par objet renvoyé dans une liste), qui
    porte néanmoins les identifiants de TOUTES les fiches renvoyées (objets_ids, voir
    core/tracabilite.py) : c'est ce qui permet de retrouver qui a vu une fiche donnée. Ne
    double jamais un appel audit_log() déjà fait pendant la même requête par la vue elle-même
    (plus riche, avec un vrai commentaire métier) — audit_log() pose request._audit_log_written
    à True quand il réussit, ce middleware ne fait que combler les trous. N'échoue jamais la
    requête qu'il journalise (audit_log() est lui-même défensif ; la dérivation objet_type/
    objet_id ci-dessous est protégée en plus, car une exception ici casserait TOUTE réponse
    API)."""

    EXCLUDED_PREFIXES = ('/api/token/',)
    # Comptes de service (ponts radio, satellites) : machines qui interrogent l'API en boucle --
    # leurs LECTURES représentaient 90 % de la main courante (~90 000 lignes/jour, 88 % de la
    # base mesuré le 20/10/2026) sans rien apprendre à personne. Leurs écritures restent tracées.
    # ponts : pont-…@assista-crise.local ; satellites : satellite-…@service.assista-crise.local
    SERVICE_ACCOUNT_SUFFIXES = ('@assista-crise.local', '.assista-crise.local')
    ACTION_BY_METHOD = {
        "GET": "LECTURE",
        "HEAD": "LECTURE",
        "POST": "CREATION",
        "PUT": "MODIFICATION",
        "PATCH": "MODIFICATION",
        "DELETE": "SUPPRESSION",
    }

    # Au-delà, une liste n'est plus notée fiche par fiche (une ligne de journal reste lisible) :
    # aucune liste de l'application n'en approche à ce jour (Signalements : 7 000 au plus).
    MAX_OBJETS_PAR_LIGNE = 20_000

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.method in self.ACTION_BY_METHOD
            and request.path.startswith('/api/')
            and not request.path.startswith(self.EXCLUDED_PREFIXES)
        ):
            if getattr(request, '_audit_log_written', False):
                self._enrichir_ligne_explicite(request, response)
            elif not self._lecture_compte_service(request):
                self._log(request, response)
        return response

    def _lecture_compte_service(self, request):
        if self.ACTION_BY_METHOD[request.method] != "LECTURE":
            return False
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return False
        return (user.username or '').lower().endswith(self.SERVICE_ACCOUNT_SUFFIXES)

    def _trace(self, request, response):
        """Ce que la requête a exposé, d'après la réponse elle-même (voir core/tracabilite.py) :
        type et identifiant(s) des fiches, nature de l'exposition, périmètre de crise et
        paramètres de recherche. Un dict prêt pour audit_log() ; None hors vue résolue."""
        from .tracabilite import (
            MODELES_NON_TRACES, Exposition, coordonnees_retirees, motif_export, objets_exposes,
            parametres_recherche, perimetre_de,
        )

        resolver_match = getattr(request, 'resolver_match', None)
        if resolver_match is None:
            return None

        view_cls = getattr(resolver_match.func, 'cls', None)
        queryset = getattr(view_cls, 'queryset', None)
        modele = queryset.model if queryset is not None else None
        objet_type = modele.__name__ if modele is not None else (resolver_match.url_name or request.path)

        # resolver_match.kwargs['pk'] n'est PAS garanti être un UUID valide : une URL mal
        # formée (typo, ancien lien, méthode non supportée) peut matcher la route
        # générique "détail" d'un ViewSet avec n'importe quel segment en guise de pk (ex:
        # POST /api/users/creer_mon_institution/ -- faute de frappe pour l'action réelle,
        # hyphénée -- capture "creer_mon_institution" comme pk) -- AuditLog.objet_id est un
        # UUIDField, le passer tel quel fait planter audit_log() (`to_python` lève
        # ValidationError avant même d'atteindre la base). Repéré le 08/10 : ce plantage
        # était jusqu'ici avalé silencieusement par le except plus bas ET par la config de
        # logging par défaut de Django (voir LOGGING, config/settings.py) -- depuis l'ajout
        # de l'alerte mail_admins/Matrix sur toute erreur, il déclenchait une fausse alerte
        # à chaque URL mal formée de ce type.
        pk_brut = resolver_match.kwargs.get('pk')
        try:
            objet_id = uuid.UUID(str(pk_brut)) if pk_brut is not None else None
        except (ValueError, AttributeError, TypeError):
            objet_id = None

        trace = {
            'objet_type': objet_type, 'objet_id': objet_id, 'objets_ids': None,
            'exposition': None, 'perimetre': None, 'crise': None, 'recherche': None,
        }
        # Le reste lit une réponse dont la forme varie d'un endpoint à l'autre : protégé à part,
        # une forme inattendue ne doit coûter que ces compléments, jamais la ligne elle-même.
        try:
            # Réponse DRF réussie seulement : une erreur n'a rien exposé.
            data = getattr(response, 'data', None) if response.status_code < 400 else None
            lecture = self.ACTION_BY_METHOD[request.method] == "LECTURE"

            objets_ids = []
            if data is not None and objet_type not in MODELES_NON_TRACES:
                objets_ids, nature = objets_exposes(data)
                if lecture and nature:
                    trace['exposition'] = nature
                    vue = (getattr(response, 'renderer_context', None) or {}).get('view')
                    if nature == Exposition.LISTE and motif_export(request):
                        trace['exposition'] = Exposition.EXPORT
                    elif nature == Exposition.LISTE and coordonnees_retirees(request, vue, objet_type):
                        trace['exposition'] = Exposition.LISTE_SANS_COORDONNEES
                objets_ids = objets_ids[:self.MAX_OBJETS_PAR_LIGNE]
                trace['objets_ids'] = objets_ids or None
            if objet_id is None and len(objets_ids) == 1:
                # fiche ouverte sans pk dans l'URL, ou création : l'objet est connu par la réponse
                trace['objet_id'] = uuid.UUID(objets_ids[0])

            trace['perimetre'], trace['crise'] = perimetre_de(modele, data, request)
            trace['recherche'] = parametres_recherche(request)
        except Exception:
            logger.exception("Traçabilité incomplète (%s %s)", request.method, request.path)
        return trace

    def _log(self, request, response):
        try:
            from .audit import audit_log

            trace = self._trace(request, response)
            if trace is None:
                return

            from .tracabilite import Exposition

            resolver_match = request.resolver_match
            action_name = resolver_match.url_name or ''
            action_code = self.ACTION_BY_METHOD[request.method]
            # Une liste relue pour produire un fichier (?motif=export) est un export, pas une
            # simple consultation : même action que les exports serveur.
            if trace['exposition'] == Exposition.EXPORT:
                action_code = "EXPORT"
            verbe = {"LECTURE": "Consultation", "CREATION": "Création", "MODIFICATION": "Modification",
                     "SUPPRESSION": "Suppression", "EXPORT": "Export"}[action_code]
            commentaire = f"{verbe} ({action_name})" if action_name else verbe

            audit_log(
                request=request,
                action_code=action_code,
                commentaire=commentaire,
                succes=response.status_code < 400,
                **trace,
            )
        except Exception:
            logger.exception("Échec de la journalisation automatique (%s %s)", request.method, request.path)

    def _enrichir_ligne_explicite(self, request, response):
        """La vue a écrit sa propre ligne (commentaire métier plus riche) : on la complète avec
        ce que seule la réponse révèle -- fiches exposées, périmètre, recherche -- sans jamais
        écraser ce que la vue a renseigné elle-même. Les fiches ne sont ajoutées que si elles
        sont du type annoncé par la ligne, pour ne pas attribuer à un objet ce qui en concerne
        un autre (une action sur un satellite qui renverrait des comptes, par exemple)."""
        try:
            from .models import AuditLog

            ligne = getattr(request, '_audit_log_ligne', None)
            if ligne is None:
                return
            trace = self._trace(request, response)
            if trace is None:
                return

            maj = {}
            if trace['objet_type'] == ligne.objet_type:
                if not ligne.objets_ids and trace['objets_ids']:
                    maj['objets_ids'] = trace['objets_ids']
                if ligne.exposition is None and trace['exposition']:
                    maj['exposition'] = trace['exposition']
            if ligne.perimetre is None and trace['perimetre']:
                maj['perimetre'] = trace['perimetre']
                if ligne.crise_id is None and trace['crise']:
                    maj['crise_id'] = trace['crise']
            if ligne.recherche is None and trace['recherche']:
                maj['recherche'] = trace['recherche']
            if maj:
                AuditLog.objects.filter(pk=ligne.pk).update(**maj)
        except Exception:
            logger.exception("Échec du complément de main courante (%s %s)", request.method, request.path)


class NoCacheApiMiddleware:
    """Empêche toute mise en cache (navigateur ou intermédiaire) des réponses `/api/` : une même
    URL (ex: `GET /api/users/`) renvoie un contenu différent selon l'en-tête `X-Environment`
    (masquage email/téléphone en zone DEMO, voir `UserSerializer.to_representation` et
    consorts) — sans ceci, une réponse PROD mise en cache pourrait être resservie telle quelle
    après bascule en DEMO (ou l'inverse), exposant de vraies coordonnées pendant une
    démonstration. `Vary` seul ne suffit pas : beaucoup de caches ignorent les en-têtes hors
    liste standard, `Cache-Control: no-store` est la garantie robuste."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/api/'):
            response['Cache-Control'] = 'no-store'
            existing_vary = response.get('Vary', '')
            vary_parts = [v.strip() for v in existing_vary.split(',') if v.strip()]
            if 'X-Environment' not in vary_parts:
                vary_parts.append('X-Environment')
            response['Vary'] = ', '.join(vary_parts)
        return response
