import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { MeshtasticCompanionsComponent } from './meshtastic-companions.component';
import { environment } from '../../../environments/environment';
import { RoutageMeshtastic, RouteMeshtastic } from '../../shared/models/routage-meshtastic.model';

const API = environment.apiUrl;

function route(partiel: Partial<RouteMeshtastic>): RouteMeshtastic {
  return {
    node_num: 0x42, nom: 'Noeud', actif: true, dernier_advert: '2026-11-08T10:00:00Z',
    compagnon_id: 'c1', compagnon_nom: 'Gaulix', broker: 'mqtt.gaulix.fr:1883',
    passerelles: [], passerelles_a_nous: 0, sauts: null, chemin: [],
    relais_obligatoire: null, retour_prouve: false, hop_limit_suffisant: null,
    raison: 'raison', ...partiel,
  };
}

const ROUTAGE: RoutageMeshtastic = {
  routes: [
    route({
      node_num: 0x1111, nom: 'Direct', sauts: 1, hop_limit_suffisant: true, retour_prouve: true,
      passerelles: [{
        node_num: 0x1000, nom: 'Mairie', snr: -5, rssi: -110, nombre: 12,
        dernier_vu: '2026-11-08T10:00:00Z', nous: true, retour_prouve: true,
      }],
      passerelles_a_nous: 1, raison: 'Entendu directement par notre passerelle « Mairie ».',
    }),
    route({
      node_num: 0x2222, nom: 'Lointain', sauts: 4, hop_limit_suffisant: false,
      compagnon_nom: 'Local', relais_obligatoire: { node_num: 0x500, nom: 'Relais Pilat' },
      chemin: [{
        de: 0x2222, nom_de: 'Lointain', vers: 0x500, nom_vers: 'Relais Pilat', snr: 2,
        sources: ['VOISINAGE'], retour_prouve: false,
      }],
      raison: '4 sauts dépassent le hop_limit par défaut (3) : abandonné en route.',
    }),
    route({ node_num: 0x3333, nom: 'Muet', sauts: null, raison: "Aucune passerelle ne l'a entendu." }),
  ],
  fenetre_jours: 7, hop_limit_defaut: 3, hop_limit_max: 7,
  calcule_le: '2026-11-09T10:00:00Z',
};

const CONTACTS = [
  { id: 'a', compagnon: 'c1', node_num: 0x1111, long_name: 'Direct', hardware_model: 'TBEAM',
    public_key_hex: 'ab', dernier_advert: '2026-11-08T10:00:00Z', deja_associe: false },
  { id: 'b', compagnon: 'c1', node_num: 0x2222, long_name: 'Lointain', hardware_model: 'HELTEC',
    public_key_hex: '', dernier_advert: '2026-11-07T10:00:00Z', deja_associe: true },
  { id: 'c', compagnon: 'c1', node_num: 0x3333, long_name: 'Muet', hardware_model: null,
    public_key_hex: '', dernier_advert: null, deja_associe: false },
];

