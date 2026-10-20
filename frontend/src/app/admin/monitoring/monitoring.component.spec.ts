import { ComponentFixture, TestBed, fakeAsync, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter, Router } from '@angular/router';

import { MonitoringComponent, ONGLETS_SUPERVISION } from './monitoring.component';
import { environment } from '../../../environments/environment';

const URL_JETON = `${environment.apiUrl}/monitoring/grafana-token/`;

describe('MonitoringComponent', () => {
  let component: MonitoringComponent;
  let fixture: ComponentFixture<MonitoringComponent>;
  let http: HttpTestingController;

  function creer(onglet: string | null = null): void {
    TestBed.configureTestingModule({
      imports: [MonitoringComponent],
      providers: [
        provideHttpClient(), provideHttpClientTesting(), provideRouter([]),
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: convertToParamMap(onglet ? { onglet } : {}) } } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(MonitoringComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  }

  function iframeSrc(): string {
    return fixture.nativeElement.querySelector('iframe')?.getAttribute('src') ?? '';
  }

  afterEach(() => http.verify());

  it('demande un jeton puis affiche le tableau de l\'onglet en kiosque', () => {
    creer();
    const req = http.expectOne(URL_JETON);
    expect(req.request.method).toBe('POST');
    req.flush({ token: 'abc', expires_in: 3600 });
    fixture.detectChanges();
    expect(iframeSrc()).toBe(`${environment.grafanaUrl}/d/assista-overview/?orgId=1&theme=light&var-monitoring=monitoring&auth_token=abc&kiosk`);
    component.ngOnDestroy();
  });

  it('un onglet par tableau ; changer d\'onglet change le tableau et l\'URL de la page', () => {
    creer();
    http.expectOne(URL_JETON).flush({ token: 'abc', expires_in: 3600 });
    const navigate = spyOn(TestBed.inject(Router), 'navigate');
    fixture.detectChanges();

    const boutons: HTMLButtonElement[] = Array.from(fixture.nativeElement.querySelectorAll('.onglet'));
    expect(boutons.map(b => b.textContent!.trim())).toEqual(ONGLETS_SUPERVISION.map(o => `${o.icon} ${o.label}`));
    boutons[3].click();
    fixture.detectChanges();

    expect(iframeSrc()).toContain('/d/assista-infra/');
    expect(navigate.calls.mostRecent().args[1]?.queryParams).toEqual({ onglet: 'infra' });
    component.ngOnDestroy();
  });

  it('conteneurs de monitoring masqués par défaut, affichables sur les tableaux qui les ont', () => {
    creer('infra');
    http.expectOne(URL_JETON).flush({ token: 'abc', expires_in: 3600 });
    fixture.detectChanges();
    expect(iframeSrc()).toContain('var-monitoring=monitoring');

    const option: HTMLInputElement = fixture.nativeElement.querySelector('.option input');
    option.checked = true;
    option.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(iframeSrc()).toContain('var-monitoring=aucun');

    component.choisir(ONGLETS_SUPERVISION.find(o => o.id === 'metier')!);
    fixture.detectChanges();
    expect(iframeSrc()).not.toContain('var-monitoring');
    expect(fixture.nativeElement.querySelector('.option')).toBeNull();
    component.ngOnDestroy();
  });

  it('ouvre l\'onglet demandé dans l\'URL', () => {
    creer('metier');
    http.expectOne(URL_JETON).flush({ token: 'abc', expires_in: 3600 });
    fixture.detectChanges();
    expect(iframeSrc()).toContain('/d/assista-metier/');
    component.ngOnDestroy();
  });

  it('renouvelle le jeton avant son expiration', fakeAsync(() => {
    creer();
    http.expectOne(URL_JETON).flush({ token: 'ancien', expires_in: 3600 });
    tick((3600 - 300) * 1000);
    http.expectOne(URL_JETON).flush({ token: 'neuf', expires_in: 3600 });
    fixture.detectChanges();
    expect(iframeSrc()).toContain('auth_token=neuf');
    component.ngOnDestroy();
  }));

  it('refus du backend : message, pas d\'iframe', () => {
    creer();
    http.expectOne(URL_JETON).flush({}, { status: 403, statusText: 'Forbidden' });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('iframe')).toBeNull();
    expect(fixture.nativeElement.querySelector('.erreur').textContent).toContain('réservée aux administrateurs');
  });

  it('backend injoignable : rappelle l\'accès de secours par tunnel SSH', () => {
    creer();
    http.expectOne(URL_JETON).flush({}, { status: 502, statusText: 'Bad Gateway' });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.erreur').textContent).toContain('ssh -L 3000:localhost:3000');
  });
});
