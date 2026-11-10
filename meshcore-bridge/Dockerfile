FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Les modules sont listés un à un, pas un `COPY . .` : l'image ne doit pas embarquer les
# fichiers de test ni les caches. Conséquence à ne pas oublier -- un module AJOUTÉ ici doit
# être ajouté à cette ligne, sinon le pont plante au démarrage sur son import, et seulement
# une fois déployé.
COPY bridge.py proxy.py admin_meshcore.py .

CMD ["python", "-u", "bridge.py"]