describe('MeshtasticCompanionsComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [MeshtasticCompanionsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function demarrer(contacts: any[] = CONTACTS, routage: RoutageMeshtastic = ROUTAGE) {
    const fixture = TestBed.createComponent(MeshtasticCompanionsComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/compagnons-meshtastic/`).flush([]);
    http.expectOne(`${API}/canaux-meshtastic/`).flush([]);
    http.expectOne(`${API}/noeuds-meshtastic/`).flush([]);
    http.expectOne(`${API}/contacts-meshtastic/`).flush(contacts);
    http.expectOne(`${API}/contacts-meshtastic/routage/`).flush(routage);
    http.expectOne(r => r.url === `${API}/users/`).flush([]);
    fixture.detectChanges();
    return fixture;
  }

  function lignes(fixture: any, table = 2): HTMLElement[] {
    // Les tableaux de la page dans l'ordre : companions, canaux, nœuds détectés, nœuds attribués.
    const tables = fixture.nativeElement.querySelectorAll('table.data-table');
    return Array.from(tables[table].querySelectorAll('tbody tr'));
  }

  it('demande le routage au chargement', () => {
    const fixture = demarrer();
    expect(fixture.componentInstance.routage?.fenetre_jours).toBe(7);
  });

  it('affiche AUSSI les nœuds déjà attribués', () => {
    // Avant, la page ne listait que les nœuds non attribués : les autres devenaient invisibles,
    // routage compris, alors que ce sont justement ceux qu'on cherche à joindre.
    const texte = lignes(demarrer()).map(l => l.textContent || '').join(' ');
    expect(texte).toContain('Lointain');
    expect(texte).toContain('Direct');
  });

  it('nomme la passerelle qui a entendu le nœud et son SNR', () => {
    const ligne = lignes(demarrer())[0].textContent || '';
    expect(ligne).toContain('Mairie');
    expect(ligne).toContain('-5');
  });

  it('nomme le companion par lequel émettre, pas un autre', () => {
    const texte = lignes(demarrer()).map(l => l.textContent || '');
    expect(texte.find(t => t.includes('Lointain'))).toContain('Local');
  });

  it('signale un nœud hors de portée au lieu de le dire à zéro saut', () => {
    const muette = lignes(demarrer()).find(l => (l.textContent || '').includes('Muet'))!;
    expect(muette.textContent).toContain('hors de portée');
  });

  it('signale le relais qui est un point de passage obligé', () => {
    const ligne = lignes(demarrer()).find(l => (l.textContent || '').includes('Lointain'))!;
    expect(ligne.textContent).toContain('Relais Pilat');
  });

  it('distingue une passerelle de tiers de la nôtre', () => {
    const avecTiers: RoutageMeshtastic = {
      ...ROUTAGE,
      routes: [route({
        node_num: 0x1111, sauts: 1, hop_limit_suffisant: true,
        passerelles: [{
          node_num: 0x7777, nom: 'Inconnue', snr: 3, rssi: null, nombre: 2,
          dernier_vu: null, nous: false, retour_prouve: false,
        }],
      })],
    };
    const fixture = demarrer([CONTACTS[0]], avecTiers);
    expect(fixture.nativeElement.querySelector('.passerelle-tiers')).toBeTruthy();
  });

  it('trie les nœuds détectés par nombre de sauts, les hors de portée en dernier', () => {
    const fixture = demarrer();
    fixture.componentInstance.triContacts.cle = 'sauts';
    fixture.componentInstance.triContacts.sens = 1;
    expect(fixture.componentInstance.contactsAffiches.map((c: any) => c.long_name))
      .toEqual(['Direct', 'Lointain', 'Muet']);
    fixture.componentInstance.triContacts.sens = -1;
    expect(fixture.componentInstance.contactsAffiches.map((c: any) => c.long_name))
      .toEqual(['Lointain', 'Direct', 'Muet']);
  });

  it('filtre les nœuds détectés sur la colonne passerelle', () => {
    const fixture = demarrer();
    fixture.componentInstance.triContacts.filtres['passerelles'] = 'mairie';
    expect(fixture.componentInstance.contactsAffiches.map((c: any) => c.long_name))
      .toEqual(['Direct']);
  });

  it("filtre sur l'attribution", () => {
    const fixture = demarrer();
    fixture.componentInstance.triContacts.filtres['attribue'] = 'oui';
    expect(fixture.componentInstance.contactsAffiches.map((c: any) => c.long_name))
      .toEqual(['Lointain']);
  });

  it('rend chaque en-tête de colonne triable au clavier', () => {
    const fixture = demarrer();
    const entetes = fixture.nativeElement.querySelectorAll('th.th-triable');
    expect(entetes.length).toBeGreaterThan(20);
    entetes.forEach((th: HTMLElement) => expect(th.getAttribute('tabindex')).toBe('0'));
  });

  it('un clic sur un en-tête trie, puis inverse, puis revient à l ordre du serveur', () => {
    const fixture = demarrer();
    const entete: HTMLElement = fixture.nativeElement
      .querySelectorAll('table.data-table')[2].querySelector('th.th-triable');
    entete.click();
    expect(fixture.componentInstance.triContacts.cle).toBe('nom');
    entete.click();
    expect(fixture.componentInstance.triContacts.sens).toBe(-1);
    entete.click();
    expect(fixture.componentInstance.triContacts.cle).toBeNull();
  });

  it('survit à un routage en erreur sans masquer les nœuds', () => {
    const fixture = TestBed.createComponent(MeshtasticCompanionsComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/compagnons-meshtastic/`).flush([]);
    http.expectOne(`${API}/canaux-meshtastic/`).flush([]);
    http.expectOne(`${API}/noeuds-meshtastic/`).flush([]);
    http.expectOne(`${API}/contacts-meshtastic/`).flush(CONTACTS);
    http.expectOne(`${API}/contacts-meshtastic/routage/`)
      .flush({ detail: 'boum' }, { status: 500, statusText: 'Server Error' });
    http.expectOne(r => r.url === `${API}/users/`).flush([]);
    fixture.detectChanges();
    expect(fixture.componentInstance.routageErreur).toBeTruthy();
    expect(lignes(fixture).length).toBe(3);
  });
});
