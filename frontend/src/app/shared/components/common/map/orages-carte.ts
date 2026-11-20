/** Les cellules orageuses dessinées sur la carte (20/11/2026) : fonctions pures qui fabriquent le
 * GeoJSON de chaque calque à partir de la réponse de /api/orages/, testées sans carte.
 *
 * Deux natures, jamais confondues à l'écran :
 * - SELON LES RELEVÉS : position, trajectoire passée (colorée par l'intensité), noyaux tobac,
 *   signatures Doppler, communes sous la pluie ;
 * - NOS ESTIMATIONS (qui ne sont pas des prévisions) : trajectoire prolongée avec ses repères de
 *   temps, contours « fantômes » à +15, +30, +45 et +60 min, cône d'incertitude, communes
 *   atteintes. Une simple translation : l'orage n'y naît ni n'y meurt. */
import { Feature, FeatureCollection, Geometry, Point, Polygon } from 'geojson';

import { CelluleOrage } from '../../../models/veille.model';

export type Position = [number, number];

/** Repères de temps des estimations, en minutes. */
export const REPERES_MIN = [15, 30, 45, 60] as const;
/** Demi-ouverture du cône : bornée, faute de quoi une trajectoire de deux points ferait un cône
 * nul ou une trajectoire hésitante un éventail sans signification. */
export const OUVERTURE_MIN_DEG = 10;
export const OUVERTURE_MAX_DEG = 45;
export const OUVERTURE_DEFAUT_DEG = 20;

/** Paliers d'intensité des cellules (mm/h) : 30, 50, 100 — mêmes teintes que leur contour. */
export const COULEUR_INTENSITE = ['step', ['get', 'intensite'], '#f59e0b', 50, '#dc2626', 100, '#7e22ce'];

const KM_PAR_DEGRE = 111.32;

function collection<G extends Geometry>(features: Feature<G>[]): FeatureCollection<G> {
  return { type: 'FeatureCollection', features };
}

/** Le point situé à `km` dans la direction `capDeg` (0 = nord), à plat : exact à mieux que 1 %
 * sur les distances d'une heure d'orage. */
export function deplacer([lon, lat]: Position, capDeg: number, km: number): Position {
  const cap = capDeg * Math.PI / 180;
  return [
    lon + km * Math.sin(cap) / (KM_PAR_DEGRE * Math.cos(lat * Math.PI / 180)),
    lat + km * Math.cos(cap) / KM_PAR_DEGRE,
  ];
}

