import { FeuSuivi, PotentielOrageFeu } from '../../../models/veille.model';
import * as dessin from './feux-carte';

function feu(extra: Partial<FeuSuivi> = {}): FeuSuivi {
  return {
    identifiant: '202607221040-44.90_-1.05', latitude: 44.87, longitude: -0.98, distance_km: 12,
    premier_vu: '2026-07-22T10:48:48Z', dernier_vu: '2026-07-22T14:28:00Z', statut: 'actif',
    puissance_mw: 3300, puissance_max_mw: 3323, instant_max: '2026-07-22T14:20:00Z', pixels: 11, confirme: true,
    source_fixe: false,
    courbe: [['2026-07-22T13:20:00Z', 1080, 7], ['2026-07-22T13:40:00Z', 1990, 11], ['2026-07-22T14:00:00Z', 2070, 12],
             ['2026-07-22T14:20:00Z', 3300, 11]],
    contexte: { orage: null, eclairs_30_min: 0, masque_par_nuage: false, potentiel: null },
    ...extra,
  };
}

describe('Feux suivis par satellite sur la carte (feux-carte)', () => {

  it('dit la puissance en MW puis en GW', () => {
    expect(dessin.libellePuissance(115.4)).toBe('115 MW');
    expect(dessin.libellePuissance(3300)).toBe('3,3 GW');
  });

  it('la tendance compare la dernière image à l\'heure qui précède', () => {
    expect(dessin.tendance(feu())).toBe('hausse');
    const baisse = feu({ courbe: [['2026-07-24T16:20:00Z', 12170, 60], ['2026-07-24T16:30:00Z', 12000, 58],
                                  ['2026-07-24T16:40:00Z', 6150, 54]] });
    expect(dessin.tendance(baisse)).toBe('baisse');
    expect(dessin.tendance(feu({ courbe: [['2026-07-22T10:40:00Z', 8, 1]] }))).toBeNull();
  });

  it('signale l\'orage, les rafales descendantes, la foudre, le masque et le seuil', () => {
    const signaux = dessin.signaux(feu({ contexte: {
      orage: { identifiant: 'c1', distance_km: 0, au_dessus: true, intensite_max_mmh: 40, eclairs: 2,
               rafale_descendante: true, rotation: false, grele: false },
      eclairs_30_min: 3, masque_par_nuage: true,
      potentiel: { pft_gw: 213, c_haines: 9.8, palier: 2, potentiel: 'élevé', echeance: '2026-07-24T15:00:00Z',
                   puissance_estimee_gw: [125, 250], atteint_le_seuil: true },
    } }));
    expect(signaux).toEqual(['orage au-dessus du feu', 'rafales descendantes (Doppler)', '3 éclairs en 30 min',
                             'le nuage masque peut-être le feu', 'assez puissant pour un orage de feu (nos estimations)']);
    expect(dessin.signaux(feu())).toEqual([]);
  });

  it('un point par feu, étiqueté de sa puissance, l\'infobulle dit « à confirmer »', () => {
    const [point, eteint] = dessin.feuxVersGeoJSON([feu(), feu({ identifiant: 'b', statut: 'plus vu' })]).features;
    expect(point.geometry.coordinates).toEqual([-0.98, 44.87]);
    expect(point.properties).toEqual(jasmine.objectContaining({ etiquette: '3,3 GW', actif: true, orage: false }));
    expect(point.properties!['infobulle']).toContain('à confirmer');
    expect(eteint.properties!['etiquette']).toBe('plus vu');
    expect(eteint.properties!['infobulle']).toContain('éteint, ou caché par les nuages');
  });

  it('l\'heure du potentiel montrée d\'entrée est la prochaine calculée', () => {
    const potentiel = { echeances: ['2026-07-24T09:00:00Z', '2026-07-24T12:00:00Z', '2026-07-24T15:00:00Z']
      .map(e => ({ echeance: e, palier_max_france: 0 })) } as PotentielOrageFeu;
    expect(dessin.echeanceParDefaut(potentiel, Date.parse('2026-07-24T13:00:00Z'))).toBe('2026-07-24T12:00:00Z');
    expect(dessin.echeanceParDefaut(potentiel, Date.parse('2026-07-24T14:00:00Z'))).toBe('2026-07-24T15:00:00Z');
    expect(dessin.echeanceParDefaut(potentiel, Date.parse('2026-07-25T14:00:00Z'))).toBe('2026-07-24T15:00:00Z');
    expect(dessin.echeanceParDefaut({ echeances: [] } as unknown as PotentielOrageFeu)).toBeNull();
  });

  it('la courbe va du début à la fin, le maximum en haut', () => {
    const chemin = dessin.cheminCourbe(feu(), 240, 40);
    expect(chemin.startsWith('M0.0,')).toBeTrue();
    expect(chemin.endsWith('L240.0,0.0')).toBeTrue();
    expect(dessin.cheminCourbe(feu({ courbe: [['2026-07-22T10:40:00Z', 8, 1]] }), 240, 40)).toBe('');
  });
});
