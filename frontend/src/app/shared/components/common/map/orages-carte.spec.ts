import { CelluleOrage } from '../../../models/veille.model';
import * as dessin from './orages-carte';

/** Une cellule carrée d'environ 10 km autour de (2,1 ; 46,1), qui va vers l'est à 60 km/h. */
function cellule(extra: { trace?: CelluleOrage['releves']['trace']; cap?: number | null; vitesse?: number | null } = {}): CelluleOrage {
  return {
    identifiant: 'c1', distance_km: null,
    contour: { type: 'Polygon', coordinates: [[[2.05, 46.05], [2.15, 46.05], [2.15, 46.15], [2.05, 46.15], [2.05, 46.05]]] },
    couloir: null,
    releves: {
      intensite_max_mmh: 64, intensite_moyenne_mmh: 35, libelle: 'pluie intense', surface_km2: 80, tendance_mmh: null,
      communes_sous_la_pluie: [{ code: '1', nom: 'Dessous', lon: 2.1, lat: 46.1 }],
      rafale_mesuree: null, eclairs: null, doppler: null,
      trace: extra.trace ?? [
        ['2026-11-20T06:00:00Z', 46.1, 1.9, 40], ['2026-11-20T06:05:00Z', 46.1, 1.95, 50], ['2026-11-20T06:10:00Z', 46.1, 2.0, 64],
      ],
      suivi: {
        suivie_depuis_min: 10, noyaux: 2, noyaux_intenses: 1, surface_10min_km2: 5, max_10min_mmh: 24,
        evolution: 'renforcement', fusion: true, division: false,
        noyaux_positions: [{ lon: 2.08, lat: 46.1, seuil: 50, max_mmh: 64, fusion: true, division: false }],
      },
    },
    estimations: {
      cap_deg: extra.cap === undefined ? 90 : extra.cap, vers: "l'est",
      vitesse_kmh: extra.vitesse === undefined ? 60 : extra.vitesse,
      communes_atteintes: [{ code: '2', nom: 'Plus-loin', dans_min: 20, lon: 2.4, lat: 46.1 }, { code: '3', nom: 'Sans-position', dans_min: 30 }],
      ligne_de_grain: false, longueur_km: 10,
    },
    prevision_meteo_france: { grele: true, rafale_kmh: null, grele_diagnostic_kgm2: null, grele_niveau: null },
  };
}

function kmEntre([lon1, lat1]: number[], [lon2, lat2]: number[]): number {
  const dx = (lon2 - lon1) * 111.32 * Math.cos((lat1 + lat2) / 2 * Math.PI / 180);
  return Math.hypot(dx, (lat2 - lat1) * 111.32);
}

