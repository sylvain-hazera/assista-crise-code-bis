import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { Router } from '@angular/router';

import { LoginComponent } from './login.component';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { environment } from '../../../../environments/environment';

describe('LoginComponent', () => {
  let component: LoginComponent;
  let fixture: ComponentFixture<LoginComponent>;
  let http: HttpTestingController;
  let router: Router;
  const api = environment.apiUrl;

  beforeEach(async () => {
    localStorage.clear();
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [LoginComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(LoginComponent);
    component = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    router = TestBed.inject(Router);
    spyOn(router, 'navigate').and.resolveTo(true);
    spyOn(router, 'navigateByUrl').and.resolveTo(true);
    fixture.detectChanges();
  });

  afterEach(() => localStorage.clear());

  function saisirAdresse(etape: 'code' | 'mot_de_passe'): void {
    component.loginForm.patchValue({ email: 'maire@exemple.test' });
    component.onSubmit();
    http.expectOne(`${api}/connexion/debut/`).flush({ etape });
  }

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it("commence par l'adresse seule, sans montrer le mot de passe", () => {
    expect(component.etape).toBe('adresse');
    expect(fixture.nativeElement.querySelector('#password')).toBeNull();
    expect(fixture.nativeElement.querySelector('#code')).toBeNull();
  });

  it("un compte sans code de sécurité passe de l'adresse au mot de passe", () => {
    saisirAdresse('mot_de_passe');
    expect(component.etape).toBe('mot_de_passe');
    component.loginForm.patchValue({ password: 'secret' });
    component.onSubmit();
    const requete = http.expectOne(`${api}/token/`);
    expect(requete.request.body.jeton_etape).toBe('');
    requete.flush({ access: 'a', refresh: 'r', user: { id: 'u' }, appareil: 'appareil-1' });
    expect(router.navigateByUrl).toHaveBeenCalledWith('/accueil');
    expect(localStorage.getItem('appareil_connu')).toBe('appareil-1');
  });

  it('un compte protégé donne son code AVANT son mot de passe, et le jeton accompagne le mot de passe', () => {
    saisirAdresse('code');
    expect(component.etape).toBe('code');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('#password')).toBeNull();

    component.loginForm.patchValue({ code: '123456' });
    component.onSubmit();
    http.expectOne(`${api}/connexion/code/`).flush({ jeton_etape: 'jeton-etape' });
    expect(component.etape).toBe('mot_de_passe');

    component.loginForm.patchValue({ password: 'secret' });
    component.onSubmit();
    const requete = http.expectOne(`${api}/token/`);
    expect(requete.request.body.jeton_etape).toBe('jeton-etape');
    requete.flush({ access: 'a', refresh: 'r', user: { id: 'u' } });
  });

  it('« renvoyer le code » affiche la réponse du serveur, identique pour toute adresse', () => {
    saisirAdresse('code');
    component.renvoyerCode();
    const requete = http.expectOne(`${api}/connexion/envoyer-code/`);
    expect(requete.request.body.email).toBe('maire@exemple.test');
    requete.flush({ detail: 'Si un compte protégé existe à cette adresse, un code vient de lui être envoyé par e-mail.' });
    expect(component.messageEnvoi).toContain('vient de lui être envoyé');
    component.recommencer();
    expect(component.messageEnvoi).toBe('');
  });

  it("un code faux laisse sur l'étape du code et vide le champ", () => {
    saisirAdresse('code');
    component.loginForm.patchValue({ code: '000000' });
    component.onSubmit();
    http.expectOne(`${api}/connexion/code/`).flush({ detail: 'Code incorrect.' }, { status: 401, statusText: 'Unauthorized' });
    expect(component.etape).toBe('code');
    expect(component.loginForm.value.code).toBe('');
    expect(component.errorMessage).toBe('Code incorrect.');
  });

  it("affiche le délai d'attente annoncé par le serveur", () => {
    saisirAdresse('mot_de_passe');
    component.loginForm.patchValue({ password: 'faux' });
    component.onSubmit();
    http.expectOne(`${api}/token/`).flush(
      { code: 'TROP_D_ESSAIS', detail: "Trop d'essais. Réessayez dans 30 secondes.", attendre: '30' },
      { status: 429, statusText: 'Too Many Requests' });
    expect(component.errorMessage).toContain('30 secondes');
  });

  it("emmène activer le code quand le délai d'activation est passé", () => {
    saisirAdresse('mot_de_passe');
    component.loginForm.patchValue({ password: 'secret' });
    component.onSubmit();
    http.expectOne(`${api}/token/`).flush(
      { code: 'SECOND_FACTEUR_A_ACTIVER', detail: 'Activez-le.', jeton_enrolement: 'jeton' },
      { status: 403, statusText: 'Forbidden' });
    expect(router.navigate).toHaveBeenCalledWith(['/securite-du-compte'], { queryParams: { returnUrl: '/accueil' } });
  });

  it('« ce n\'est pas la bonne adresse » ramène au début et oublie le reste', () => {
    saisirAdresse('code');
    component.loginForm.patchValue({ code: '123456' });
    component.recommencer();
    expect(component.etape).toBe('adresse');
    expect(component.loginForm.value.code).toBe('');
  });

  it("un serveur qui ne connaît pas les étapes (ancien satellite) mène au mot de passe", () => {
    component.loginForm.patchValue({ email: 'maire@exemple.test' });
    component.onSubmit();
    http.expectOne(`${api}/connexion/debut/`).flush('', { status: 404, statusText: 'Not Found' });
    expect(component.etape).toBe('mot_de_passe');
  });
});
