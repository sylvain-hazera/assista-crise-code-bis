import type { MultiPolygon, Polygon, Position } from 'geojson';

/** Convertit une position géographique en pixels d'écran. */
export type Projeter = (lng: number, lat: number) => { x: number; y: number };

/** Les segments (paires de sommets consécutifs) de tous les anneaux des contours donnés. */
export function segmentsDe(contours: (Polygon | MultiPolygon)[]): [Position, Position][] {
  const segments: [Position, Position][] = [];
  for (const contour of contours) {
    const polygones = contour.type === 'Polygon' ? [contour.coordinates] : contour.coordinates;
    for (const anneaux of polygones) {
      for (const anneau of anneaux) {
        for (let i = 0; i + 1 < anneau.length; i++) {
          segments.push([anneau[i], anneau[i + 1]]);
        }
      }
    }
  }
  return segments;
}

/**
 * Aimantation du tracé sur des contours existants.
 *
 * Rend la position à laquelle « coller » le point en cours, ou `undefined` s'il n'y a rien à
 * portée. **Un sommet l'emporte sur un bord** : deux zones qui partagent un sommet se touchent
 * exactement, alors qu'un point posé au milieu d'un bord laisse toujours un interstice ou un
 * chevauchement d'un pixel. La distance se mesure en pixels d'écran et non en mètres : ce que
 * l'utilisateur vise, c'est ce qu'il voit, quel que soit le zoom.
 *
 * Le projeté sur un bord est calculé à l'écran puis ramené en coordonnées par interpolation
 * le long du segment — exact à l'échelle d'une commune, où un segment est une ligne droite
 * dans les deux repères.
 */
export function aimanter(
  lng: number, lat: number,
  segments: [Position, Position][],
  projeter: Projeter,
  tolerancePx = 12,
): Position | undefined {
  const curseur = projeter(lng, lat);
  let sommet: Position | undefined;
  let distanceSommet = tolerancePx;
  let bord: Position | undefined;
  let distanceBord = tolerancePx;

  for (const [a, b] of segments) {
    const pa = projeter(a[0], a[1]);
    const pb = projeter(b[0], b[1]);

    for (const [point, ecran] of [[a, pa], [b, pb]] as [Position, { x: number; y: number }][]) {
      const d = Math.hypot(ecran.x - curseur.x, ecran.y - curseur.y);
      if (d <= distanceSommet) {
        distanceSommet = d;
        sommet = [point[0], point[1]];
      }
    }

    const dx = pb.x - pa.x;
    const dy = pb.y - pa.y;
    const longueur2 = dx * dx + dy * dy;
    if (longueur2 === 0) continue;
    const t = Math.max(0, Math.min(1, ((curseur.x - pa.x) * dx + (curseur.y - pa.y) * dy) / longueur2));
    const d = Math.hypot(pa.x + t * dx - curseur.x, pa.y + t * dy - curseur.y);
    if (d < distanceBord) {
      distanceBord = d;
      bord = [a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])];
    }
  }

  return sommet ?? bord;
}
