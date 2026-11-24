import { TestBed } from '@angular/core/testing';
import { ActivationPointEau } from '../pilotage.service';
import { COULEURS_MINI_CARTE, MiniCartePointsEauComponent } from './mini-carte-points-eau.component';

const candidat = (id: number, lat: number) => ({
  id, source: 'OSM', ref: String(id), type_pei: 'PI', type_libelle: "Poteau d'incendie", ref_terrain: '', debit: null,
  volume: null, etat: 'INCONNU', distance_km: 0.3, latitude: lat, longitude: 3.88, attribution: null,
  nom: `Poteau d'incendie n° ${id}`,
});

const activation = (pei: number, statut: ActivationPointEau['statut']): ActivationPointEau => ({
  id: `a${pei}`, nom: `Poteau d'incendie n° ${pei}`, type_pei: 'PI', debit: null, volume: null, latitude: 45.05, longitude: 3.89,
  pei, statut, statut_libelle: statut, equipe: null, indicatif: 'RCSC', equipe_id: null, mission: null,
  demande_le: '2026-11-24T12:00:00Z', en_route_le: null, actif_le: null, ferme_le: null, codis_prevenu_le: null,
});

describe('Mini-carte des points d’eau (24/11/2026)', () => {
  it('les candidats, les cochés et les points ouverts ont chacun leur couleur ; un point ouvert n’est plus candidat', () => {
    const composant = TestBed.createComponent(MiniCartePointsEauComponent).componentInstance;
    composant.candidats = [candidat(1, 45.04), candidat(2, 45.045), candidat(3, 45.05)];
    composant.activations = [activation(3, 'ACTIF'), activation(9, 'ANNULE')];
    composant.choix = { 2: true };

    const traits = composant.donnees().features.map(f => f.properties as { id?: number; genre: string; couleur: string });
    expect(traits.length).toBe(3);                                   // 1, 2 et l'activation du 3 ; pas l'annulée
    expect(traits.find(t => t.id === 1)?.couleur).toBe(COULEURS_MINI_CARTE['candidat']);
    expect(traits.find(t => t.id === 2)?.couleur).toBe(COULEURS_MINI_CARTE['choisi']);
    expect(traits.filter(t => t.genre === 'activation').map(t => t.couleur)).toEqual([COULEURS_MINI_CARTE['ACTIF']]);
  });
});
