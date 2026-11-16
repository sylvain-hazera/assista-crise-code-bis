import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { SelecteurPerimetreComponent } from './selecteur-perimetre.component';
import { AuthService } from '../../../../auth/services/auth.service';
import { authInterceptor } from '../../../../auth/interceptor/auth';
import { EtatPerimetre, PerimetreService } from '../../../../services/perimetre.service';
import { UserRole } from '../../../../shared/models/user.model';
import { environment } from '../../../../../environments/environment';

/** Périmètre de l'administrateur (15/11/2026) : « je vois des institutions qui ne sont pas les
 * miennes ». Ce qui est vérifié : le sélecteur n'existe que pour un administrateur, il propose
 * sa propre institution d'abord, et le choix part bien avec chaque requête vers notre serveur. */
describe('SelecteurPerimetreComponent', () => {
  const api = environment.apiUrl;
  const ETAT: EtatPerimetre = {
    administrateur: true, mode: 'INSTITUTION',
    institution: { id: 'ici', nom: 'Mairie de Saint-Étienne' },
    mienne: { id: 'ici', nom: 'Mairie de Saint-Étienne' },
    institutions: [
      { id: 'ici', nom: 'Mairie de Saint-Étienne', type_libelle: 'Mairie' },
      { id: 'ailleurs', nom: 'Mairie de Lille', type_libelle: 'Mairie' },
    ],
  };
  let fixture: ComponentFixture<SelecteurPerimetreComponent>;
  let component: SelecteurPerimetreComponent;
  let http: HttpTestingController;
  let role: UserRole | null;

  function creer(etat: EtatPerimetre | null = ETAT) {
    fixture = TestBed.createComponent(SelecteurPerimetreComponent);
    component = fixture.componentInstance;
    spyOn(component, 'recharger');
    fixture.detectChanges();
    if (etat) {
      http.expectOne(`${api}/me/perimetre/`).flush(etat);
      fixture.detectChanges();
    }
  }

  beforeEach(() => {
    localStorage.removeItem(PerimetreService.CLE);
    role = UserRole.ADMIN;
    TestBed.configureTestingModule({
      imports: [SelecteurPerimetreComponent],
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])), provideHttpClientTesting(),
        { provide: AuthService, useValue: { getEffectiveRole: () => role, getToken: () => 'jeton', getEnvironment: () => 'PROD' } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => { http.verify(); localStorage.removeItem(PerimetreService.CLE); });

  it('propose d’abord sa propre institution, puis toute la plateforme, puis les autres', () => {
    creer();
    const options: HTMLOptionElement[] = Array.from(fixture.nativeElement.querySelectorAll('option'));

    expect(options.map(o => o.textContent!.trim())).toEqual(
      ['Mon institution — Mairie de Saint-Étienne', 'Toute la plateforme', 'Mairie de Lille']);
    expect(component.choix).toBe('MIENNE');
    expect(fixture.nativeElement.querySelector('.perimetre').classList).not.toContain('ailleurs');
  });

  it('n’existe pas pour un compte qui n’est pas administrateur, et ne demande rien', () => {
    role = UserRole.LOCAL_AUTH;
    creer(null);

    expect(fixture.nativeElement.querySelector('.perimetre')).toBeNull();
  });

  it('retient le choix et recharge la page', () => {
    creer();
    component.choisir('ailleurs');

    expect(localStorage.getItem(PerimetreService.CLE)).toBe('ailleurs');
    expect(component.recharger).toHaveBeenCalled();
  });

  it('ne recharge pas pour rien quand on rechoisit le même périmètre', () => {
    creer();
    component.choisir('MIENNE');

    expect(component.recharger).not.toHaveBeenCalled();
  });

  it('se signale quand on ne regarde pas son institution', () => {
    localStorage.setItem(PerimetreService.CLE, 'TOUT');
    creer({ ...ETAT, mode: 'TOUT', institution: null });

    expect(fixture.nativeElement.querySelector('.perimetre').classList).toContain('ailleurs');
  });

  it('revient à sa propre institution quand le choix gardé ne désigne plus rien', () => {
    localStorage.setItem(PerimetreService.CLE, 'institution-supprimee');
    creer({ ...ETAT, mode: 'INVALIDE', institution: null });

    expect(localStorage.getItem(PerimetreService.CLE)).toBe('MIENNE');
    expect(component.recharger).toHaveBeenCalled();
  });

  it('affiche « toute la plateforme » pour un administrateur sans institution', () => {
    creer({ ...ETAT, mode: 'TOUT', institution: null, mienne: null });

    expect(component.choix).toBe('TOUT');
    expect(fixture.nativeElement.querySelector('option').textContent.trim()).toBe('Toute la plateforme');
  });

  describe('le choix part avec chaque requête', () => {
    it('vers notre serveur, pour un administrateur', () => {
      localStorage.setItem(PerimetreService.CLE, 'ailleurs');
      TestBed.inject(HttpClient).get(`${api}/teams/`).subscribe();

      expect(http.expectOne(`${api}/teams/`).request.headers.get('X-Perimetre')).toBe('ailleurs');
    });

    it('avec « MIENNE » tant que rien n’a été choisi', () => {
      TestBed.inject(HttpClient).get(`${api}/missions/`).subscribe();

      expect(http.expectOne(`${api}/missions/`).request.headers.get('X-Perimetre')).toBe('MIENNE');
    });

    it('jamais pour un autre rôle, ni vers un service tiers', () => {
      TestBed.inject(HttpClient).get('https://data.geopf.fr/geocodage/search').subscribe();
      expect(http.expectOne('https://data.geopf.fr/geocodage/search').request.headers.has('X-Perimetre')).toBeFalse();

      role = UserRole.LOCAL_AUTH;
      localStorage.setItem(PerimetreService.CLE, 'TOUT');
      TestBed.inject(HttpClient).get(`${api}/teams/`).subscribe();
      expect(http.expectOne(`${api}/teams/`).request.headers.has('X-Perimetre')).toBeFalse();
    });
  });
});
