export interface GeoPoint {
  type: 'Point';
  coordinates: [number, number];        // [longitude, latitude]
}


/** Extrait latitude et longitude d'un GeoPoint Django */
export function geoPointToLatLng(point: GeoPoint): { latitude: number; longitude: number } {
  return { latitude: point.coordinates[1], longitude: point.coordinates[0] };
}

/** Construit un GeoPoint JSON à envoyer dans un FormData */
export function latLngToGeoJson(latitude: number, longitude: number): string {
  return JSON.stringify({ type: 'Point', coordinates: [longitude, latitude] });
}