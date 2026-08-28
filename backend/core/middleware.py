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