/** Direction (degrés, 0 = nord) de `a` vers `b`. */
export function direction([lon1, lat1]: Position, [lon2, lat2]: Position): number {
  const dx = (lon2 - lon1) * Math.cos((lat1 + lat2) / 2 * Math.PI / 180);
  const dy = lat2 - lat1;
  return (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
}

/** Position actuelle : le dernier point de la trajectoire, à défaut la moyenne du contour. */
export function centreCellule(c: CelluleOrage): Position {
  const dernier = c.releves.trace?.[c.releves.trace.length - 1];
  if (dernier) return [dernier[2], dernier[1]];
  const anneau = c.contour.coordinates[0] ?? [];
  const n = Math.max(anneau.length - 1, 1);         // le dernier sommet répète le premier
  const sommets = anneau.slice(0, n);
  return [sommets.reduce((s, p) => s + p[0], 0) / sommets.length, sommets.reduce((s, p) => s + p[1], 0) / sommets.length];
}

/** Demi-ouverture du cône : la dispersion des directions prises pendant l'heure écoulée (écart
 * type circulaire), bornée. Une cellule qui file droit garde un cône étroit. */
export function ouvertureCone(c: CelluleOrage): number {
  const points = (c.releves.trace ?? []).map(p => [p[2], p[1]] as Position);
  const caps: number[] = [];
  for (let i = 1; i < points.length; i++) {
    if (points[i][0] !== points[i - 1][0] || points[i][1] !== points[i - 1][1]) caps.push(direction(points[i - 1], points[i]));
  }
  if (caps.length < 2) return OUVERTURE_DEFAUT_DEG;
  const s = caps.reduce((t, a) => t + Math.sin(a * Math.PI / 180), 0) / caps.length;
  const co = caps.reduce((t, a) => t + Math.cos(a * Math.PI / 180), 0) / caps.length;
  const r = Math.min(Math.hypot(s, co), 1);
  const ecart = Math.sqrt(-2 * Math.log(Math.max(r, 1e-6))) * 180 / Math.PI;
  return Math.min(OUVERTURE_MAX_DEG, Math.max(OUVERTURE_MIN_DEG, ecart));
}

function enMouvement(c: CelluleOrage): c is CelluleOrage & { estimations: { cap_deg: number; vitesse_kmh: number } } {
  return c.estimations.cap_deg != null && c.estimations.vitesse_kmh != null && c.estimations.vitesse_kmh > 0;
}

function heureCourte(iso: string): string {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

// ── Selon les relevés ────────────────────────────────────────────────────────

/** Un point par cellule, au centre : flèche orientée vers où elle va, étiquette courte. */
export function centres(cellules: CelluleOrage[]): FeatureCollection<Point> {
  return collection(cellules.map(c => ({
    type: 'Feature', geometry: { type: 'Point', coordinates: centreCellule(c) },
    properties: {
      identifiant: c.identifiant,
      intensite: c.releves.intensite_max_mmh,
      cap: c.estimations.cap_deg ?? 0,
      vitesse: c.estimations.vitesse_kmh ?? 0,
      mobile: enMouvement(c),
      renforcement: c.releves.suivi?.evolution === 'renforcement',
      etiquette: `${Math.round(c.releves.intensite_max_mmh)} mm/h`
        + (enMouvement(c) ? ` · ${c.estimations.vitesse_kmh} km/h` : ''),
    },
  })));
}

/** Trajectoire de l'heure écoulée : un segment par pas de cinq minutes, coloré par l'intensité
 * de son point d'arrivée, et un point par position (heure sur le premier et un sur trois). */
export function trajectoires(cellules: CelluleOrage[]): { segments: FeatureCollection; points: FeatureCollection<Point> } {
  const segments: Feature[] = [];
  const points: Feature<Point>[] = [];
  for (const c of cellules) {
    const trace = c.releves.trace ?? [];
    trace.forEach(([heure, lat, lon, intensite], i) => {
      const instant = new Date(heure).getTime();
      const valeur = intensite ?? c.releves.intensite_max_mmh;
      points.push({
        type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] },
        properties: {
          identifiant: c.identifiant, instant, intensite: valeur,
          etiquette: i < trace.length - 1 && (i === 0 || (trace.length - 1 - i) % 3 === 0) ? heureCourte(heure) : '',
        },
      });
      if (i > 0) {
        const [, latP, lonP] = trace[i - 1];
        segments.push({
          type: 'Feature', geometry: { type: 'LineString', coordinates: [[lonP, latP], [lon, lat]] },
          properties: { identifiant: c.identifiant, instant, intensite: valeur },
        });
      }
    });
  }
  return { segments: collection(segments), points: collection(points) };
}

/** Noyaux tobac (cœurs à 30, 50, 100 mm/h) et lieux de fusion ou de division. */
export function noyaux(cellules: CelluleOrage[]): FeatureCollection<Point> {
  return collection(cellules.flatMap(c => (c.releves.suivi?.noyaux_positions ?? []).map(n => ({
    type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [n.lon, n.lat] },
    properties: {
      identifiant: c.identifiant, intensite: n.max_mmh, seuil: n.seuil,
      etiquette: n.fusion ? 'fusion' : n.division ? 'division' : '',
    },
  }))));
}

/** Signatures Doppler et grêle. La rotation est placée où le radar l'a mesurée ; la grêle et la
 * divergence, dont le radar ne donne pas le point précis, au centre de la cellule, décalées pour
 * rester lisibles. */
export function signatures(cellules: CelluleOrage[]): FeatureCollection<Point> {
  const resultat: Feature<Point>[] = [];
  for (const c of cellules) {
    const d = c.releves.doppler;
    const p = c.prevision_meteo_france;
    const centre = centreCellule(c);
    const ajouter = (position: Position, type: string, etiquette: string) => resultat.push({
      type: 'Feature', geometry: { type: 'Point', coordinates: position },
      properties: { identifiant: c.identifiant, type, etiquette },
    });
    const rotation = d?.rotation;
    if (rotation) {
      const position: Position = rotation.lon != null && rotation.lat != null ? [rotation.lon, rotation.lat] : centre;
      ajouter(position, d?.polarimetrie?.debris ? 'debris' : 'rotation', d?.polarimetrie?.debris ? 'débris' : 'rotation');
    }
    if (d?.polarimetrie?.grele || d?.grele?.probable) {
      ajouter(deplacer(centre, 225, 4), 'grele', 'grêle');
    } else if (p.grele || p.grele_niveau) {
      ajouter(deplacer(centre, 225, 4), 'grele-prevue', 'grêle prévue');
    }
    if (d?.divergence) ajouter(deplacer(centre, 135, 4), 'divergence', 'rafale descendante');
  }
  return collection(resultat);
}

