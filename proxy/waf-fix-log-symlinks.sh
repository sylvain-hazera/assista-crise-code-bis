#!/bin/sh
# L'image owasp/modsecurity-crs:nginx pré-crée access.log/error.log en tant que symlinks
# vers /dev/stdout/stderr, y compris sous le chemin custom qu'on donne via ACCESSLOG/
# ERRORLOG — pratique pour `docker logs`, mais ça empêche fail2ban de les lire comme de
# vrais fichiers depuis l'extérieur du conteneur. Monté en dernier (nom "99-") dans
# /docker-entrypoint.d/, ce script s'exécute juste avant le démarrage de nginx et
# remplace les symlinks par de vrais fichiers.
set -e
rm -f /var/log/nginx-real/access.log /var/log/nginx-real/error.log
touch /var/log/nginx-real/access.log /var/log/nginx-real/error.log
chmod 644 /var/log/nginx-real/access.log /var/log/nginx-real/error.log
