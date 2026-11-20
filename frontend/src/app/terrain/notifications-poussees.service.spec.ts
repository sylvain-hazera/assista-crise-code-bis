import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { fournisseursDeTest } from '../testing/test-providers';
import { environment } from '../../environments/environment';
import { NotificationsPousseesService } from './notifications-poussees.service';

describe('NotificationsPousseesService', () => {
  let service: NotificationsPousseesService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    service = TestBed.inject(NotificationsPousseesService);
    http = TestBed.inject(HttpTestingController);
  });

  it('convertit la clé du serveur (base64url) en octets', () => {
    const octets = NotificationsPousseesService.octets('BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8');
    expect(octets.length).toBe(65);
    expect(octets[0]).toBe(4);
  });

  it('refusées : le dit, et le serveur oublie l\'abonnement', async () => {
    spyOnProperty(Notification, 'permission', 'get').and.returnValue('denied');
    await service.actualiser();
    expect(service.etat()).toBe('refusees');
    const requete = http.expectOne(`${environment.apiUrl}/mon-appareil/`);
    expect(requete.request.body.abonnement_push).toBe('');
    expect(requete.request.body.notifications_autorisees).toBeFalse();
    requete.flush({});
  });

  it('activer : demande l\'accord, s\'abonne avec la clé du serveur et confie l\'abonnement', async () => {
    spyOn(Notification, 'requestPermission').and.resolveTo('granted');
    const abonnement = { toJSON: () => ({ endpoint: 'https://web.push.apple.com/x', keys: { p256dh: 'p', auth: 'a' } }) };
    const pushManager = { getSubscription: jasmine.createSpy().and.resolveTo(null), subscribe: jasmine.createSpy().and.resolveTo(abonnement) };
    spyOnProperty(navigator.serviceWorker, 'ready', 'get').and.returnValue(Promise.resolve({ pushManager } as never));

    const fini = service.activer();
    await Promise.resolve(); await Promise.resolve();
    http.expectOne(`${environment.apiUrl}/pwa/cle-push/`).flush({ cle: 'BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8' });
    expect(await fini).toBeTrue();
    expect(pushManager.subscribe.calls.mostRecent().args[0].userVisibleOnly).toBeTrue();
    const presentation = http.expectOne(`${environment.apiUrl}/mon-appareil/`);
    expect(presentation.request.body.abonnement_push.endpoint).toBe('https://web.push.apple.com/x');
    expect(presentation.request.body.notifications_autorisees).toBeTrue();
    presentation.flush({});
    expect(service.etat()).toBe('actives');
  });
});
