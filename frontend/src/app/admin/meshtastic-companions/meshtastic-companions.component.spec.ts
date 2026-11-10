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

  function demarrer(contacts: any[] = CONTACTS, routage: RoutageMeshtastic = ROUTAGE,
                    rattachements: any[] = []) {
    const fixture = TestBed.createComponent(MeshtasticCompanionsComponent);
    fixture.detectChanges();
    http.expectOne(`${API}/compagnons-meshtastic/`).flush([]);
    http.expectOne(`${API}/canaux-meshtastic/`).flush([]);
    http.expectOne(`${API}/noeuds-meshtastic/`).flush([]);
    http.expectOne(`${API}/contacts-meshtastic/`).flush(contacts);
    http.expectOne(`${API}/contacts-meshtastic/routage/`).flush(routage);
    http.expectOne(`${API}/rattachements-noeuds-radio/`).flush(rattachements);
    http.expectOne(r => r.url === `${API}/users/`).flush([]);
    fixture.detectChanges();
    return fixture;
  }

  describe('rattachement des répéteurs', () => {
    const RATTACHEMENT = {
      id: 'r1', node_num: 0x3333, institution: 'i1', institution_nom: 'Mairie',
      utilisateur: null, responsable: 'Mairie de Saint-Pierre', libelle: 'Château d\'eau',
      note: '',
    };

    it('affiche qui répond du nœud, et propose de rattacher les autres', () => {
      const fixture = demarrer(CONTACTS, ROUTAGE, [RATTACHEMENT]);
      const texte = fixture.nativeElement.textContent as string;

      expect(fixture.componentInstance.responsable(0x3333)).toBe('Mairie de Saint-Pierre');
      expect(texte).toContain('Mairie de Saint-Pierre');
      // Les nœuds sans responsable gardent le bouton : c'est la seule façon d'en désigner un.
      expect(fixture.componentInstance.responsable(0x1111)).toBeNull();
      expect(texte).toContain('rattacher');
    });

    it('rattache à l\'institution du compte quand il en a une, et relit ensuite', () => {
      const fixture = demarrer();
      // `institution_id` est servi par le profil : le composant ne le devine pas.
      localStorage.setItem('current_user', JSON.stringify({ id: 'u1', institution_id: 'i1' }));

      fixture.componentInstance.libellesParContact['a'] = 'Répéteur du pylône';
      fixture.componentInstance.rattacher(CONTACTS[0] as any);

      const envoi = http.expectOne(`${API}/rattachements-noeuds-radio/`);
      expect(envoi.request.method).toBe('POST');
      expect(envoi.request.body).toEqual({
        node_num: 0x1111, institution: 'i1', utilisateur: null, libelle: 'Répéteur du pylône',
      });
      envoi.flush({});

      // Relecture : le serveur seul sait ce qu'il a enregistré, et si un conflit d'unicité a
      // été arbitré entre-temps.
      http.expectOne(`${API}/rattachements-noeuds-radio/`).flush([RATTACHEMENT]);
      localStorage.removeItem('current_user');
    });

    it('rattache au compte lui-même quand il n\'a pas d\'institution', () => {
      const fixture = demarrer();
      localStorage.setItem('current_user', JSON.stringify({ id: 'u1' }));

      fixture.componentInstance.rattacher(CONTACTS[0] as any);
      const envoi = http.expectOne(`${API}/rattachements-noeuds-radio/`);
      expect(envoi.request.body.institution).toBeNull();
      expect(envoi.request.body.utilisateur).toBe('u1');
      envoi.flush({});
      http.expectOne(`${API}/rattachements-noeuds-radio/`).flush([]);
      localStorage.removeItem('current_user');
    });

    it('affiche la raison du serveur quand le nœud est déjà rattaché', () => {
      const fixture = demarrer();
      localStorage.setItem('current_user', JSON.stringify({ id: 'u1', institution_id: 'i1' }));

      fixture.componentInstance.rattacher(CONTACTS[0] as any);
      http.expectOne(`${API}/rattachements-noeuds-radio/`).flush(
        { node_num: ['Ce champ doit être unique.'] },
        { status: 400, statusText: 'Bad Request' },
      );
      expect(fixture.componentInstance.rattachementErreur).toContain('unique');
      localStorage.removeItem('current_user');
    });

    it('une colonne de plus reste triable et filtrable, comme toutes les autres', () => {
      // Exigence posée pour cette page : tri ET filtrage sur toutes les colonnes.
      const fixture = demarrer(CONTACTS, ROUTAGE, [RATTACHEMENT]);
      const tri = fixture.componentInstance.triContacts;
      tri.basculer('responsable');
      expect(tri.cle).toBe('responsable');
      tri.filtres['responsable'] = 'saint-pierre';
      expect(fixture.componentInstance.contactsAffiches.map(c => c.node_num)).toEqual([0x3333]);
    });
  });

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
    http.expectOne(`${API}/rattachements-noeuds-radio/`).flush([]);
    http.expectOne(r => r.url === `${API}/users/`).flush([]);
    fixture.detectChanges();
    expect(fixture.componentInstance.routageErreur).toBeTruthy();
    expect(lignes(fixture).length).toBe(3);
  });
});