/** Communes sous la pluie (`touchee`) et atteintes dans l'heure (estimation, avec leur délai). */
export function communes(cellules: CelluleOrage[]): FeatureCollection<Point> {
  const resultat: Feature<Point>[] = [];
  for (const c of cellules) {
    for (const commune of c.releves.communes_sous_la_pluie) {
      if (commune.lon == null || commune.lat == null) continue;
      resultat.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [commune.lon, commune.lat] },
                      properties: { identifiant: c.identifiant, touchee: true, nom: commune.nom, etiquette: commune.nom } });
    }
    for (const commune of c.estimations.communes_atteintes) {
      if (commune.lon == null || commune.lat == null) continue;
      resultat.push({ type: 'Feature', geometry: { type: 'Point', coordinates: [commune.lon, commune.lat] },
                      properties: { identifiant: c.identifiant, touchee: false, nom: commune.nom, dans_min: commune.dans_min ?? null,
                                    etiquette: `${commune.nom} · ${commune.dans_min} min` } });
    }
  }
  return collection(resultat);
}

// ── Nos estimations ──────────────────────────────────────────────────────────

/** Trajectoire prolongée (une ligne jusqu'à +60 min) et ses repères de temps. */
export function trajectoiresEstimees(cellules: CelluleOrage[]): { lignes: FeatureCollection; reperes: FeatureCollection<Point> } {
  const lignes: Feature[] = [];
  const reperes: Feature<Point>[] = [];
  for (const c of cellules.filter(enMouvement)) {
    const depart = centreCellule(c);
    const { cap_deg: cap, vitesse_kmh: vitesse } = c.estimations;
    const etapes = REPERES_MIN.map(m => deplacer(depart, cap, vitesse * m / 60));
    lignes.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: [depart, ...etapes] },
                  properties: { identifiant: c.identifiant } });
    REPERES_MIN.forEach((m, i) => reperes.push({
      type: 'Feature', geometry: { type: 'Point', coordinates: etapes[i] },
      properties: { identifiant: c.identifiant, minutes: m, etiquette: `+${m} min` },
    }));
  }
  return { lignes: collection(lignes), reperes: collection(reperes) };
}

/** Le contour de la cellule déplacé à +15, +30, +45 et +60 min, si elle gardait sa vitesse et sa
 * direction. `minutes` sert à les pâlir avec le temps. */
export function fantomes(cellules: CelluleOrage[]): FeatureCollection<Polygon> {
  const resultat: Feature<Polygon>[] = [];
  for (const c of cellules.filter(enMouvement)) {
    const { cap_deg: cap, vitesse_kmh: vitesse } = c.estimations;
    for (const m of REPERES_MIN) {
      const km = vitesse * m / 60;
      resultat.push({
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: c.contour.coordinates.map(anneau =>
          anneau.map(p => deplacer([p[0], p[1]], cap, km))) },
        properties: { identifiant: c.identifiant, minutes: m },
      });
    }
  }
  return collection(resultat);
}

/** Cône d'incertitude sur l'heure qui vient : il part de la largeur de la cellule et s'évase selon
 * la stabilité de sa direction passée (`ouvertureCone`). */
export function cones(cellules: CelluleOrage[]): FeatureCollection<Polygon> {
  const resultat: Feature<Polygon>[] = [];
  for (const c of cellules.filter(enMouvement)) {
    const depart = centreCellule(c);
    const { cap_deg: cap, vitesse_kmh: vitesse } = c.estimations;
    const rayon = Math.sqrt(Math.max(c.releves.surface_km2, 1) / Math.PI);
    const tangente = Math.tan(ouvertureCone(c) * Math.PI / 180);
    const pas = [0, ...REPERES_MIN];
    const gauche: Position[] = [];
    const droite: Position[] = [];
    for (const m of pas) {
      const axe = deplacer(depart, cap, vitesse * m / 60);
      const demi = rayon + vitesse * m / 60 * tangente;
      gauche.push(deplacer(axe, cap - 90, demi));
      droite.push(deplacer(axe, cap + 90, demi));
    }
    // Arrondi au bout du cône : un demi-cercle de la demi-largeur finale.
    const bout = deplacer(depart, cap, vitesse);
    const demiFinale = rayon + vitesse * tangente;
    const arc: Position[] = [];
    for (let a = -90 + 20; a < 90; a += 20) arc.push(deplacer(bout, cap + a, demiFinale));
    const anneau = [...gauche, ...arc, ...droite.reverse()];
    anneau.push(anneau[0]);
    resultat.push({ type: 'Feature', geometry: { type: 'Polygon', coordinates: [anneau] },
                    properties: { identifiant: c.identifiant } });
  }
  return collection(resultat);
}

/** Expression d'opacité : la cellule choisie garde `normale`, les autres passent à `estompee`. */
export function selonSelection(selection: string | null, normale: number | unknown[], estompee: number): unknown {
  return selection == null ? normale : ['case', ['==', ['get', 'identifiant'], selection], normale, estompee];
}
