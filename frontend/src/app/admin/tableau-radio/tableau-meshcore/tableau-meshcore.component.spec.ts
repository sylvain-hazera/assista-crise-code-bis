import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { TableauMeshCoreComponent } from './tableau-meshcore.component';
import { TableauMeshCore } from './tableau-meshcore.service';

const TABLEAU: TableauMeshCore = {
  fenetre: '24h', calcule_le: '2026-11-23T14:00:00Z',
  trafic: {
    total: 12345, pas_heures: 1,
    par_type: [{ type: 'REQ', trames: 10000 }, { type: 'ADVERT', trames: 2345 }],
    courbe: [{ debut: '2026-11-23T12:00:00Z', trames: 5000 }, { debut: '2026-11-23T13:00:00Z', trames: 7345 }],
    recepteurs: [{ pubkey: 'ab'.repeat(32), nom: 'Obs Porge', trames: 12345, derniere_heure: null }],
  },
  liaisons: { reception_directe: 4332, chemins: 30034, voisinage: 0, emetteurs_entendus: 900, recepteurs: 155 },
  relais_publics: { repeteurs: 2400, repeteurs_vus: 600, rooms: 137, instances: ['meshstats.exemple'], derniere_import: null, plus_utiles: [] },
  observateurs: [{ pubkey: 'ab'.repeat(32), nom: 'Obs Porge', iata: 'BOD', recu_le: '2026-11-23T13:55:00Z', silencieux: false,
                   mesures: { battery_mv: 4012, noise_floor: -112, uptime_secs: 90061 }, autres_mesures: 2, trames: 12345 }],
  sources: [{ nom: 'Broker public', type: 'MQTT', actif: true, etat: 'CONNECTE', derniere_connexion: null }],
};

describe('TableauMeshCoreComponent', () => {
  it('affiche trafic, liaisons et état des observateurs, et change de période', () => {
    TestBed.configureTestingModule({ imports: [TableauMeshCoreComponent], providers: [provideHttpClient(), provideHttpClientTesting()] });
    const http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(TableauMeshCoreComponent);
    fixture.detectChanges();
    http.expectOne(r => r.url.endsWith('/tableau-radio-meshcore/') && r.params.get('fenetre') === '24h').flush(TABLEAU);
    fixture.detectChanges();
    const texte = (fixture.nativeElement as HTMLElement).textContent || '';
    expect(texte).toContain('requêtes');
    expect(texte).toContain('Obs Porge');
    expect(texte).toContain('4.01 V');
    expect(texte).toContain('-112 dBm');
    expect(texte).toContain('1 j 1 h');
    expect(fixture.componentInstance.hauteur(7345)).toBe(100);
    fixture.componentInstance.choisir('7j');
    http.expectOne(r => r.params.get('fenetre') === '7j').flush(TABLEAU);
    http.verify();
  });
});
