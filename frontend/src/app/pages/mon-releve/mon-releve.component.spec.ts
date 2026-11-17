import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { LigneReleve, MonReleveComponent, Releve } from './mon-releve.component';
import { fournisseursDeTest } from '../../testing/test-providers';

/** Mon relevé d'heures : le tableau, les oublis complétés à la main, l'activité en regard. */
describe('MonReleveComponent', () => {
  let composant: MonReleveComponent;
  let http: HttpTestingController;

  const LIGNE: LigneReleve = {
    id: 'l1', crise: 'c1', crise_nom: 'Crue', equipe: 'e1', equipe_nom: 'Renfort',
    parti_le: '2026-11-16T07:00:00Z', rentre_le: null, depart_de: 'HEBERGEMENT', retour_a: '',
    hebergement: 'Gîte communal', saisie_manuelle: false, heures: null,
  };
  const RELEVE: Releve = {
    du: '2026-10-18', au: '2026-11-17', lignes: [LIGNE], total_heures: 0,
    activite: [
      { quand: '2026-11-16T14:10:00Z', heure: true, source: 'equipe', equipe: 'Renfort', quoi: 'Dossier DOS-1 : pris en charge' },
      { quand: '2026-11-16', heure: false, source: 'moi', equipe: 'Renfort', quoi: 'Planning : créneau matin' },
    ],
    crises: [{ id: 'c1', nom: 'Crue' }], equipes: [{ id: 'e1', nom: 'Renfort' }],
    lieux: [{ code: 'DOMICILE', libelle: 'Domicile' }, { code: 'HEBERGEMENT', libelle: "Point d'hébergement (en déplacement sur site)" }],
  };

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting()],
      imports: [MonReleveComponent],
    });
    composant = TestBed.createComponent(MonReleveComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
    composant.ngOnInit();
    http.expectOne(r => r.method === 'GET' && r.url.endsWith('/mon-releve/')).flush(RELEVE);
  });

  afterEach(() => http.match(() => true));

  it('prépare une sortie oubliée avec la seule crise et la seule équipe', () => {
    composant.ajouter();
    expect(composant.brouillon).toEqual(jasmine.objectContaining({ crise: 'c1', equipe: 'e1', depart_de: 'DOMICILE' }));
  });

  it('refuse d\'enregistrer une ligne sans départ ou sans retour', () => {
    composant.ajouter();
    composant.enregistrer();
    expect(composant.erreur).toContain('départ et le retour');
    http.expectNone(r => r.method === 'POST');
  });

  it('reprend une heure de l\'activité : le départ d\'abord, puis le retour', () => {
    composant.ajouter();
    composant.reprendre('2026-11-16T08:00:00Z');
    composant.reprendre('2026-11-16T14:10:00Z');
    expect(composant.brouillon!.parti_le).toBe(composant.enLocal('2026-11-16T08:00:00Z'));
    expect(composant.brouillon!.rentre_le).toBe(composant.enLocal('2026-11-16T14:10:00Z'));
  });

  it('envoie des instants universels, quel que soit le fuseau du poste', () => {
    composant.ajouter();
    composant.brouillon!.parti_le = composant.enLocal('2026-11-16T08:00:00Z');
    composant.brouillon!.rentre_le = composant.enLocal('2026-11-16T14:10:00Z');
    composant.enregistrer();
    const requete = http.expectOne(r => r.method === 'POST');
    expect(requete.request.body.parti_le).toBe('2026-11-16T08:00:00.000Z');
    expect(requete.request.body.rentre_le).toBe('2026-11-16T14:10:00.000Z');
    requete.flush({});
  });

  it('complète le retour oublié d\'une ligne existante par une correction', () => {
    composant.modifier(LIGNE);
    expect(composant.brouillon!.retour_a).toBe('HEBERGEMENT');          // on rentre d'où l'on est parti
    composant.brouillon!.rentre_le = composant.enLocal('2026-11-16T17:00:00Z');
    composant.enregistrer();
    const requete = http.expectOne(r => r.method === 'PATCH' && r.url.endsWith('/mon-releve/l1/'));
    expect(requete.request.body.rentre_le).toBe('2026-11-16T17:00:00.000Z');
    requete.flush({});
  });

  it('filtre l\'activité : la mienne, ou celle de mes équipes', () => {
    composant.filtreActivite = 'moi';
    expect(composant.activite.map(a => a.quoi)).toEqual(['Planning : créneau matin']);
    composant.filtreActivite = 'equipe';
    expect(composant.activite.length).toBe(1);
  });
});
