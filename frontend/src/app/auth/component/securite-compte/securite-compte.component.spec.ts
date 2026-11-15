import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { Router } from '@angular/router';

import { SecuriteCompteComponent } from './securite-compte.component';
import { AuthService } from '../../services/auth.service';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { environment } from '../../../../environments/environment';
import { EtatSecondFacteur } from '../../../shared/models/user.model';

describe('SecuriteCompteComponent', () => {
  let fixture: ComponentFixture<SecuriteCompteComponent>;
  let composant: SecuriteCompteComponent;
  let http: HttpTestingController;
  let router: Router;
  let auth: AuthService;
  const api = environment.apiUrl;

  const ETAT: EtatSecondFacteur = {
    applicable: true, actif: false, requis: true, bloquant: false,
    date_limite: '2026-11-30T05:00:00Z', codes_secours_restants: 0, mot_de_passe_defini: true,
  };
  const PREPARATION = {
    secret: 'ABCDEFGHIJKLMNOP', adresse: 'otpauth://totp/Assista-Crise:a?secret=ABCDEFGHIJKLMNOP',
    qr_svg: '<svg xmlns="http://www.w3.org/2000/svg"><path d="M0 0h1v1H0z"/></svg>',
  };

  function monter(): void {
    fixture = TestBed.createComponent(SecuriteCompteComponent);
    composant = fixture.componentInstance;
    fixture.detectChanges();
  }

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [SecuriteCompteComponent],
    }).compileComponents();
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    auth = TestBed.inject(AuthService);
    spyOn(router, 'navigate').and.resolveTo(true);
    spyOn(router, 'navigateByUrl').and.resolveTo(true);
  });

  afterEach(() => localStorage.clear());

  it('renvoie vers la connexion qui arrive sans session ni activation en attente', () => {
    monter();
    expect(router.navigate).toHaveBeenCalledWith(['/login'], { queryParams: { returnUrl: '/securite-du-compte' } });
  });

  describe('depuis une session ouverte', () => {
    beforeEach(() => {
      localStorage.setItem('access_token', 'jeton');
      localStorage.setItem('current_user', JSON.stringify({ id: 'u', second_facteur: ETAT }));
    });

    it("dit l'échéance et redemande le mot de passe avant de montrer le QR code", () => {
      monter();
      http.expectOne(`${api}/second-facteur/`).flush(ETAT);
      fixture.detectChanges();
      expect(fixture.nativeElement.textContent).toContain('30/11/2026');
      expect(fixture.nativeElement.querySelector('.qr')).toBeNull();

      composant.motDePasse = 'secret';
      composant.preparer();
      const requete = http.expectOne(`${api}/second-facteur/preparer/`);
      expect(requete.request.body.mot_de_passe).toBe('secret');
      requete.flush(PREPARATION);
      fixture.detectChanges();
      expect(composant.motDePasse).toBe('');
      expect(fixture.nativeElement.querySelector('.qr svg')).not.toBeNull();
      expect(composant.secretLisible).toBe('ABCD EFGH IJKL MNOP');
    });

    it("ne demande pas de mot de passe à un compte qui n'en a pas", () => {
      monter();
      http.expectOne(`${api}/second-facteur/`).flush({ ...ETAT, mot_de_passe_defini: false });
      fixture.detectChanges();
      expect(fixture.nativeElement.querySelector('#mdp')).toBeNull();
    });

    it("après activation, montre les codes de secours une fois et met le rappel à jour", () => {
      monter();
      http.expectOne(`${api}/second-facteur/`).flush(ETAT);
      composant.motDePasse = 'secret';
      composant.preparer();
      http.expectOne(`${api}/second-facteur/preparer/`).flush(PREPARATION);
      composant.code = '123456';
      composant.confirmer();
      http.expectOne(`${api}/second-facteur/confirmer/`).flush({
        codes_secours: ['aaaaa-bbbbb', 'ccccc-ddddd'], etat: { ...ETAT, actif: true, date_limite: null },
      });
      fixture.detectChanges();
      expect(composant.ecran).toBe('codes');
      expect(fixture.nativeElement.textContent).toContain('aaaaa-bbbbb');
      expect(JSON.parse(localStorage.getItem('current_user')!).second_facteur.actif).toBeTrue();

      composant.terminer();
      expect(composant.codesSecours).toEqual([]);
      expect(composant.ecran).toBe('etat');
    });

    it('un code faux laisse sur le QR code avec le message du serveur', () => {
      monter();
      http.expectOne(`${api}/second-facteur/`).flush(ETAT);
      composant.motDePasse = 'secret';
      composant.preparer();
      http.expectOne(`${api}/second-facteur/preparer/`).flush(PREPARATION);
      composant.code = '000000';
      composant.confirmer();
      http.expectOne(`${api}/second-facteur/confirmer/`).flush(
        { detail: 'Code incorrect. Vérifiez l\'heure de votre téléphone et réessayez.' },
        { status: 400, statusText: 'Bad Request' });
      expect(composant.ecran).toBe('installer');
      expect(composant.erreur).toContain('heure de votre téléphone');
    });

    it('retirer le code demande un code, et dit à un compte à pouvoir de réactiver', () => {
      monter();
      http.expectOne(`${api}/second-facteur/`).flush({ ...ETAT, actif: true, date_limite: null, codes_secours_restants: 9 });
      composant.demander('retirer');
      composant.code = '123456';
      composant.valider();
      const requete = http.expectOne(`${api}/second-facteur/retirer/`);
      expect(requete.request.body.code).toBe('123456');
      requete.flush({ etat: { ...ETAT, bloquant: true } });
      expect(composant.etat!.actif).toBeFalse();
      expect(composant.message).toContain('activez-en un nouveau');
    });
  });

  describe("quand l'activation est devenue obligatoire", () => {
    beforeEach(() => {
      // La connexion vient d'être refusée avec de quoi activer.
      auth.login('maire@exemple.test', 'secret').subscribe({ error: () => undefined });
      http.expectOne(`${api}/token/`).flush(
        { code: 'SECOND_FACTEUR_A_ACTIVER', detail: 'Activez-le.', jeton_enrolement: 'jeton-activation' },
        { status: 403, statusText: 'Forbidden' });
    });

    it("prépare tout de suite, sans redemander le mot de passe, et ouvre la session à l'activation", () => {
      monter();
      const preparation = http.expectOne(`${api}/second-facteur/preparer/`);
      expect(preparation.request.body.jeton_enrolement).toBe('jeton-activation');
      preparation.flush(PREPARATION);
      expect(composant.obligatoire).toBeTrue();

      composant.code = '123456';
      composant.confirmer();
      const confirmation = http.expectOne(`${api}/second-facteur/confirmer/`);
      expect(confirmation.request.body.jeton_enrolement).toBe('jeton-activation');
      confirmation.flush({
        codes_secours: ['aaaaa-bbbbb'], etat: { ...ETAT, actif: true },
        session: { access: 'acces', refresh: 'rafraichissement', user: { id: 'u' }, appareil: 'appareil-9' },
      });
      expect(localStorage.getItem('access_token')).toBe('acces');
      expect(localStorage.getItem('appareil_connu')).toBe('appareil-9');
      expect(auth.doitActiverSonCode()).toBeFalse();

      composant.terminer();
      expect(router.navigateByUrl).toHaveBeenCalledWith('/accueil');
    });

    it("dit de se reconnecter quand le délai d'activation est écoulé", () => {
      monter();
      http.expectOne(`${api}/second-facteur/preparer/`).flush(
        { detail: 'Session expirée. Reconnectez-vous.' }, { status: 401, statusText: 'Unauthorized' });
      fixture.detectChanges();
      expect(composant.erreur).toContain('Reconnectez-vous');
      expect(fixture.nativeElement.querySelector('.qr')).toBeNull();
    });
  });
});
