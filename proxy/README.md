# Entrée réseau publique : WAF + proxy

Documentation reconstituée le 2026-10-15 depuis l'état réel de l'infra (`docker inspect`,
`~/.bash_history`, `~/scripts/`) — jusque-là, cette partie de l'infra n'était documentée nulle
part (seulement référencée comme "doc de conception Matrix / Element" dans les commentaires de
`nginx.conf`, qui n'a jamais existé comme fichier). Référence-toi à ce fichier, pas à la mémoire
d'une session passée.

## Architecture

```
Internet (443/80)
  │
  ▼
ac_waf   (owasp/modsecurity-crs:nginx -- TLS + ModSecurity/OWASP CRS)
  │  proxy_pass http://ac_proxy, en clair, réseau docker interne `assista-front`
  ▼
ac_proxy (image buildée depuis CE dossier -- proxy/Dockerfile + proxy/nginx.conf)
  │  route selon le Host (server_name) vers les conteneurs applicatifs
  ▼
backend (Django/DRF, port 8000) / frontend (Angular, fichiers statiques, port 80)
```

`ac_waf` est le **seul** point d'entrée public (ports hôte 80→8080 et 443→8443 du conteneur) :
termine le TLS, applique l'OWASP CRS (ModSecurity), puis relaie en clair à `ac_proxy` sur le
réseau Docker interne. `ac_proxy` route ensuite par `Host` (plusieurs blocs `server{}`, voir
`nginx.conf`) vers `backend:8000`/`frontend:80`, ou vers Synapse/MAS/Element Web pour les
sous-domaines Matrix.

## `ac_waf`

- **Image** : `owasp/modsecurity-crs:nginx` (image publique, pas construite depuis ce dépôt).
- **Créé le** : 2026-09-06. **Aucun docker-compose ni script de lancement n'existait** jusqu'au
  2026-10-15 — reconstruit depuis l'état du conteneur vivant.
- **Depuis le 19/10/2026** : décrit par `docker-compose.114.yml` (service `waf`, toutes les
  options ci-dessous y figurent).
- **Redéploiement** : `~/scripts/redeploy-waf.sh` (hors dépôt, recrée le service par compose).
  Nécessaire après toute modification de `waf.env` ou de `modsecurity-override.conf` (les
  variables d'env d'un conteneur sont figées au démarrage, et l'override est un template
  instancié au démarrage — un `nginx -s reload` ne relit ni l'un ni l'autre).
- **Mode BLOCAGE** (`MODSEC_RULE_ENGINE=On` dans `waf.env`) depuis le 19/10/2026 ; avant :
  `DetectionOnly` (journalisation seule). Décidé après analyse des journaux de 6 semaines
  (`waf_modsec_logs`, `audit/audit.log`, JSON) : 85 requêtes auraient été bloquées, presque
  toutes des scanners ; les faux positifs restants (Accept-Charset de navigateurs mobiles,
  Grafana) sont exclus dans `modsecurity-override.conf`. **Faux positif en production** :
  chercher la règle (`ruleId`) dans `audit.log`, l'exclure dans l'override au plus près du
  chemin concerné, redéployer ; en urgence, repasser `MODSEC_RULE_ENGINE=DetectionOnly` puis
  `redeploy-waf.sh`.
- **Config** :
  - `SERVER_NAME` (dans `waf.env`) : liste des hostnames acceptés, séparés par un espace.
    Injectée directement dans `server_name ${SERVER_NAME};` du template nginx de l'image (voir
    `/etc/nginx/templates/conf.d/default.conf.template` dans l'image) — nginx gère nativement
    plusieurs hostnames séparés par un espace dans `server_name`.
  - `SSL_CERT_FILE`/`SSL_CERT_KEY_FILE` : `/etc/letsencrypt/live/assista-crise.fr/{fullchain,privkey}.pem`
    (un seul certificat, une seule paire de clés, qui couvre TOUS les hostnames via ses SAN —
    pas de certificat par sous-domaine).
  - `modsecurity-override.conf` (ce dossier) : règles CRS personnalisées, montées depuis le
    dépôt depuis le passage à compose (avant : copie hors dépôt `~/proxy/modsecurity-override.conf`,
    à synchroniser à la main -- désormais inutilisée).
  - `waf-fix-log-symlinks.sh` (ce dossier) : hook `docker-entrypoint.d`, monté tel quel.

⚠️ **Le conteneur doit démarrer avec `--user root`** (voir `redeploy-waf.sh`) — l'image
`owasp/modsecurity-crs:nginx` déclare `USER nginx` (uid 101) par défaut, qui ne peut pas
traverser `/etc/letsencrypt/live/` (verrouillé `root`-only par certbot pour protéger la clé
privée) : sans ce flag, nginx plante au démarrage et le conteneur boucle en restart, coupant
tout le site. Ce n'est pas un affaiblissement de sécurité : nginx redescend lui-même en
utilisateur `nginx` pour ses processus worker via sa propre config, `root` n'est nécessaire que
pour que le process master lise le certificat au démarrage — mécanisme standard de nginx.
Incident vécu le 2026-10-15 en redéployant pour `cj.assista-crise.fr` (l'ancien conteneur,
tournant depuis le 2026-09-06, avait dû être lancé avec ce même flag à l'origine, ou avec une
version antérieure de l'image qui ne déclarait pas `USER nginx` — image `:nginx` non épinglée à
un digest précis, donc son comportement peut changer d'un `docker pull` à l'autre).

⚠️ **`~/proxy/Dockerfile` et `~/proxy/nginx.conf` sont des fichiers périmés/non utilisés**
(datés du 2026-09-03, divergent du `nginx.conf` réellement déployé dans `ac_proxy`) — ne pas
confondre avec ce dossier (`assista-crise-code-bis/proxy/`, qui EST utilisé pour `ac_proxy`) ni
avec `~/proxy/modsecurity-override.conf` (le seul fichier de `~/proxy/` réellement monté dans
`ac_waf`). Non supprimés par prudence (contenu jamais confirmé comme totalement mort), mais à
ignorer.

## `ac_proxy`

Buildé depuis ce dossier (`docker build -t assista-crise-proxy:latest .`), routage par
`server_name` dans `nginx.conf`. Après modification de `nginx.conf` : préférer copier le
nouveau fichier dans le conteneur vivant + `nginx -t` + `nginx -s reload` (zéro coupure) plutôt
que recréer le conteneur — voir l'historique de la marque blanche Réserve Résilience pour le
patron exact (`docker cp` + test + reload, backup avant/suppression après).

## Certificat (Let's Encrypt, DNS-01 via IONOS)

- **Renouvellement automatique** : `~/scripts/renew-certs.sh` (cron quotidien à 4h30, voir
  `crontab -l`) — utilise `certbot renew`, qui relit tout seul les domaines déjà enregistrés
  dans `/etc/letsencrypt/renewal/assista-crise.fr.conf`. Ne fait rien tant que le certificat
  n'entre pas dans sa fenêtre de renouvellement (30 jours avant expiration) : un run quotidien
  silencieux est normal.
- **Image utilisée** : `assista-certbot-ionos:latest` (certbot + plugin `certbot-dns-ionos`,
  construite localement — pas une image publique).
- **Authentification DNS-01** : credentials IONOS dans `/etc/letsencrypt/ionos/credentials.ini`
  (hors dépôt, sur l'hôte) — ne couvrent QUE le compte IONOS gérant `assista-crise.fr`. Ce
  mécanisme ne peut PAS émettre de certificat pour un domaine appartenant à quelqu'un d'autre
  (ex: un sous-domaine marque blanche sur le domaine propre d'un partenaire) : il faudrait soit
  que le partenaire crée lui-même l'enregistrement TXT demandé, soit basculer sur une
  validation HTTP-01 une fois son CNAME réellement actif.

### ⚠️ Ajouter un nouveau domaine au certificat — piège rencontré le 2026-10-15

`certonly --cert-name assista-crise.fr --expand -d nouveau-domaine.fr` **ne garantit PAS** de
conserver les domaines déjà présents sur le certificat avec cette version de
certbot/certbot-dns-ionos — testé en direct : `--expand --force-renewal -d cj.assista-crise.fr`
seul a réémis un certificat ne couvrant QUE `cj.assista-crise.fr`, faisant disparaître
`assista-crise.fr`/`www`/`matrix`/`auth`/`chat` du SAN (donc cassé la prod le temps de
s'en apercevoir et corriger). **Toujours lister EXPLICITEMENT tous les domaines existants +
le(s) nouveau(x)**, jamais compter sur `--expand` seul :

```bash
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v /etc/letsencrypt/ionos/credentials.ini:/creds/credentials.ini:ro \
  assista-certbot-ionos:latest certonly --non-interactive \
  --authenticator dns-ionos \
  --dns-ionos-credentials /creds/credentials.ini \
  --dns-ionos-propagation-seconds 60 \
  --cert-name assista-crise.fr --force-renewal \
  -d assista-crise.fr -d www.assista-crise.fr -d matrix.assista-crise.fr \
  -d auth.assista-crise.fr -d chat.assista-crise.fr -d cj.assista-crise.fr
  # -d <tout nouveau domaine ici>
```

Avant de lancer cette commande pour de vrai, vérifie la liste ACTUELLE des domaines couverts
(pour ne pas en oublier un) :
```bash
echo | openssl s_client -connect 127.0.0.1:443 -servername assista-crise.fr 2>/dev/null \
  | openssl x509 -noout -text | grep -A2 "Subject Alternative Name"
```
Puis, après coup, `docker exec ac_waf nginx -s reload` (les fichiers de certificat changent sur
disque immédiatement, mais nginx ne les relit qu'au reload) et **re-vérifie avec la même
commande openssl** que tous les domaines attendus sont bien présents avant de considérer que
c'est fait.

## Procédure complète : ajouter un sous-domaine marque blanche

1. `nginx.conf` (ce dossier) : nouveau bloc `server { server_name <domaine> ; ... }` routant
   vers les mêmes `backend`/`frontend` (voir le bloc Réserve Résilience comme modèle) → déployer
   sur `ac_proxy` (copier + `nginx -t` + reload, voir plus haut).
2. `backend/config/settings.py` : ajouter le domaine à `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`
   (`https://...`) et `CORS_ALLOWED_ORIGINS` → rebuild/redéploie l'image `backend`.
3. Certificat : voir section ci-dessus — réémettre avec la liste complète + le nouveau domaine,
   `--force-renewal`, puis `docker exec ac_waf nginx -s reload` et vérifier le SAN.
4. `~/.config/assista-crise/secrets/waf.env` : ajouter le domaine à `SERVER_NAME` (séparé par un
   espace).
5. `~/scripts/redeploy-waf.sh` : recrée `ac_waf` pour qu'il prenne en compte le nouveau
   `SERVER_NAME` (un simple reload ne suffit pas pour une variable d'environnement).
6. Vérifier avec `curl -H "Host: <domaine>" https://<ip-ou-domaine>/` et un vrai navigateur.
