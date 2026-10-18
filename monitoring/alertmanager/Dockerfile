# Alertmanager + configuration de production (choisie par --config.file dans docker-compose.prod.yml).
# En dev, alertmanager.yml est monté sur le chemin par défaut. Aucun secret : lus dans /run/secrets.
FROM prom/alertmanager:v0.34.0
COPY alertmanager.prod.yml /etc/alertmanager/
RUN amtool check-config /etc/alertmanager/alertmanager.prod.yml
