# Prometheus + configuration intégrée. Le 1er étage valide la config et exécute les tests de
# règles : le build échoue si une règle est invalide ou non testée.
FROM prom/prometheus:v3.15.0 AS test
COPY prometheus.yml alerts.yml alerts_test.yml /etc/prometheus/
WORKDIR /etc/prometheus
RUN promtool check config prometheus.yml \
 && promtool test rules alerts_test.yml

FROM prom/prometheus:v3.15.0
COPY --from=test /etc/prometheus/prometheus.yml /etc/prometheus/alerts.yml /etc/prometheus/
