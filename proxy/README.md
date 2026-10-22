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

### Cas particulier : domaine appartenant au partenaire (pas un sous-domaine d'assista-crise.fr)

`app.reserve-resilience.org` et consorts ne sont PAS dans la zone IONOS : la validation DNS-01
utilisée pour le certificat principal ne peut pas les couvrir (voir plus haut). Depuis que le
partenaire a posé ses CNAME vers nous, la validation **HTTP-01** fonctionne sans rien lui
demander de plus.

Choix retenu le 2026-10-22 : **un certificat séparé** `reserve-resilience.org`, jamais fusionné
avec celui d'assista-crise.fr. Le certificat principal et son renouvellement DNS-01 restent
intacts — une erreur sur le certificat partenaire ne peut donc pas faire tomber le domaine
principal, contrairement à l'incident du 15/10.

Deux fichiers additifs, montés dans `ac_waf` comme gabarits `conf.d` (ils ne remplacent rien) :

| Fichier | Rôle | Monté |
| --- | --- | --- |
| `waf-partenaires-acme.conf` | Sert le jeton ACME en clair sur :80 au lieu de rediriger | dès le départ |
| `waf-partenaires-tls.conf` | Bloc :443 avec le certificat partenaire, choisi par SNI | seulement après la 1re émission |

#### Émission, en trois temps

Dans cet ordre, sans sauter d'étape : le bloc TLS référence un certificat, et nginx refuse de
démarrer s'il n'existe pas — tout le site tomberait.

```bash
# 1. Le bloc ACME seul (le TLS reste commenté dans docker-compose.114.yml)
cd ~/assista-crise-code-bis && git pull
~/scripts/redeploy-waf.sh
docker exec ac_waf nginx -t

# 2. Émission du certificat partenaire, par HTTP-01
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v ac_certbot_webroot:/var/www/certbot \
  assista-certbot-ionos:latest certonly --non-interactive --agree-tos \
  --webroot --webroot-path /var/www/certbot \
  --cert-name reserve-resilience.org \
  -d app.reserve-resilience.org -d auth.reserve-resilience.org \
  -d chat.reserve-resilience.org -d matrix.reserve-resilience.org
sudo ls /etc/letsencrypt/live/reserve-resilience.org/   # doit lister fullchain.pem

# 3. Activer le bloc TLS : décommenter la ligne waf-partenaires-tls.conf dans
#    docker-compose.114.yml, puis
~/scripts/redeploy-waf.sh
docker exec ac_waf nginx -t
for d in app auth chat matrix; do
  curl -sS -o /dev/null -w "$d %{http_code}\n" --resolve "$d.reserve-resilience.org:443:127.0.0.1" \
    "https://$d.reserve-resilience.org/"
done
```

#### ⚠ Un domaine partenaire ne doit PAS rester dans `SERVER_NAME` du WAF

Piège rencontré le 22/10/2026. `app.reserve-resilience.org` figurait dans `SERVER_NAME`
(`waf.env`), donc dans le `server_name` du bloc PAR DÉFAUT de l'image. Deux blocs revendiquaient
le même nom sur le port 8080, et nginx garde **le premier défini** — `default.conf` passe avant
`partenaires-acme.conf` dans l'ordre alphabétique de `conf.d/*.conf` :

```
[warn] conflicting server name "app.reserve-resilience.org" on 0.0.0.0:8080, ignored
```

Résultat : le jeton ACME de `app.` tombait sur la redirection 301 du bloc par défaut, et sa
validation échouait, alors que les trois autres domaines passaient. Le nom a donc été retiré de
`SERVER_NAME` (sauvegarde : `waf.env.bak-2026-10-22`) ; les blocs `partenaires-*.conf` le
servent désormais seuls, sur :80 comme sur :443. Aucune régression : sur :443 un nom non reconnu
retombe de toute façon sur le premier bloc du port.

**Règle** : un domaine partenaire est déclaré dans `waf-partenaires-*.conf`, jamais dans
`SERVER_NAME`. Vérifier après chaque redéploiement :
`docker logs ac_waf 2>&1 | grep -c "conflicting server name"` doit renvoyer `0`.

#### ⚠ Le port 80 doit être joignable depuis Internet

HTTP-01 l'exige. Au 22/10/2026 il ne l'est pas : la machine écoute bien sur :80, aucun pare-feu
local ne bloque (`ufw` désactivé, `firewalld` inactif), mais Let's Encrypt n'atteint pas
176.141.139.81:80 — « Timeout during connect (likely firewall problem) » sur les quatre
domaines, alors que :443 fonctionne. La redirection 80→443 ne sert donc aujourd'hui que le
trafic local. Il manque une redirection de port 80 sur le routeur.

Tant que ce n'est pas fait, le certificat partenaire ne peut pas être émis par HTTP-01.
L'alternative est DNS-01 avec `certbot-dns-ovh` (la zone du partenaire est chez OVH), qui ne
demande aucun port ouvert mais exige des identifiants d'API OVH fournis par le partenaire.

#### Renouvellement automatique

Le domaine est chez **OVH** (registrar et DNS : `dns200.anycast.me`, SOA `tech.ovh.net`),
expiration du domaine le 2027-03-25 — donc hors de portée des identifiants IONOS, d'où HTTP-01.

`certbot renew` (cron de 4h30, `~/scripts/renew-certs.sh`) reprend TOUS les certificats, chacun
avec la méthode mémorisée à son émission dans `/etc/letsencrypt/renewal/<nom>.conf` : DNS-01
pour assista-crise.fr, webroot pour reserve-resilience.org. **Aucune action du partenaire n'est
nécessaire, jamais.**

Deux dépendances à ne pas casser, sous peine d'un échec 60 jours plus tard :

1. **Le bloc ACME** (`waf-partenaires-acme.conf`) doit rester monté : c'est lui qui sert le
   jeton de validation.
2. **`~/scripts/renew-certs.sh` doit monter le volume du webroot** — `-v
   ac_certbot_webroot:/var/www/certbot`, ajouté le 22/10/2026 (sauvegarde :
   `renew-certs.sh.bak-2026-10-22`). Sans lui, le conteneur certbot n'a pas le répertoire où
   écrire le jeton. Script hors dépôt, d'où cette note.

L'échec serait signalé par mail (`certbot renew` sort en code non nul, le script envoie
l'alerte), pas silencieux — mais il laisserait quand même le certificat expirer s'il n'est pas
traité.

#### Et si le partenaire change ses CNAME ?

HTTP-01 dépend de leurs CNAME pointant chez nous. S'ils les retirent, le renouvellement échoue
— mais leurs domaines ne pointeraient plus sur nous de toute façon, donc le certificat n'aurait
plus d'objet. Pas de fragilité réelle.

L'alternative serait DNS-01 avec le plugin `certbot-dns-ovh` : plus robuste si un jour leurs
domaines cessent de pointer chez nous tout en gardant le certificat, mais il faut que le
partenaire crée des identifiants d'API OVH et nous les confie. À ne faire que s'il y a une
raison précise.

Un nouveau partenaire s'ajoute en complétant `server_name` dans les DEUX fichiers, puis en
réémettant le certificat avec la liste complète des domaines partenaires (même piège `--expand`
que pour le certificat principal : toujours tout lister).
