import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { BoutonRapportComponent } from './bouton-rapport.component';
import { RapportService } from '../../../../services/rapport.service';
import { fournisseursDeTest } from '../../../../testing/test-providers';

describe('BoutonRapportComponent', () => {
  let fixture: ComponentFixture<BoutonRapportComponent>;
  let rapports: jasmine.SpyObj<RapportService>;
  const bouton = () => fixture.nativeElement.querySelector('button') as HTMLButtonElement;

  beforeEach(() => {
    rapports = jasmine.createSpyObj('RapportService', ['telecharger']);
    TestBed.configureTestingModule({
      imports: [BoutonRapportComponent],
      providers: [...fournisseursDeTest(), { provide: RapportService, useValue: rapports }],
    });
    fixture = TestBed.createComponent(BoutonRapportComponent);
    fixture.componentInstance.nature = 'dossier';
    fixture.componentInstance.id = 'd1';
    fixture.componentInstance.reference = 'DOS 2026/014';
  });

  it('s’appelle « Rapport de clôture » une fois l’objet clos, et nomme le fichier d’après la référence', () => {
    rapports.telecharger.and.returnValue(of(true));
    fixture.detectChanges();
    expect(bouton().textContent).toContain('Rapport (PDF)');

    fixture.componentInstance.clos = true;
    fixture.detectChanges();
    expect(bouton().textContent).toContain('Rapport de clôture (PDF)');

    bouton().click();
    expect(rapports.telecharger).toHaveBeenCalledWith('dossier', 'd1', 'rapport-dossier-DOS-2026-014', false);

    // « toutes les photos » : la case lève le plafond par défaut.
    const caseACocher = fixture.nativeElement.querySelector('input[type=checkbox]') as HTMLInputElement;
    caseACocher.click();
    bouton().click();
    expect(rapports.telecharger).toHaveBeenCalledWith('dossier', 'd1', 'rapport-dossier-DOS-2026-014', true);
    expect(fixture.componentInstance.edition).toBeFalse();
  });

  it('dit quand l’accès est refusé, et reste inactif sans identifiant', () => {
    rapports.telecharger.and.returnValue(throwError(() => ({ status: 403 })));
    fixture.detectChanges();
    bouton().click();
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain("Vous n'avez pas accès à ce rapport");

    fixture.componentInstance.id = null;
    fixture.detectChanges();
    expect(bouton().disabled).toBeTrue();
  });
});
