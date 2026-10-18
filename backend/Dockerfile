
FROM python:3.10-slim@sha256:6ff506466f8b1e981719b468cc0023b8ef000b983cdec0eafe119d01f379e31d

# Variables d'environnement pour éviter les fichiers .pyc et logs bufférisés
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# --- INSTALLATION DES DÉPENDANCES SYSTÈME (Pour GeoDjango/PostGIS) ---
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    binutils libproj-dev gdal-bin libgdal-dev \
    python3-gdal gcc python3-dev musl-dev \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# Installation des dépendances Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Le point de montage /app/media est de toute façon écrasé par le bind mount hôte au
# démarrage : son appartenance ne dépend pas de cette commande, elle doit être gérée
# côté hôte séparément.
RUN groupadd -g 10001 appuser \
    && useradd -u 10001 -g appuser -M -s /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["/entrypoint.sh"]

# GUNICORN_WORKERS : l'image est partagée entre .113 (dev, machine modeste) et .114 (prod, 12
# coeurs/15 Go) -- un nombre de workers figé dans l'image a fait grimper le temps système à
# 90-96% sur .113 le 24/09 (6 workers taillés pour .114 tournant en même temps qu'un ng build,
# constaté par vmstat). Forme shell (pas exec) pour que ${...} soit interprété au démarrage du
# conteneur, pas gelé au build -- valeur par défaut prudente, à relever explicitement via
# l'env du conteneur sur une machine qui peut l'encaisser (.114 : GUNICORN_WORKERS=6).
CMD ["sh", "-c", "exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --timeout 60"]