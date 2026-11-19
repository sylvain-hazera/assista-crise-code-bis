import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { BrokersMeshcoreComponent } from './brokers-meshcore.component';
import { environment } from '../../../environments/environment';

const URL = `${environment.apiUrl}/sources-observateurs-meshcore/`;
const SOURCE = {
  id: 's1', nom: 'Régional BOD', broker_host: 'mqtt.exemple.fr', broker_port: 1883, mqtt_username: 'mm',
  mqtt_use_tls: false, mqtt_transport: 'tcp', mqtt_ws_chemin: '/mqtt', filtre_topic: 'meshcore/BOD/#',
  actif: true, derniere_connexion: null, dernier_etat: 'CONNECTE', derniere_erreur: null,
};

describe('BrokersMeshcoreComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [BrokersMeshcoreComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  function ouvrir() {
    const f = TestBed.createComponent(BrokersMeshcoreComponent);
    f.detectChanges();
    http.expectOne(URL).flush([SOURCE]);
    f.detectChanges();
    return f;
  }

  it('liste les brokers et leur état', () => {
    const f = ouvrir();
    const texte = f.nativeElement.textContent as string;
    expect(texte).toContain('Régional BOD');
    expect(texte).toContain('mqtt://mqtt.exemple.fr:1883');
    expect(texte).toContain('connecté');
  });

  it('ne renvoie pas un mot de passe vide en modification', () => {
    const f = ouvrir();
    f.componentInstance.editer(SOURCE as never);
    f.componentInstance.enregistrer();
    const req = http.expectOne(`${URL}s1/`);
    expect(req.request.method).toBe('PATCH');
    expect('mqtt_password' in req.request.body).toBeFalse();
    req.flush(SOURCE);
    http.expectOne(URL).flush([SOURCE]);
  });

  it('le WebSocket propose le port 443 et le chiffrement', () => {
    const f = ouvrir();
    f.componentInstance.nouveau();
    f.componentInstance.brouillon.mqtt_transport = 'websockets';
    f.componentInstance.changerTransport();
    expect(f.componentInstance.brouillon.broker_port).toBe(443);
    expect(f.componentInstance.brouillon.mqtt_use_tls).toBeTrue();
  });

  it('dit clairement un refus de droits', () => {
    const f = ouvrir();
    f.componentInstance.nouveau();
    f.componentInstance.enregistrer();
    http.expectOne(URL).flush({}, { status: 403, statusText: 'Forbidden' });
    expect(f.componentInstance.erreur).toContain('administrateur');
  });
});
