import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MatrixSalonChatComponent } from './matrix-salon-chat.component';
import { MatrixMessage } from '../../../shared/models/team.model';

/**
 * Le journal de bord de la crise se nourrit des messages des équipes : dans la cellule de
 * crise, chaque message peut y être porté d'un geste. Ailleurs, le bouton n'existe pas.
 */
describe('MatrixSalonChatComponent — porter un message au journal de bord', () => {
  let fixture: ComponentFixture<MatrixSalonChatComponent>;

  const MESSAGE: MatrixMessage = {
    event_id: '$m1', texte: 'Pont de la gare coupé, déviation en place.', horodatage: Date.UTC(2026, 10, 16, 14, 5),
    expediteur_id: 'u1', expediteur_nom: 'Équipier d’essai', moi: false, urgent: true, vu_par: [],
  };

  function afficher(journal: boolean) {
    fixture = TestBed.createComponent(MatrixSalonChatComponent);
    const composant = fixture.componentInstance;
    composant.journal = journal;
    composant.chargement = false;
    composant.messages = [MESSAGE];
    fixture.detectChanges();
  }
  const bouton = (): HTMLButtonElement | null => fixture.nativeElement.querySelector('.btn-journal');

  beforeEach(() => TestBed.configureTestingModule({ imports: [MatrixSalonChatComponent] }));

  it('signale le message à son hôte, puis montre qu’il est au journal', () => {
    afficher(true);
    const recus: MatrixMessage[] = [];
    fixture.componentInstance.versJournal.subscribe(m => recus.push(m));

    bouton()!.click();
    fixture.detectChanges();

    expect(recus).toEqual([MESSAGE]);
    // Une coche et un bouton inactif : le même message ne part pas deux fois par mégarde.
    expect(bouton()!.disabled).toBeTrue();
    expect(bouton()!.textContent).toContain('Au journal');
  });

  it('ne propose rien hors de la cellule de crise', () => {
    afficher(false);

    expect(bouton()).toBeNull();
  });
});
