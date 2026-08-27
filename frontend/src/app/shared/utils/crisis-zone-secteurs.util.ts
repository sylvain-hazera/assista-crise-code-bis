import * as turf from '@turf/turf';
import type { Feature, Polygon, MultiPolygon } from 'geojson';

/** Bufferise chaque contour (commune/département) du rayon donné (km) puis fait l'union
 * de tous les résultats — la zone de crise "composée" demandée : ajouter une commune
 * l'agrandit du contour officiel de cette commune + le rayon partagé de la crise. */
export function composeZoneSecteurs(
  contours: (Polygon | MultiPolygon)[],
  radiusKm: number,
): (Polygon | MultiPolygon) | null {
  if (contours.length === 0) return null;

  const buffered = contours
    .map(geom => turf.buffer(turf.feature(geom), radiusKm, { units: 'kilometers' }))
    .filter((f): f is Feature<Polygon | MultiPolygon> => !!f);

  if (buffered.length === 0) return null;
  if (buffered.length === 1) return buffered[0].geometry;

  const union = turf.union(turf.featureCollection(buffered));
  return union ? union.geometry : null;
}

/** Convertit un Polygon/MultiPolygon GeoJSON en WKT MultiPolygon — la colonne
 * `Crisis.zone_secteurs` est un MultiPolygonField strict côté PostGIS, donc un simple
 * Polygon (ex: une seule commune, ou des contours contigus fusionnés par l'union) doit
 * être explicitement enveloppé avant l'envoi. */
export function toMultiPolygonWkt(geom: Polygon | MultiPolygon): string {
  const ringToWkt = (ring: number[][]) => `(${ring.map(([lng, lat]) => `${lng} ${lat}`).join(', ')})`;
  const polygonCoordsToWkt = (coords: number[][][]) => `(${coords.map(ringToWkt).join(', ')})`;

  if (geom.type === 'Polygon') {
    return `MULTIPOLYGON (${polygonCoordsToWkt(geom.coordinates)})`;
  }
  return `MULTIPOLYGON (${geom.coordinates.map(polygonCoordsToWkt).join(', ')})`;
}
