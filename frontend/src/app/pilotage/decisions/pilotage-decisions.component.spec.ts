import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { PilotageDecisionsComponent } from './pilotage-decisions.component';
import { PilotageService } from '../pilotage.service';
import { AuthService } from '../../auth/services/auth.service';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('PilotageDecisionsComponent', () => {
  it('enregistre une décision et ses actions, puis change l’état d’une action', () => {
    TestBed.configureTestingModule({
      imports: [PilotageDecisionsComponent],
      providers: [...fournisseursDeTest(), provideHttpClientTesting(),
                  { provide: AuthService, useValue: { getCurrentUser: () => ({ institution_id: null }) } }],
    });
    TestBed.inject(PilotageService).choisir('c1');
    const http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(PilotageDecisionsComponent);
    fixture.detectChanges();
    http.expectOne(r => r.url.endsWith('/cellule/decisions/')).flush([]);
    http.expectOne(r => r.url.endsWith('/cellule/actions/')).flush([]);
    http.expectOne(r => r.url.endsWith('/cellule/releves/')).flush([]);
    const c = fixture.componentInstance;
    c.texte = 'Évacuer la rue des Saules';
    c.ajouterAction();
    c.nouvelles[0].intitule = 'Ouvrir le gymnase';
    c.nouvelles[0].responsable_libre = 'Services techniques';
    c.decider();
    const req = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/cellule/decisions/'));
    expect(req.request.body).toEqual(jasmine.objectContaining({ crise: 'c1', texte: 'Évacuer la rue des Saules' }));
    expect(req.request.body.actions[0]).toEqual(jasmine.objectContaining({ intitule: 'Ouvrir le gymnase', responsable_libre: 'Services techniques' }));
    const action = { id: 'a1', crise: 'c1', decision: 'd1', intitule: 'Ouvrir le gymnase', responsable: null, responsable_nom: 'Services techniques',
                     responsable_libre: 'Services techniques', equipe: null, equipe_nom: null, echeance: null, statut: 'A_FAIRE' as const,
                     statut_libelle: 'À faire', faite_le: null, commentaire: '', en_retard: false };
    req.flush({ id: 'd1', crise: 'c1', texte: 'Évacuer la rue des Saules', auteur_nom: 'X', decidee_le: '2026-11-23T10:00:00Z', actions: [action] });
    http.expectOne(r => r.url.endsWith('/cellule/actions/')).flush([action]);
    expect(c.decisions.length).toBe(1);
    c.changerStatut(c.actions[0], 'FAIT');
    http.expectOne(r => r.method === 'PATCH' && r.url.endsWith('/cellule/actions/a1/')).flush({ ...action, statut: 'FAIT', faite_le: '2026-11-23T11:00:00Z' });
    expect(c.actions[0].statut).toBe('FAIT');
    http.verify();
  });
});
