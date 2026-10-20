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
    et futur. Une seule ligne par requête (jamais une par objet renvoyé dans une liste). Ne
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

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.method in self.ACTION_BY_METHOD
            and request.path.startswith('/api/')
            and not request.path.startswith(self.EXCLUDED_PREFIXES)
            and not getattr(request, '_audit_log_written', False)
            and not self._lecture_compte_service(request)
        ):
            self._log(request, response)
        return response

    def _lecture_compte_service(self, request):
        if self.ACTION_BY_METHOD[request.method] != "LECTURE":
            return False
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            return False
        return (user.username or '').lower().endswith(self.SERVICE_ACCOUNT_SUFFIXES)

    def _log(self, request, response):
        try:
            from .audit import audit_log

            resolver_match = getattr(request, 'resolver_match', None)
            if resolver_match is None:
                return

            view_cls = getattr(resolver_match.func, 'cls', None)
            queryset = getattr(view_cls, 'queryset', None)
            if queryset is not None:
                objet_type = queryset.model.__name__
            else:
                objet_type = resolver_match.url_name or request.path

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
            action_name = resolver_match.url_name or ''
            verbe = {"LECTURE": "Consultation", "CREATION": "Création", "MODIFICATION": "Modification",
                     "SUPPRESSION": "Suppression"}[self.ACTION_BY_METHOD[request.method]]
            commentaire = f"{verbe} ({action_name})" if action_name else verbe

            audit_log(
                request=request,
                action_code=self.ACTION_BY_METHOD[request.method],
                objet_type=objet_type,
                objet_id=objet_id,
                commentaire=commentaire,
                succes=response.status_code < 400,
            )
        except Exception:
            logger.exception("Échec de la journalisation automatique (%s %s)", request.method, request.path)


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
