import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { HabitationsPageComponent } from './habitations-page.component';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { environment } from '../../../../environments/environment';
import { LABELS_NATURE_DEGATS, LABELS_STATUT_EVALUATION, STATUTS_AVEC_DEGATS } from '../../../shared/models/habitation.model';

/** Suivi des dégâts sur le terrain : l'agent pointe la maison où il se trouve, quel que soit
 * le sinistre. Le composant n'est pas rendu ici (sa carte demande WebGL) : on éprouve sa logique. */
describe('HabitationsPageComponent — pointage terrain', () => {
  let composant: HabitationsPageComponent;
  let http: HttpTestingController;
  const api = environment.apiUrl;
  const MAISON = { id: 'h1', adresse: '14 Allée des Pins 33260 La Teste-de-Buch', crise: 'c1', statut_evaluation: 'NON_EVALUEE' } as any;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [HabitationsPageComponent], providers: fournisseursDeTest() });
    composant = TestBed.createComponent(HabitationsPageComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => { http.match(() => true); });

  it('pointe la maison à la position donnée et ouvre sa fiche, sans doubler une maison déjà référencée', () => {
    const ouverte = spyOn(composant, 'ouvrirFiche');

    composant.pointer('c1', 44.63, -1.14);
    const creation = http.expectOne(`${api}/habitations/pointer/`);
    expect(creation.request.body).toEqual({ crise: 'c1', latitude: 44.63, longitude: -1.14 });
    creation.flush({ ...MAISON, existante: false });
    expect(composant.habitations.length).toBe(1);
    expect(composant.messagePointage).toContain('Maison pointée : 14 Allée des Pins');
    expect(ouverte).toHaveBeenCalled();

    composant.pointer('c1', 44.63001, -1.14001, 80);
    http.expectOne(`${api}/habitations/pointer/`).flush({ ...MAISON, existante: true });
    expect(composant.habitations.length).toBe(1);                       // pas de doublon dans la liste
    expect(composant.messagePointage).toContain('Maison déjà référencée ici');
    expect(composant.messagePointage).toContain('précise à 80 m seulement');
  });

  it('demande la crise quand on ne sait pas laquelle, et la devine quand une seule est ouverte', () => {
    composant.crises = [{ id: 'c1', is_open: true }, { id: 'c2', is_open: true }] as any;
    composant.pointerIci();
    expect(composant.messagePointage).toContain('Choisissez d’abord la crise');
    http.expectNone(`${api}/habitations/pointer/`);

    composant.crises = [{ id: 'c1', is_open: true }, { id: 'c0', is_open: false }] as any;
    expect(composant.crisePourPointer).toBe('c1');
    composant.filtres.crise = 'c0';
    expect(composant.crisePourPointer).toBe('c0');                      // le filtre l'emporte
  });

  it('un intervenant propose son pointage et son constat, que la commune valide', () => {
    const POINTAGE = { id: 'p1', a_valider: true, statut: 'A_VALIDER', adresse: '14 Allée des Pins', statut_evaluation: 'NON_EVALUEE',
      nature_degats: '', commentaire: '', existante: false, le_mien: true, peut_valider: false } as any;
    const ouverte = spyOn(composant, 'ouvrirFiche');

    composant.pointer('c1', 44.63, -1.14);
    http.expectOne(`${api}/habitations/pointer/`).flush(POINTAGE, { status: 202, statusText: 'Accepted' });
    http.expectOne(`${api}/habitations/pointages/`).flush([POINTAGE]);
    expect(ouverte).not.toHaveBeenCalled();                              // pas encore une habitation
    expect(composant.habitations.length).toBe(0);
    expect(composant.messagePointage).toContain('la commune validera');
    expect(composant.mesPointages.length).toBe(1);

    composant.constat = { statut_evaluation: 'DETRUITE', nature_degats: 'FEU', commentaire: 'Toiture effondrée.' };
    composant.envoyerConstat();
    const envoi = http.expectOne(`${api}/habitations/pointages/p1/constater/`);
    expect(envoi.request.body).toEqual({ statut_evaluation: 'DETRUITE', nature_degats: 'FEU', commentaire: 'Toiture effondrée.' });
    envoi.flush({ ...POINTAGE, statut_evaluation: 'DETRUITE' });
    expect(composant.pointagePropose).toBeNull();

    // Côté commune : la liste « à valider », puis la validation retire la ligne et recharge la carte.
    composant.pointages = [{ ...POINTAGE, le_mien: false, peut_valider: true }];
    expect(composant.pointagesAValider.length).toBe(1);
    composant.validerPointage(composant.pointages[0]);
    http.expectOne(`${api}/habitations/pointages/p1/valider/`).flush({ pointage: POINTAGE, habitation: MAISON });
    expect(composant.pointages.length).toBe(0);
    expect(composant.messagePointage).toContain('Pointage validé : 14 Allée des Pins');

    composant.pointages = [{ ...POINTAGE, le_mien: false, peut_valider: true }];
    composant.refuserPointage(composant.pointages[0], 'Hors périmètre.');
    const refus = http.expectOne(`${api}/habitations/pointages/p1/refuser/`);
    expect(refus.request.body).toEqual({ motif: 'Hors périmètre.' });
    refus.flush({ ...POINTAGE, statut: 'REFUSE' });
    expect(composant.pointages.length).toBe(0);
  });

  it('affiche le refus du serveur (hors zone, module non activé)', () => {
    composant.pointer('c1', 44.63, -1.14);
    http.expectOne(`${api}/habitations/pointer/`).flush({ detail: 'Ce point est hors de la zone définie pour le suivi des dégâts.' },
      { status: 403, statusText: 'Forbidden' });
    expect(composant.messagePointage).toContain('hors de la zone');
  });

  it('le suivi n’est pas réservé à l’eau : une maison peut être détruite, par le feu ou le vent', () => {
    expect(LABELS_STATUT_EVALUATION.DETRUITE).toBe('Détruite');
    expect(STATUTS_AVEC_DEGATS).toContain('DETRUITE');
    expect(Object.keys(LABELS_NATURE_DEGATS)).toEqual(jasmine.arrayContaining(['EAU', 'FEU', 'VENT', 'GRELE']));
  });
});
