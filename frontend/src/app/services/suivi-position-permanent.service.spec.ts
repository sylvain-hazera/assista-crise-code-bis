import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

import { SuiviPositionPermanentService } from './suivi-position-permanent.service';

/** Ce service appelait `watchPosition` depuis `AppComponent.ngOnInit`, donc à CHAQUE chargement
 * de page et pour tout visiteur. L'invite de permission surgissait sans geste — et sur iOS un
 * refus est définitif pour tout le site, ce qui condamnait ensuite toutes les autres
 * utilisations de la position. Correction du 07/11/2026. */
describe('SuiviPositionPermanentService', () => {
  let service: SuiviPositionPermanentService;

  beforeEach(() => {
    localStorage.removeItem('suiviPositionPermanentDesactive');
    localStorage.removeItem('suiviPositionPermanentConsenti');
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(SuiviPositionPermanentService);
  });

  afterEach(() => {
    service.desactiver();
    localStorage.removeItem('suiviPositionPermanentDesactive');
    localStorage.removeItem('suiviPositionPermanentConsenti');
  });

  function permission(etat: PermissionState | null) {
    const permissions = (navigator as any).permissions;
    if (etat === null) {
      spyOn(permissions, 'query').and.rejectWith(new Error('nom inconnu'));
    } else {
      spyOn(permissions, 'query').and.resolveTo({ state: etat } as any);
    }
  }

  it('ne démarre pas le suivi sans accord explicite', async () => {
    // LE test : un visiteur qui n'a rien demandé ne doit voir aucune invite.
    const watch = spyOn(navigator.geolocation, 'watchPosition');
    permission('prompt');

    await service.demarrerSiConsentement();
    expect(watch).not.toHaveBeenCalled();
  });

  it('ne démarre pas non plus quand le navigateur ne sait pas dire l’état', async () => {
    const watch = spyOn(navigator.geolocation, 'watchPosition');
    permission(null);

    await service.demarrerSiConsentement();
    expect(watch).not.toHaveBeenCalled();
  });

  it('reprend le suivi quand l’utilisateur l’avait activé lui-même', async () => {
    const watch = spyOn(navigator.geolocation, 'watchPosition').and.returnValue(1);
    service.activer();                       // geste utilisateur : consentement enregistré
    expect(watch).toHaveBeenCalledTimes(1);

    service.desactiver();
    localStorage.setItem('suiviPositionPermanentConsenti', 'true');
    localStorage.removeItem('suiviPositionPermanentDesactive');

    await service.demarrerSiConsentement();
    expect(watch).toHaveBeenCalledTimes(2);
  });

  it('reprend sans invite pour un compte d’avant la correction, si c’est déjà autorisé', async () => {
    // Sinon un intervenant déjà suivi aujourd'hui s'arrêterait de l'être en silence.
    const watch = spyOn(navigator.geolocation, 'watchPosition').and.returnValue(1);
    permission('granted');

    await service.demarrerSiConsentement();
    expect(watch).toHaveBeenCalled();
  });

  it('un refus explicite reste respecté', async () => {
    const watch = spyOn(navigator.geolocation, 'watchPosition');
    permission('granted');
    localStorage.setItem('suiviPositionPermanentDesactive', 'true');

    await service.demarrerSiConsentement();
    expect(watch).not.toHaveBeenCalled();
  });

  it('désactiver retire le consentement, pas seulement le suivi', () => {
    // Sans ça, le prochain chargement de page relancerait le suivi que l'utilisateur vient
    // d'arrêter.
    spyOn(navigator.geolocation, 'watchPosition').and.returnValue(1);
    service.activer();
    expect(service.consentementExplicite).toBeTrue();

    service.desactiver();
    expect(service.consentementExplicite).toBeFalse();
    expect(service.desactiveExplicitement).toBeTrue();
  });

  it('n’économise pas la précision : le suivi n’a pas besoin du GPS fin', () => {
    // enableHighAccuracy faux et maximumAge généreux : un suivi continu en haute précision
    // vide la batterie d'un intervenant sur le terrain.
    let options: PositionOptions | undefined;
    spyOn(navigator.geolocation, 'watchPosition').and.callFake(
      (_s: any, _e: any, opts?: PositionOptions) => { options = opts; return 1; });
    service.activer();
    expect(options?.enableHighAccuracy).toBeFalse();
    expect(options?.maximumAge).toBeGreaterThan(0);
  });
});

describe('SuiviPositionPermanentService — stockage indisponible', () => {
  /** Safari en navigation privée, ou avec blocage total des cookies, fait LEVER
   * `localStorage`. Comme ce service est appelé depuis `AppComponent.ngOnInit`, une exception
   * y empêchait l'initialisation de toute l'application — pour une simple préférence. */
  it('ne fait pas tomber le démarrage de l’application', async () => {
    spyOn(localStorage, 'getItem').and.throwError('SecurityError');
    spyOn(navigator.geolocation, 'watchPosition');
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const service = TestBed.inject(SuiviPositionPermanentService);

    await expectAsync(service.demarrerSiConsentement()).toBeResolved();
  });
});
