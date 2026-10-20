import maplibregl, { StyleSpecification } from 'maplibre-gl';
import { Protocol } from 'pmtiles';
import { layers, namedFlavor } from '@protomaps/basemaps';
import { configInstance } from './config-instance';

/** Fond de carte en ligne (central). */
const STYLE_EN_LIGNE = 'https://raw.githubusercontent.com/go2garret/maps/main/src/assets/json/openStreetMap.json';

let protocoleEnregistre = false;

/** Style à passer à `new maplibregl.Map({ style })` : fond en ligne sur le central, fond hors
 * ligne (PMTiles téléchargé par le satellite, schéma Protomaps) sur un satellite. */
export function styleCarte(): string | StyleSpecification {
  const config = configInstance();
  if (!config.tuiles) return STYLE_EN_LIGNE;
  if (!protocoleEnregistre) {
    maplibregl.addProtocol('pmtiles', new Protocol().tile);
    protocoleEnregistre = true;
  }
  const origine = window.location.origin;
  const assets = `${origine}${config.assetsCarte ?? '/tuiles/assets'}`;
  return {
    version: 8,
    glyphs: `${assets}/fonts/{fontstack}/{range}.pbf`,
    sprite: `${assets}/sprites/v4/light`,
    sources: {
      protomaps: {
        type: 'vector',
        url: `pmtiles://${origine}${config.tuiles}`,
        attribution: '© <a href="https://openstreetmap.org">OpenStreetMap</a>, Protomaps',
      },
    },
    layers: layers('protomaps', namedFlavor('light'), { lang: 'fr' }),
  } as StyleSpecification;
}
