import { TestBed } from '@angular/core/testing';

import { GeolocationService } from './geolocation.service';
import { fournisseursDeTest } from '../testing/test-providers';

/** Le point sensible de ce service n'est pas le GPS, c'est l'INVITE de permission.
 *
 * Sur iOS, un refus est définitif pour tout le site : Safari ne repropose jamais. Dépenser
 * l'unique invite sur un usage opportuniste (biaiser une recherche d'adresse, centrer une carte
 * au chargement) condamnait donc tous les usages légitimes suivants — c'est le bug signalé le
 * 07/11/2026, « Safari bloque la géoloc ». */
describe('GeolocalisationService', () => {
  let service: GeolocationService;

  beforeEach(() => {
    localStorage.removeItem('userLocation');
    TestBed.configureTestingModule({ providers: fournisseursDeTest() });
    service = TestBed.inject(GeolocationService);
  });

  afterEach(() => localStorage.removeItem('userLocation'));

  it('should be created', () => {
    expect(service).toBeTruthy();
  });

  describe('positionSansInvite', () => {
    it('n’appelle pas le GPS quand la permission n’est pas déjà accordée', async () => {
      const gps = spyOn(navigator.geolocation, 'getCurrentPosition');
      spyOn(service, 'etatPermission').and.resolveTo('prompt');

      await expectAsync(service.positionSansInvite()).toBeResolvedTo(null);
      // LE test : aucune invite déclenchée par un usage opportuniste.
      expect(gps).not.toHaveBeenCalled();
    });

    it('n’appelle pas le GPS quand le navigateur ne sait pas dire l’état', async () => {
      // Safari < 16 n'a pas l'API Permissions : impossible de savoir si l'appel inviterait.
      // On s'abstient, puisque l'invite non sollicitée est précisément le problème.
      const gps = spyOn(navigator.geolocation, 'getCurrentPosition');
      spyOn(service, 'etatPermission').and.resolveTo(null);

      await expectAsync(service.positionSansInvite()).toBeResolvedTo(null);
      expect(gps).not.toHaveBeenCalled();
    });

    it('appelle le GPS quand la permission est déjà accordée', async () => {
      spyOn(service, 'etatPermission').and.resolveTo('granted');
      spyOn(navigator.geolocation, 'getCurrentPosition').and.callFake((succes: any) =>
        succes({ coords: { latitude: 45.43, longitude: 4.39 } }));

      const coords = await service.positionSansInvite();
      expect(coords).toEqual({ latitude: 45.43, longitude: 4.39 });
    });

    it('rend la position déjà connue sans rien demander', async () => {
      localStorage.setItem('userLocation', JSON.stringify({ latitude: 1, longitude: 2 }));
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({ providers: fournisseursDeTest() });
      const avecCache = TestBed.inject(GeolocationService);
      const gps = spyOn(navigator.geolocation, 'getCurrentPosition');

      await expectAsync(avecCache.positionSansInvite()).toBeResolvedTo({ latitude: 1, longitude: 2 });
      expect(gps).not.toHaveBeenCalled();
    });

    it('ne propage pas une erreur : un usage opportuniste n’est jamais bloquant', async () => {
      spyOn(service, 'etatPermission').and.resolveTo('granted');
      spyOn(navigator.geolocation, 'getCurrentPosition').and.callFake(
        (_s: any, echec: any) => echec({ code: 1, PERMISSION_DENIED: 1 }));

      await expectAsync(service.positionSansInvite()).toBeResolvedTo(null);
    });
  });

  describe('requestLocation', () => {
    it('demande un point récent plutôt qu’une mesure neuve, avec un délai tenable', async () => {
      // Sur iOS, le PREMIER point GPS demande couramment plus de dix secondes : un délai court
      // avec maximumAge à 0 échouait alors que le téléphone cherchait encore.
      let options: PositionOptions | undefined;
      spyOn(navigator.geolocation, 'getCurrentPosition').and.callFake(
        (succes: any, _e: any, opts?: PositionOptions) => {
          options = opts;
          succes({ coords: { latitude: 45, longitude: 4 } });
        });

      await service.requestLocation();
      expect(options?.timeout).toBeGreaterThanOrEqual(20000);
      expect(options?.maximumAge).toBeGreaterThan(0);
      expect(options?.enableHighAccuracy).toBeTrue();
    });

    it('sur iOS, un refus dit où rétablir l’autorisation', async () => {
      // Safari ne redemandera pas : un message qui ne dit pas où aller laisse l'utilisateur
      // conclure que l'application est cassée.
      spyOnProperty(navigator, 'userAgent').and.returnValue(
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15');
      spyOn(navigator.geolocation, 'getCurrentPosition').and.callFake(
        (_s: any, echec: any) => echec({ code: 1, PERMISSION_DENIED: 1 }));

      await expectAsync(service.requestLocation()).toBeRejectedWithError(/Réglages/);
    });

    it('ailleurs, le message reste générique', async () => {
      spyOnProperty(navigator, 'userAgent').and.returnValue(
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120');
      spyOn(navigator.geolocation, 'getCurrentPosition').and.callFake(
        (_s: any, echec: any) => echec({ code: 1, PERMISSION_DENIED: 1 }));

      await expectAsync(service.requestLocation()).toBeRejectedWithError(/Permission refusée/);
    });
  });
});
