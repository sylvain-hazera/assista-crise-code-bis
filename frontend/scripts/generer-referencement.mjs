// Fabrique les variables nginx du referencement a partir de src/app/seo/referencement.json
// et des routes du site (src/app/public/public.routes.ts, src/app/app.routes.ts).
//
// Lance a la construction de l'image (Dockerfile.prod) : la sortie est copiee dans
// /etc/nginx/conf.d/00-referencement.conf, et frontend/nginx.conf n'emploie que ses variables.
//
// Pourquoi generer plutot qu'ecrire a la main : la liste des adresses que le site connait sert
// a repondre un vrai 404 aux autres. Recopiee a la main, elle aurait fini en retard sur les
// routes, et une page reelle aurait repondu 404. Ici elle est RELUE dans les routes a chaque
// construction ; un texte interdit ou une page referencee sans route font echouer la
// construction au lieu de partir en production.
//
// Usage : node scripts/generer-referencement.mjs > 00-referencement.conf
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const racine = join(dirname(fileURLToPath(import.meta.url)), '..');
const lire = (chemin) => readFileSync(join(racine, chemin), 'utf8');

const fiche = JSON.parse(lire('src/app/seo/referencement.json'));

function echec(message) {
  console.error(`generer-referencement : ${message}`);
  process.exit(1);
}

