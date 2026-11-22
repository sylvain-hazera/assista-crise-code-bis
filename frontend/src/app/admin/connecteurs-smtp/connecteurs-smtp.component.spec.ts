import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { ConnecteursSmtpComponent } from './connecteurs-smtp.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { ConnecteursSmtpService } from '../../services/connecteurs-smtp.service';

describe('ConnecteursSmtpComponent', () => {
  let service: ConnecteursSmtpService;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest(), imports: [ConnecteursSmtpComponent] });
    service = TestBed.inject(ConnecteursSmtpService);
  });

  it("liste les connecteurs avec leur adresse, et le mot de passe n'est jamais réaffiché", () => {
    spyOn(service, 'lister').and.returnValue(of([{ id: 'c1', institution: 'i1', nom: 'Messagerie', hote: 'smtp.exemple', port: 587,
      chiffrement: 'STARTTLS', expediteur_email: 'envoi@reserve.exemple', expediteur_nom: 'Réserve', actif: true,
      mot_de_passe_renseigne: true } as any]));
    const f = TestBed.createComponent(ConnecteursSmtpComponent);
    f.componentInstance.institutionId = 'i1';
    f.componentInstance.ngOnChanges();
    f.detectChanges();
    expect(f.nativeElement.textContent).toContain('envoi@reserve.exemple');
    f.componentInstance.modifier(f.componentInstance.connecteurs[0]);
    expect(f.componentInstance.saisie?.mot_de_passe).toBe('');
  });

  it('le port suit le chiffrement', () => {
    const c = TestBed.createComponent(ConnecteursSmtpComponent).componentInstance;
    c.institutionId = 'i1';
    c.nouveau();
    c.changerChiffrement('SSL');
    expect(c.saisie?.port).toBe(465);
  });
});
