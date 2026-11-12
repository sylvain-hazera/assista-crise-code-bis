import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { PlanningEquipesComponent } from './planning-equipes.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { PlanningEquipe } from '../../shared/models/planning-equipe.model';

/**
 * Ce que ces tests tiennent :
 *
 * 1. **La case est son propre interrupteur** : recliquer une case qui porte déjà le statut
 *    choisi la retire, au lieu d'imposer un mode « gomme ».
 * 2. **L'effectif affiché est celui du serveur**, annulés et absents déjà exclus : le
 *    recalculer ici finirait par diverger de ce que le bilan annonce.
 * 3. **Les écarts du dernier geste remplacent les précédents** : la liste des conflits est
 *    l'état d'une action, pas un journal qui s'empile.
 */
describe('PlanningEquipesComponent', () => {
  let composant: PlanningEquipesComponent;
  let http: HttpTestingController;

  const JOUR = '2026-11-20';

  function planning(caseOccupee: unknown = null): PlanningEquipe {
    return {
      equipe: 'e1', equipe_nom: 'Garde A', debut: JOUR, fin: JOUR, jours: [JOUR],
      creneaux: ['MATIN', 'SOIR'],
      personnes: [{
        utilisateur: 'u1', nom: 'DURAND', fonction: 'Équipier', creneaux_tenus: 1,
        jours: [{ date: JOUR, creneaux: { MATIN: caseOccupee, SOIR: null } }],
      }],
      effectifs: { [JOUR]: { MATIN: 1 } }, statuts: [], effectif_cible: 0,
      non_couverts: [],
    } as unknown as PlanningEquipe;
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting()],
      imports: [PlanningEquipesComponent],
    });
    composant = TestBed.createComponent(PlanningEquipesComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.match(() => true);
    http.verify();
  });

  it('pose un créneau au clic sur une case libre', () => {
    composant.equipeChoisie = 'e1';
    composant.planning = planning();
    composant.statutAPoser = 'CONFIRME';

    composant.basculerCase(composant.planning!.personnes[0], 0, 'MATIN');

    const appel = http.expectOne(r => r.url.includes('/creneaux-equipe/pointer/'));
    expect(appel.request.body.equipe).toBe('e1');
    expect(appel.request.body.statut).toBe('CONFIRME');
    expect(appel.request.body.creneaux).toEqual([
      { utilisateur: 'u1', date: JOUR, creneau: 'MATIN' }]);
    appel.flush({ poses: 1, mis_a_jour: 0, ignores: [], conflits: [],
                  hors_disponibilite: [] });
  });

  it('recliquer une case qui porte déjà ce statut la retire', () => {
    // La case est son propre interrupteur : un mode « gomme » séparé serait un geste de plus
    // à apprendre pour défaire ce qu'on vient de faire.
    composant.equipeChoisie = 'e1';
    composant.planning = planning({ id: 'c1', statut: 'CONFIRME',
                                    statut_libelle: 'Confirmé', role: '' });
    composant.statutAPoser = 'CONFIRME';

    composant.basculerCase(composant.planning!.personnes[0], 0, 'MATIN');

    const appel = http.expectOne(r => r.url.endsWith('/creneaux-equipe/c1/'));
    expect(appel.request.method).toBe('DELETE');
    appel.flush(null);
  });

  it('recliquer avec un AUTRE statut met à jour au lieu de retirer', () => {
    composant.equipeChoisie = 'e1';
    composant.planning = planning({ id: 'c1', statut: 'PREVU', statut_libelle: 'Prévu',
                                    role: '' });
    composant.statutAPoser = 'CONFIRME';

    composant.basculerCase(composant.planning!.personnes[0], 0, 'MATIN');

    const appel = http.expectOne(r => r.url.includes('/pointer/'));
    expect(appel.request.body.statut).toBe('CONFIRME');
    appel.flush({ poses: 0, mis_a_jour: 1, ignores: [], conflits: [],
                  hors_disponibilite: [] });
  });

  it('pose toute une journée d\'un geste', () => {
    composant.equipeChoisie = 'e1';
    composant.planning = planning();

    composant.poserJournee(composant.planning!.personnes[0], 0);

    const appel = http.expectOne(r => r.url.includes('/pointer/'));
    expect(appel.request.body.creneaux.length).toBe(2);
    appel.flush({ poses: 2, mis_a_jour: 0, ignores: [], conflits: [],
                  hors_disponibilite: [] });
  });

  it('lit l\'effectif tenu du serveur et signale le sous-armement', () => {
    composant.planning = planning();
    composant.effectifCible = 2;

    expect(composant.effectif(JOUR, 'MATIN')).toBe(1);
    expect(composant.sousArme(JOUR, 'MATIN')).toBeTrue();
    expect(composant.effectif(JOUR, 'SOIR')).toBe(0);
  });

  it('remplace les écarts du geste précédent', () => {
    // Ce sont les écarts de la DERNIÈRE action, pas un journal qui s'empile : une liste qui
    // grossit à chaque clic ne se lit plus.
    composant.equipeChoisie = 'e1';
    composant.planning = planning();
    composant.conflits = [{ utilisateur: 'vieux', nom: 'ANCIEN', date: JOUR,
                            creneau: 'SOIR', equipe: 'e9', equipe_nom: 'Vieille',
                            motif: 'ancien' }];

    composant.basculerCase(composant.planning!.personnes[0], 0, 'MATIN');
    http.expectOne(r => r.url.includes('/pointer/')).flush({
      poses: 1, mis_a_jour: 0, ignores: [], conflits: [], hors_disponibilite: [],
    });

    expect(composant.conflits).toEqual([]);
  });
});
