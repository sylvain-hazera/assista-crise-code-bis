from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.utils.urls import remove_query_param, replace_query_param


class InstitutionPagination(PageNumberPagination):
    """Pagination toujours active (contrairement à OptionalPageNumberPagination) pour
    InstitutionViewSet : la liste des institutions n'a pas de raison de rester non paginée —
    même un rôle ADMIN qui voit tout (voir InstitutionViewSet.get_queryset) reçoit une
    enveloppe {count, next, previous, results} plutôt qu'un tableau brut potentiellement
    énorme."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 500


class OptionalPageNumberPagination(PageNumberPagination):
    """Pagination opt-in : ne s'active que si l'appelant passe `?page=`, sinon renvoie la liste
    complète comme avant (`paginate_queryset` -> None fait sauter l'enveloppe côté DRF). Évite
    de casser tous les appelants existants d'un endpoint (qui attendent un tableau brut) le jour
    où on active la pagination sur une action déjà utilisée ailleurs — seuls les nouveaux appels
    qui passent explicitement `page` reçoivent l'enveloppe {count, next, previous, results}."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500

    def paginate_queryset(self, queryset, request, view=None):
        if request.query_params.get(self.page_query_param) is None:
            return None
        return super().paginate_queryset(queryset, request, view=view)


class MainCourantePagination(OptionalPageNumberPagination):
    """Pagination d'un registre très volumineux (AuditLog : 2,5 M de lignes, voir la page
    /admin/main-courante) où le COMPTAGE devenait le dernier poste de lenteur une fois les index
    posés : un `SELECT count(*)` exact relit toute la table (500 Mo, 150 à 350 ms) à chaque
    affichage de page, et ce coût grandit indéfiniment avec le registre.

    À la place :
    - comptage exact tant qu'il reste bon marché (jusqu'à SEUIL_COMPTAGE_EXACT lignes, ~3 ms) :
      c'est le cas de toute vue filtrée, celles où le total affiché a vraiment un sens ;
    - au-delà, le comptage s'arrête au plafond et `count_plafonne: true` dit à l'interface
      d'afficher « plus de 10 000 entrées ». Volontairement PAS une estimation du planificateur
      (EXPLAIN) : essayée le 21/10/2026, elle annonçait 84 entrées là où il y en avait 67 000
      (statistiques en retard sur les lignes du jour, les plus consultées) — un chiffre faux
      affiché comme un total est pire que pas de total ;
    - la navigation, elle, ne dépend JAMAIS de ce total : on lit une ligne de plus que la page
      demandée, et sa présence suffit à savoir s'il existe une page suivante. Un total plafonné
      ne peut donc pas empêcher d'aller au-delà de la 200e page.

    Ne remplace pas OptionalPageNumberPagination ailleurs : sur une table de taille ordinaire le
    comptage exact ne coûte rien et reste préférable.
    """

    SEUIL_COMPTAGE_EXACT = 10_000

    def paginate_queryset(self, queryset, request, view=None):
        if request.query_params.get(self.page_query_param) is None:
            return None

        self.request = request
        self.taille_page = self.get_page_size(request) or self.page_size
        self.numero_page = self._numero_page_demande(request)

        debut = (self.numero_page - 1) * self.taille_page
        lignes = list(queryset[debut:debut + self.taille_page + 1])
        self.a_une_suite = len(lignes) > self.taille_page
        self.total, self.total_plafonne = self._compter(queryset)
        return lignes[:self.taille_page]

    def get_paginated_response(self, data):
        return Response({
            'count': self.total,
            'count_plafonne': self.total_plafonne,
            'next': self._lien_page(self.numero_page + 1) if self.a_une_suite else None,
            'previous': self._lien_page(self.numero_page - 1) if self.numero_page > 1 else None,
            'results': data,
        })

    def get_paginated_response_schema(self, schema):
        # Schéma OpenAPI (drf-spectacular) : déclarer le champ supplémentaire plutôt que de
        # laisser le schéma décrire une enveloppe qui n'est pas celle réellement renvoyée.
        enveloppe = super().get_paginated_response_schema(schema)
        enveloppe['properties']['count_plafonne'] = {
            'type': 'boolean',
            'description': "true : il y a plus de `count` entrées (comptage arrêté au plafond).",
        }
        return enveloppe

    def to_html(self):
        # Rendu HTML de l'API navigable (BrowsableAPIRenderer, actif par défaut) : l'implémentation
        # de DRF s'appuie sur self.page, que cette classe n'utilise pas. Pas de contrôles plutôt
        # qu'une erreur 500 sur une page de debug.
        return ''

    def _numero_page_demande(self, request):
        valeur = request.query_params.get(self.page_query_param)
        try:
            numero = int(valeur)
        except (TypeError, ValueError):
            return 1
        return max(1, numero)

    def _compter(self, queryset):
        """(total, plafonné) : `plafonné` signifie « il y a PLUS que ce total », pas « environ ».
        Le LIMIT interne fait que Postgres s'arrête au plafond au lieu de parcourir le registre
        entier (2,7 ms contre 150 à 350 ms et 500 Mo lus, mesuré le 21/10/2026)."""
        plafond = self.SEUIL_COMPTAGE_EXACT
        exact = queryset[:plafond + 1].count()
        if exact <= plafond:
            return exact, False
        return plafond, True

    def _lien_page(self, numero):
        url = self.request.build_absolute_uri()
        if numero <= 1:
            return remove_query_param(url, self.page_query_param)
        return replace_query_param(url, self.page_query_param, numero)