// Ces textes finissent dans des attributs HTML et dans des chaines nginx entre guillemets.
function texteSur(texte, ou) {
  if (typeof texte !== 'string') echec(`${ou} : texte attendu`);
  if (/["<>&$\\\n\r]/.test(texte)) echec(`${ou} : caractere interdit dans « ${texte} »`);
  return texte;
}
const cheminSur = (chemin, ou) => {
  if (!/^\/[a-z0-9/_.-]*$/.test(chemin)) echec(`${ou} : chemin inattendu « ${chemin} »`);
  return chemin;
};
const hoteSur = (hote) => {
  if (!/^[a-z0-9.-]+$/.test(hote)) echec(`nom d'hote inattendu « ${hote} »`);
  return hote;
};
const regex = (texte) => texte.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
// Dans une chaine nginx entre guillemets doubles, seuls « " » et « \ » s'echappent.
const q = (texte) => `"${texte.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;

// --- Premiers segments des adresses que le site connait ---------------------------------
const segments = new Set();
for (const fichier of ['src/app/public/public.routes.ts', 'src/app/app.routes.ts']) {
  for (const [, chemin] of lire(fichier).matchAll(/\bpath:\s*'([^']*)'/g)) {
    const premier = chemin.split('/')[0];
    if (premier && premier !== '**' && !premier.startsWith(':')) segments.add(premier);
  }
}
if (!segments.has('accueil') || !segments.has('admin') || segments.size < 20) {
  echec(`routes illisibles : ${segments.size} segments trouves`);
}
for (const segment of segments) {
  if (!/^[a-z0-9-]+$/.test(segment)) echec(`segment de route inattendu « ${segment} »`);
}

// --- Marques ------------------------------------------------------------------------------
const hotes = Object.keys(fiche.marques).map(hoteSur);
const defaut = fiche.marque_par_defaut;
if (!fiche.marques[defaut]) echec(`marque par defaut « ${defaut} » absente de 'marques'`);
for (const hote of hotes) {
  for (const champ of ['nom', 'slogan', 'description']) {
    texteSur(fiche.marques[hote][champ], `marques.${hote}.${champ}`);
  }
}

// --- Pages --------------------------------------------------------------------------------
const pages = fiche.pages;
if (!pages.some((p) => p.chemin === '/')) echec("la page d'accueil « / » manque dans 'pages'");
for (const page of pages) {
  cheminSur(page.chemin, 'pages');
  texteSur(page.titre, `pages ${page.chemin} titre`);
  texteSur(page.description, `pages ${page.chemin} description`);
  if (page.chemin !== '/') {
    if (!page.titre || !page.description) echec(`pages ${page.chemin} : titre et description requis`);
    if (!segments.has(page.chemin.slice(1).split('/')[0])) {
      echec(`pages ${page.chemin} : aucune route du site ne porte cette adresse`);
    }
  }
}

const sortie = [];
const carte = (source, variable, lignes) => {
  sortie.push(`map ${source} ${variable} {`, ...lignes.map((l) => `    ${l}`), '}', '');
};
const parMarque = (champ) => [
  `default ${q(fiche.marques[defaut][champ])};`,
  ...hotes.map((hote) => `${hote} ${q(fiche.marques[hote][champ])};`),
];

sortie.push('# FICHIER GENERE par frontend/scripts/generer-referencement.mjs -- ne pas modifier.');
sortie.push('# Source : frontend/src/app/seo/referencement.json et les routes du site.', '');

carte('$host', '$seo_nom', parMarque('nom'));
carte('$host', '$seo_slogan', parMarque('slogan'));
carte('$host', '$seo_description_marque', parMarque('description'));

// Seuls les hotes d'une marque sont proposes aux moteurs : une adresse de secours, l'adresse
// IP du reseau local ou un satellite servent le meme site et feraient doublon.
carte('$host', '$seo_hote_reference', ['default 0;', ...hotes.map((hote) => `${hote} 1;`)]);

// $request_uri et non $uri : apres le renvoi interne vers /index.html, $uri ne dit plus
// quelle page a ete demandee. La chaine de requete est ecartee (adresse canonique).
carte('$request_uri', '$seo_chemin', [
  'default "";',
  '"~^/(accueil/?)?(\\?.*)?$" "/";',
  ...pages.filter((p) => p.chemin !== '/').map(
    (p) => `"~^${regex(p.chemin)}/?(\\?.*)?$" ${q(p.chemin)};`),
]);

carte('$seo_chemin', '$seo_titre', [
  'default "$seo_nom";',
  '"/" "$seo_nom — $seo_slogan";',
  ...pages.filter((p) => p.chemin !== '/').map((p) => `${q(p.chemin)} ${q(`${p.titre} — `).slice(0, -1)}$seo_nom";`),
]);

carte('$seo_chemin', '$seo_description', [
  'default "$seo_description_marque";',
  ...pages.filter((p) => p.chemin !== '/').map((p) => `${q(p.chemin)} ${q(p.description)};`),
]);

// « 1:/guide » = hote reference et page referencee : indexable. Tout le reste ne l'est pas.
carte('"$seo_hote_reference:$seo_chemin"', '$seo_robots', [
  'default "noindex, nofollow";',
  '"~^1:/" "";',
]);
carte('"$seo_hote_reference:$seo_chemin"', '$seo_canonique', [
  'default "";',
  '"~^1:/" "<link rel=\\"canonical\\" href=\\"https://$host$seo_chemin\\">";',
]);

// Adresse inconnue du site : ni la racine, ni un premier segment porte par une route.
carte('$request_uri', '$seo_inconnue', [
  'default 1;',
  '"~^/(\\?.*)?$" 0;',
  `"~^/(${[...segments].sort().map(regex).join('|')})(/|\\?|$)" 0;`,
]);

// Pages de l'ancien site, encore proposees par les moteurs.
carte('$request_uri', '$seo_ancienne_adresse', [
  'default "";',
  ...Object.entries(fiche.anciennes_adresses).map(
    ([ancienne, nouvelle]) => `"~^${regex(cheminSur(ancienne, 'anciennes_adresses'))}(\\?.*)?$" ${q(cheminSur(nouvelle, 'anciennes_adresses'))};`),
]);

const adresses = pages.map((p) => `<url><loc>https://$host${p.chemin}</loc></url>`).join('');
carte('$host', '$seo_plan_du_site', [
  `default ${q(`<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">${adresses}</urlset>`)};`,
]);

process.stdout.write(sortie.join('\n'));
