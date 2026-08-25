
FROM python:3.10-slim

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

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]