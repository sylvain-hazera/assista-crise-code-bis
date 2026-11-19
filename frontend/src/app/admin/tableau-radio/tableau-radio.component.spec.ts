import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { TableauRadioComponent } from './tableau-radio.component';
import { environment } from '../../../environments/environment';
import { TableauRadio } from '../../shared/models/tableau-radio.model';
import { CartePaquetsComponent } from '../../shared/components/common/carte-paquets/carte-paquets.component';

const TABLEAU: TableauRadio = {
  fenetre: '6h', pas_s: 600, debut: new Date(Date.now() - 6 * 3600_000).toISOString(),
  passerelle: { id: 'gw1', nom: 'Mairie', node_num: 0xd001 },
  series: {
    occupation_canal: [{ t: new Date().toISOString(), v: 12 }], temps_antenne_tx: [], batterie: [],
    paquets_tx: [], paquets_rx: [], paquets_recus_par_heure: [],
  },
  types_paquets: [{ type: 'POSITION_APP', nombre: 7 }, { type: 'TEXT_MESSAGE_APP', nombre: 5 }],
  noeuds: [
    { node_num: 1, id: '!00000001', nom: 'Relais Pilat', nom_court: 'PILA', materiel: 'RAK4631',
      batterie: 64, tension: 3.9, sauts: 1, snr: 6.25, dernier_entendu: new Date().toISOString(), position: true },
    { node_num: 2, id: '!00000002', nom: 'Caserne', nom_court: 'CAS', materiel: '',
      batterie: null, tension: null, sauts: 3, snr: null, dernier_entendu: null, position: false },
  ],
  traceroutes: [{
    cible: 1, cible_nom: 'Relais Pilat', date: new Date().toISOString(),
    aller: [{ node_num: 0xd001, nom: 'Mairie' }, { node_num: 1, nom: 'Relais Pilat' }], snr_aller: [6.25],
    retour: [], snr_retour: [],
  }],
};

describe('TableauRadioComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [TableauRadioComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  function ouvrir() {
    const f = TestBed.createComponent(TableauRadioComponent);
    f.detectChanges();
    http.expectOne(`${environment.apiUrl}/compagnons-meshtastic/`).flush([{ id: 'gw1', nom: 'Mairie' }]);
    http.expectOne(r => r.url === `${environment.apiUrl}/compagnons-meshtastic/gw1/tableau/`
      && r.params.get('fenetre') === '6h').flush(TABLEAU);
    f.detectChanges();
    return f;
  }

  it('affiche les nœuds, le traceroute et la répartition du trafic', () => {
    const f = ouvrir();
    const texte = f.nativeElement.textContent as string;
    expect(texte).toContain('Relais Pilat');
    expect(texte).toContain('+6.3 dB');
    expect(texte).toContain('64 %');
    expect(texte).toContain('relayé');
    expect(f.nativeElement.querySelectorAll('app-serie-compacte').length).toBe(6);
    expect(f.nativeElement.querySelectorAll('app-carte-paquets rect').length).toBe(2);
    f.destroy();
  });

  it('filtre et trie les nœuds', () => {
    const f = ouvrir();
    const c = f.componentInstance;
    c.tri = 'sauts';
    expect(c.noeudsAffiches.map(n => n.nom)).toEqual(['Relais Pilat', 'Caserne']);
    c.filtre = 'cas';
    expect(c.noeudsAffiches.map(n => n.nom)).toEqual(['Caserne']);
    f.destroy();
  });

  it('change de fenêtre', () => {
    const f = ouvrir();
    f.componentInstance.choisirFenetre('24h');
    http.expectOne(r => r.url.endsWith('/gw1/tableau/') && r.params.get('fenetre') === '24h').flush(TABLEAU);
    f.destroy();
  });

  it('lance un traceroute par une tâche d’administration', () => {
    const f = ouvrir();
    f.componentInstance.lancerTraceroute(TABLEAU.noeuds[0]);
    const req = http.expectOne(`${environment.apiUrl}/taches-admin-meshtastic/`);
    expect(req.request.body).toEqual(jasmine.objectContaining({ type_tache: 'TRACEROUTE', node_num_cible: 1, compagnon: 'gw1' }));
    req.flush({});
    expect(f.componentInstance.traceroutesDemandes.has(1)).toBeTrue();
    f.destroy();
  });
});

describe('CartePaquetsComponent.squarifier', () => {
  it('couvre exactement la surface, sans débordement', () => {
    const aires = [50, 25, 15, 10].map(p => p * 600 * 260 / 100);
    const r = CartePaquetsComponent.squarifier(aires, 0, 0, 600, 260);
    const total = r.reduce((s, b) => s + b.l * b.h, 0);
    expect(Math.round(total)).toBe(600 * 260);
    for (const b of r) {
      expect(b.x + b.l).toBeLessThanOrEqual(600.001);
      expect(b.y + b.h).toBeLessThanOrEqual(260.001);
    }
  });
});

describe('TableauRadioComponent — historique d’un nœud', () => {
  it('ouvre puis referme l’historique', () => {
    TestBed.configureTestingModule({
      imports: [TableauRadioComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    const http = TestBed.inject(HttpTestingController);
    const f = TestBed.createComponent(TableauRadioComponent);
    f.detectChanges();
    http.expectOne(`${environment.apiUrl}/compagnons-meshtastic/`).flush([{ id: 'gw1', nom: 'Mairie' }]);
    http.expectOne(r => r.url.endsWith('/gw1/tableau/')).flush(TABLEAU);
    f.detectChanges();
    f.componentInstance.suivre(TABLEAU.noeuds[0]);
    http.expectOne(r => r.url.endsWith('/gw1/tableau/') && r.params.get('noeud') === '1'
      && r.params.get('fenetre') === '24h').flush({
      node_num: 1, fenetre: '24h', pas_s: 1800, debut: new Date(Date.now() - 86400_000).toISOString(), nombre_mesures: 1,
      series: { batterie: [{ t: new Date().toISOString(), v: 70 }], tension: [], occupation_canal: [], temps_antenne_tx: [] },
    });
    f.detectChanges();
    expect(f.nativeElement.textContent).toContain('Historique de Relais Pilat');
    f.componentInstance.suivre(TABLEAU.noeuds[0]);
    expect(f.componentInstance.historique).toBeNull();
    f.destroy();
  });
});
