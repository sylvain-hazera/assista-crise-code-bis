import type { Polygon } from 'geojson';

import { aimanter, segmentsDe } from './aimantation.util';

/**
 * L'aimantation du tracé d'une zone sur les contours existants (17/11/2026).
 *
 * Repère d'essai : un degré = 100 pixels, pour que les distances se lisent à l'œil.
 */
describe('aimanter', () => {
  const projeter = (lng: number, lat: number) => ({ x: lng * 100, y: lat * 100 });
  const CARRE: Polygon = {
    type: 'Polygon',
    coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
  };
  const segments = segmentsDe([CARRE]);

  it('colle au sommet proche', () => {
    expect(aimanter(1.05, 1.04, segments, projeter)).toEqual([1, 1]);
  });

  it('colle au bord quand aucun sommet n\'est à portée', () => {
    const position = aimanter(0.5, 0.06, segments, projeter)!;
    expect(position[0]).toBeCloseTo(0.5, 6);
    expect(position[1]).toBeCloseTo(0, 6);
  });

  it('préfère le sommet au bord, même un peu plus loin', () => {
    // À 10 px du sommet (1, 0) et à 6 px du bord : deux zones qui partagent un sommet se
    // touchent exactement, un point au milieu d'un bord laisse toujours un interstice.
    expect(aimanter(0.92, 0.06, segments, projeter)).toEqual([1, 0]);
  });

  it('laisse le point libre hors de portée', () => {
    expect(aimanter(0.5, 0.5, segments, projeter)).toBeUndefined();
    expect(aimanter(3, 3, segments, projeter)).toBeUndefined();
  });

  it('ne dépasse pas l\'extrémité d\'un bord', () => {
    // Dans le prolongement du bord du bas, à 20 px du coin : rien à coller.
    expect(aimanter(1.2, 0, segments, projeter)).toBeUndefined();
  });

  it('lit tous les morceaux d\'un contour en plusieurs parties', () => {
    const iles = segmentsDe([{
      type: 'MultiPolygon',
      coordinates: [CARRE.coordinates, [[[5, 5], [6, 5], [6, 6], [5, 5]]]],
    }]);
    expect(iles.length).toBe(4 + 3);
    expect(aimanter(5.02, 5.03, iles, projeter)).toEqual([5, 5]);
  });

  it('sans contour, rien à aimanter', () => {
    expect(aimanter(0, 0, [], projeter)).toBeUndefined();
  });
});
