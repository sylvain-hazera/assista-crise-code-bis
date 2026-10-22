# Image certbot du projet -- jusqu'au 22/10/2026 elle était construite à la main, sans
# Dockerfile nulle part (reconstituée ici depuis `docker history assista-certbot-ionos`).
#
# Deux greffons DNS, parce que deux zones chez deux hébergeurs différents :
#   - IONOS : zone assista-crise.fr (certificat principal, DNS-01) ;
#   - OVH   : zone reserve-resilience.org (marque blanche). Le partenaire est chez OVH, et
#     HTTP-01 est inutilisable ici -- le port 443 est restreint aux IP françaises et Let's
#     Encrypt valide depuis plusieurs points du globe, dont les adresses ne sont ni publiées
#     ni stables (voir README, « Le port 80 doit être joignable »).
#
# Construction :
#   docker build -t assista-certbot-ionos:latest proxy/certbot/
# Le nom d'image reste `assista-certbot-ionos` : il est câblé dans ~/scripts/renew-certs.sh et
# dans la procédure du README. Le renommer demanderait de toucher ces deux-là en même temps.
#
# `certbot/certbot:latest` n'est pas épinglé, comme l'image d'origine -- le comportement peut
# donc changer d'un build à l'autre. À épingler le jour où ça pose problème.
FROM certbot/certbot:latest

RUN pip install --no-cache-dir \
      certbot-dns-ionos \
      certbot-dns-ovh
