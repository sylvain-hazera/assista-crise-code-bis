from rest_framework.pagination import PageNumberPagination


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
