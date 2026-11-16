#!/usr/bin/env bash
# Verifie le referencement sur l'image de production du site, telle qu'elle sera servie :
# titre et description par marque et par page, adresse canonique, interdiction d'indexer les
# pages privees, robots.txt, plan du site, vrai 404, anciennes adresses, compression.
#
# Usage : scripts/tester-referencement.sh [image]     (defaut : assista-crise-frontend:verif)
# Appele par scripts/tester-frontend.sh apres la construction de production. Aucun port n'est
# publie : les requetes partent de l'interieur du conteneur, avec l'en-tete Host voulu.
set -uo pipefail

IMAGE="${1:-assista-crise-frontend:verif}"
NOM="ac_test_referencement_$$"
ECHECS=0

docker run -d --rm --name "$NOM" "$IMAGE" >/dev/null || { echo "image introuvable : $IMAGE" >&2; exit 2; }
trap 'docker stop "$NOM" >/dev/null 2>&1' EXIT
for _ in $(seq 1 30); do
  docker exec "$NOM" curl -s -o /dev/null http://127.0.0.1/ && break
  sleep 0.5
done

# appel <hote> <chemin> [option curl...] : en-tetes puis corps.
appel() {
  local hote="$1" chemin="$2"; shift 2
  docker exec "$NOM" curl -s -i -H "Host: $hote" "$@" "http://127.0.0.1$chemin" | tr -d '\r'
}
verifier() {   # verifier <libelle> <reponse> <attendu> : le texte doit s'y trouver
  if grep -qF -- "$3" <<<"$2"; then echo "  ok    $1"; else echo "  ECHEC $1 : « $3 » absent"; ECHECS=$((ECHECS+1)); fi
}
refuser() {    # refuser <libelle> <reponse> <interdit> : le texte ne doit pas s'y trouver
  if grep -qiF -- "$3" <<<"$2"; then echo "  ECHEC $1 : « $3 » present"; ECHECS=$((ECHECS+1)); else echo "  ok    $1"; fi
}

AC=www.assista-crise.fr
RR=app.reserve-resilience.org

echo "Accueil, par marque"
r=$(appel $AC /)
verifier "statut 200" "$r" "HTTP/1.1 200"
verifier "titre Assista-Crise" "$r" "<title>Assista-Crise — entraide et gestion de crise pour les communes</title>"
verifier "description" "$r" '<meta name="description" content="Assista-Crise, la plateforme d'
verifier "adresse canonique" "$r" '<link rel="canonical" href="https://www.assista-crise.fr/">'
verifier "image de partage" "$r" '<meta property="og:image" content="https://www.assista-crise.fr/api/branding/logo/">'
verifier "texte sans JavaScript" "$r" "<noscript><h1>Assista-Crise</h1>"
verifier "jamais mise en cache" "$r" "Cache-Control: no-cache"
refuser  "indexable" "$r" "X-Robots-Tag"
refuser  "ancien titre remplace" "$r" "<title>Assista Crise</title>"
[ "$(grep -c '<title>' <<<"$r")" = "1" ] && echo "  ok    un seul titre" || { echo "  ECHEC un seul titre"; ECHECS=$((ECHECS+1)); }

r=$(appel $RR /accueil)
verifier "titre Reserve Resilience" "$r" "<title>Réserve Résilience - Casques Jaunes — entraide en situation d'urgence</title>"
verifier "nom du site" "$r" '<meta property="og:site_name" content="Réserve Résilience - Casques Jaunes">'
verifier "/accueil a pour adresse canonique la racine" "$r" '<link rel="canonical" href="https://app.reserve-resilience.org/">'
refuser  "aucune trace de l'autre marque" "$r" "Assista-Crise"

echo "Page publique"
r=$(appel $RR "/guide?utm_source=essai")
verifier "titre de la page" "$r" "<title>Guide des risques majeurs — Réserve Résilience - Casques Jaunes</title>"
verifier "description de la page" "$r" 'content="Consultez les risques majeurs de votre commune'
verifier "adresse canonique sans parametres" "$r" '<link rel="canonical" href="https://app.reserve-resilience.org/guide">'
refuser  "indexable" "$r" "X-Robots-Tag"

echo "Pages a ne pas indexer"
for chemin in /dossier-suivi/abc123 /connexion-magique/uid/jeton /admin/missions /login /verifier-mobilisation/abc /mon-equipe/42; do
  r=$(appel $AC "$chemin")
  verifier "$chemin repond 200" "$r" "HTTP/1.1 200"
  verifier "$chemin interdit d'indexation" "$r" "X-Robots-Tag: noindex, nofollow"
  refuser  "$chemin sans adresse canonique" "$r" 'rel="canonical"'
done
r=$(appel 172.16.1.114 /)
verifier "hote hors marque : 200" "$r" "HTTP/1.1 200"
verifier "hote hors marque : interdit d'indexation" "$r" "X-Robots-Tag: noindex, nofollow"

echo "Adresses inconnues"
r=$(appel $AC /cette-page-n-existe-pas)
verifier "statut 404" "$r" "HTTP/1.1 404"
verifier "le site est quand meme servi" "$r" "<app-root></app-root>"
verifier "jamais mise en cache" "$r" "Cache-Control: no-cache"
r=$(appel $AC /wp-login.php);        verifier "/wp-login.php : 404" "$r" "HTTP/1.1 404"
r=$(appel $AC /chunk-ABSENT.js);     verifier "script absent : 404" "$r" "HTTP/1.1 404"
r=$(appel $AC "/?retour=1");         verifier "racine avec parametres : 200" "$r" "HTTP/1.1 200"

echo "Anciennes adresses"
r=$(appel $AC /rgpd.php);            verifier "/rgpd.php : 301" "$r" "HTTP/1.1 301"; verifier "/rgpd.php vers /rgpd" "$r" "Location: /rgpd"
r=$(appel $AC /list-cards.php);      verifier "/list-cards.php : 301 vers l'accueil" "$r" "Location: /"

echo "robots.txt et plan du site"
r=$(appel $RR /robots.txt)
verifier "robots.txt en texte" "$r" "Content-Type: text/plain"
verifier "robots.txt annonce le plan du site" "$r" "Sitemap: https://app.reserve-resilience.org/sitemap.xml"
refuser  "robots.txt n'interdit pas l'API" "$r" "Disallow: /api"
r=$(appel $RR /sitemap.xml)
verifier "plan du site en XML" "$r" "Content-Type: text/xml"
verifier "plan du site : accueil" "$r" "<loc>https://app.reserve-resilience.org/</loc>"
verifier "plan du site : guide" "$r" "<loc>https://app.reserve-resilience.org/guide</loc>"
refuser  "plan du site : aucune page privee" "$r" "admin"

echo "Compression"
script=$(docker exec "$NOM" sh -c 'cd /usr/share/nginx/html && ls -S *.js | head -1')
r=$(appel $AC "/$script" -o /dev/null -D - -H "Accept-Encoding: gzip")
verifier "script compresse ($script)" "$r" "Content-Encoding: gzip"
verifier "script en cache long" "$r" "max-age=31536000"

echo
if [ "$ECHECS" -gt 0 ]; then echo "$ECHECS echec(s)"; exit 1; fi
echo "referencement : tout est conforme"
