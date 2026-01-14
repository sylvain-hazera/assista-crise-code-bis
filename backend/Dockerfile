
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

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]