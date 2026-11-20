/*
 * Service worker du site installable (DOSSIER-PWA-INTERVENANTS.md, 20/11/2026).
 *
 * Il ne fait que ceci :
 * - la page (index.html) : réseau d'abord, la dernière copie si le réseau manque — l'application
 *   s'ouvre hors ligne, et une version en ligne est toujours la plus récente ;
 * - les fichiers JS/CSS/polices au nom haché : mis en cache à la première lecture (leur nom
 *   change à chaque version) ;
 * - RIEN d'autre : ni /api/ (les données hors ligne vivent chiffrées dans IndexedDB, jamais en
 *   clair dans un cache), ni /media/, ni /mobile/, ni /admin-django/.
 *
 * Changer ce fichier (VERSION) remplace l'ancien service worker et vide ses caches.
 */
const VERSION = 'coquille-2026-11-20';
const PAGE = '/index.html';

self.addEventListener('install', (evenement) => {
  evenement.waitUntil(
    caches.open(VERSION).then((cache) => cache.add(new Request(PAGE, { cache: 'reload' }))).catch(() => {}),
  );
  self.skipWaiting();
});

self.addEventListener('activate', (evenement) => {
  evenement.waitUntil(
    caches.keys()
      .then((noms) => Promise.all(noms.filter((nom) => nom !== VERSION).map((nom) => caches.delete(nom))))
      .then(() => self.clients.claim()),
  );
});

function jamaisEnCache(url) {
  return ['/api/', '/media/', '/mobile/', '/admin-django/', '/grafana/', '/static/', '/sw.js']
    .some((prefixe) => url.pathname.startsWith(prefixe));
}

const HACHE = /-[A-Z0-9]{8,}\.(js|css)$|\.(woff2?|ttf)$/i;

self.addEventListener('fetch', (evenement) => {
  const requete = evenement.request;
  if (requete.method !== 'GET') return;
  const url = new URL(requete.url);
  if (url.origin !== self.location.origin || jamaisEnCache(url)) return;

  if (requete.mode === 'navigate') {
    evenement.respondWith(
      fetch(requete)
        .then((reponse) => {
          if (reponse.ok) {
            const copie = reponse.clone();
            caches.open(VERSION).then((cache) => cache.put(PAGE, copie));
          }
          return reponse;
        })
        .catch(() => caches.match(PAGE).then((copie) => copie || Response.error())),
    );
    return;
  }

  if (HACHE.test(url.pathname)) {
    evenement.respondWith(
      caches.match(requete).then((copie) => copie || fetch(requete).then((reponse) => {
        if (reponse.ok) {
          const aGarder = reponse.clone();
          caches.open(VERSION).then((cache) => cache.put(requete, aGarder));
        }
        return reponse;
      })),
    );
  }
});