describe('Cellules orageuses sur la carte (orages-carte)', () => {

  it('déplace un point à la bonne distance et dans la bonne direction', () => {
    const arrivee = dessin.deplacer([2, 46], 90, 30);
    expect(kmEntre([2, 46], arrivee)).toBeCloseTo(30, 1);
    expect(arrivee[1]).toBeCloseTo(46, 6);
    expect(dessin.direction([2, 46], arrivee)).toBeCloseTo(90, 3);
  });

  it('place la cellule à sa dernière position, flèche vers où elle va', () => {
    const [centre] = dessin.centres([cellule()]).features;
    expect(centre.geometry.coordinates).toEqual([2.0, 46.1]);
    expect(centre.properties).toEqual(jasmine.objectContaining({ cap: 90, mobile: true, renforcement: true, etiquette: '64 mm/h · 60 km/h' }));
    // Sans trajectoire : le milieu du contour.
    const [seul] = dessin.centres([cellule({ trace: [] })]).features;
    expect(seul.geometry.coordinates[0]).toBeCloseTo(2.1, 6);
    expect(seul.geometry.coordinates[1]).toBeCloseTo(46.1, 6);
  });

  it('la trajectoire passée a un segment par pas, coloré par l\'intensité d\'arrivée', () => {
    const { segments, points } = dessin.trajectoires([cellule()]);
    expect(segments.features.length).toBe(2);
    expect(segments.features.map(f => f.properties!['intensite'])).toEqual([50, 64]);
    expect(points.features.length).toBe(3);
    expect(points.features[0].properties!['etiquette']).toBe(new Date('2026-11-20T06:00:00Z').toTimeString().slice(0, 5));
    expect(points.features[2].properties!['etiquette']).toBe('');          // la position actuelle porte déjà la flèche
  });

  it('les contours fantômes sont le contour déplacé à +15 … +60 min', () => {
    const f = dessin.fantomes([cellule()]).features;
    expect(f.map(x => x.properties!['minutes'])).toEqual([15, 30, 45, 60]);
    const coin = cellule().contour.coordinates[0][0];
    expect(kmEntre(coin, f[3].geometry.coordinates[0][0])).toBeCloseTo(60, 0);     // 60 km/h pendant une heure
    expect(kmEntre(coin, f[0].geometry.coordinates[0][0])).toBeCloseTo(15, 0);
  });

  it('la trajectoire estimée porte ses repères de temps', () => {
    const { lignes, reperes } = dessin.trajectoiresEstimees([cellule()]);
    expect(lignes.features.length).toBe(1);
    expect(reperes.features.map(r => r.properties!['etiquette'])).toEqual(['+15 min', '+30 min', '+45 min', '+60 min']);
    expect(kmEntre([2.0, 46.1], reperes.features[1].geometry.coordinates)).toBeCloseTo(30, 0);
  });

  it('une cellule immobile n\'a ni flèche, ni estimations', () => {
    const immobile = cellule({ cap: null, vitesse: null });
    expect(dessin.centres([immobile]).features[0].properties!['mobile']).toBeFalse();
    expect(dessin.fantomes([immobile]).features).toEqual([]);
    expect(dessin.cones([immobile]).features).toEqual([]);
    expect(dessin.trajectoiresEstimees([immobile]).reperes.features).toEqual([]);
  });

  it('le cône est étroit pour une trajectoire droite, large pour une trajectoire hésitante', () => {
    expect(dessin.ouvertureCone(cellule())).toBe(dessin.OUVERTURE_MIN_DEG);
    const zigzag = cellule({ trace: [
      ['2026-11-20T06:00:00Z', 46.1, 1.9], ['2026-11-20T06:05:00Z', 46.15, 1.95],
      ['2026-11-20T06:10:00Z', 46.05, 2.0], ['2026-11-20T06:15:00Z', 46.15, 2.05],
    ] });
    expect(dessin.ouvertureCone(zigzag)).toBeGreaterThan(30);
    expect(dessin.ouvertureCone(cellule({ trace: [['2026-11-20T06:00:00Z', 46.1, 1.9]] }))).toBe(dessin.OUVERTURE_DEFAUT_DEG);
    const anneau = dessin.cones([cellule()]).features[0].geometry.coordinates[0];
    expect(anneau[0]).toEqual(anneau[anneau.length - 1]);
    // Plus large au bout qu'au départ.
    const largeur = (i: number, j: number) => kmEntre(anneau[i], anneau[j]);
    expect(largeur(4, anneau.length - 6)).toBeGreaterThan(largeur(0, anneau.length - 2));
  });

  it('communes : sous la pluie et atteintes, celles sans position écartées', () => {
    const f = dessin.communes([cellule()]).features;
    expect(f.map(x => [x.properties!['nom'], x.properties!['touchee']])).toEqual([['Dessous', true], ['Plus-loin', false]]);
    expect(f[1].properties!['etiquette']).toBe('Plus-loin · 20 min');
  });

  it('noyaux et signatures', () => {
    expect(dessin.noyaux([cellule()]).features[0].properties).toEqual(jasmine.objectContaining({ seuil: 50, etiquette: 'fusion' }));
    const avecRotation = cellule();
    avecRotation.releves.doppler = {
      rotation: { vrot_ms: 18, elevations: [0.4, 0.8], radar: 'Bordeaux', lon: 2.11, lat: 46.12 },
      grele: null, divergence: null, polarimetrie: null, radars: ['Bordeaux'], heure: '2026-11-20T06:10:00Z',
    };
    const types = dessin.signatures([avecRotation]).features.map(f => [f.properties!['type'], f.geometry.coordinates]);
    expect(types[0]).toEqual(['rotation', [2.11, 46.12]]);
    expect(types[1][0]).toBe('grele-prevue');
  });

  it('la sélection estompe les autres cellules', () => {
    expect(dessin.selonSelection(null, 0.5, 0.1)).toBe(0.5);
    expect(dessin.selonSelection('c1', 0.5, 0.1)).toEqual(['case', ['==', ['get', 'identifiant'], 'c1'], 0.5, 0.1]);
  });
});
