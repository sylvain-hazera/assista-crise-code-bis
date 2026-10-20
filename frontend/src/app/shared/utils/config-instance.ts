/** Lu au démarrage (main.ts) : présent seulement sur un satellite (satellite/nginx-satellite.conf).
 * Fichier sans dépendance : il fait partie du bundle initial. */
export interface ConfigInstance {
  satellite?: boolean;
  tuiles?: string;        // fichier PMTiles local
  assetsCarte?: string;   // polices et pictogrammes du fond de carte
}

let config: ConfigInstance = {};

export function definirConfigInstance(c: ConfigInstance): void {
  config = c ?? {};
}

export function configInstance(): ConfigInstance {
  return config;
}

export function estSatellite(): boolean {
  return !!config.satellite;
}
