import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { PreparerInvitationComponent } from './preparer-invitation.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { DelegationGestionService } from '../../services/delegation-gestion.service';

describe('PreparerInvitationComponent', () => {
  let service: DelegationGestionService;
  const preparation = {
    resume: { vers_referent: 1, vers_officielle: 1, sans_adresse: ['Mairie - Muette'], deja_membres: 0 },
    pretes: [{ id: 'm1', nom: 'Mairie - A' }, { id: 'm2', nom: 'Mairie - B' }],
    sujet: 'Votre espace [COLLECTIVITE] est prêt', corps: '[SALUTATION]\n[LIEN]', champs: ['COLLECTIVITE', 'LIEN'],
    connecteurs: [
      { cle: 'brevo:a', type: 'brevo', libelle: 'Brevo — Réserve', adresse: 'contact@reserve.exemple', institution: 'Réserve',
        dernier_succes: null, dernier_echec: null, dernier_echec_motif: '' },
      { cle: 'plateforme', type: 'plateforme', libelle: 'SMTP de la plateforme', adresse: 'ne-pas-repondre@exemple.fr',
        institution: '', dernier_succes: null, dernier_echec: null, dernier_echec_motif: '' },
    ],
  } as any;

  function creer() {
    TestBed.configureTestingModule({ providers: fournisseursDeTest(), imports: [PreparerInvitationComponent] });
    service = TestBed.inject(DelegationGestionService);
    spyOn(service, 'preparerInvitation').and.returnValue(of(preparation));
    const f = TestBed.createComponent(PreparerInvitationComponent);
    f.componentInstance.delegationId = 'd1';
    f.componentInstance.institutions = ['m1', 'm2', 'm3'];
    f.detectChanges();
    return f;
  }

  it('propose le texte, les connecteurs avec leur adresse, le premier par défaut', () => {
    const f = creer();
    const c = f.componentInstance;
    expect(c.sujet).toContain('[COLLECTIVITE]');
    expect(c.connecteur).toBe('brevo:a');
    expect(f.nativeElement.textContent).toContain('contact@reserve.exemple');
    expect(f.nativeElement.textContent).toContain('2 collectivité(s)');
  });

  it("refuse d'envoyer un texte sans [LIEN]", () => {
    const c = creer().componentInstance;
    c.corps = 'Bonjour';
    expect(c.lienPresent).toBeFalse();
  });

  it('envoie après confirmation, par le connecteur choisi', () => {
    const f = creer();
    const c = f.componentInstance;
    spyOn(window, 'confirm').and.returnValue(true);
    const lancer = spyOn(service, 'lancerCampagne').and.returnValue(of({ id: 'c1' } as any));
    const emis = spyOn(c.lancee, 'emit');
    c.connecteur = 'plateforme';
    c.envoyer();
    expect(lancer).toHaveBeenCalledWith('d1', ['m1', 'm2'], c.sujet, c.corps, 'plateforme');
    expect(emis).toHaveBeenCalled();
  });

  it("montre l'aperçu d'une collectivité", () => {
    const c = creer().componentInstance;
    spyOn(service, 'apercuInvitation').and.returnValue(of({ etat: 'prete', destinataire: 'x@y.fr', sujet: 'Votre espace A', corps: 'Bonjour,' }));
    c.voirApercu();
    expect(c.apercu?.sujet).toBe('Votre espace A');
  });
});
