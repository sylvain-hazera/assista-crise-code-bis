import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { kmDesCompteurs, LigneReleve, MonReleveComponent, Releve, trajetDe } from './mon-releve.component';
import { fournisseursDeTest } from '../../testing/test-providers';

/** Mon relevé d'heures : le tableau, les oublis complétés à la main, l'activité en regard. */
describe('MonReleveComponent', () => {
  let composant: MonReleveComponent;
  let http: HttpTestingController;

  const LIGNE: LigneReleve = {
    id: 'l1', crise: 'c1', crise_nom: 'Crue', equipe: 'e1', equipe_nom: 'Renfort',
    parti_le: '2026-11-16T07:00:00Z', rentre_le: null, depart_de: 'HEBERGEMENT', retour_a: '',
    hebergement: 'Gîte communal', saisie_manuelle: false, heures: null, validee: false, remarque_chef: '',
  };
  const RELEVE: Releve = {
    du: '2026-10-18', au: '2026-11-17', lignes: [LIGNE], total_heures: 0,
    activite: [
      { quand: '2026-11-16T14:10:00Z', heure: true, source: 'equipe', equipe: 'Renfort', quoi: 'Dossier DOS-1 : pris en charge' },
      { quand: '2026-11-16', heure: false, source: 'moi', equipe: 'Renfort', quoi: 'Planning : créneau matin' },
    ],
    crises: [{ id: 'c1', nom: 'Crue' }], equipes: [{ id: 'e1', nom: 'Renfort' }],
    lieux: [{ code: 'DOMICILE', libelle: 'Domicile' }, { code: 'HEBERGEMENT', libelle: "Point d'hébergement (en déplacement sur site)" }],
    encadre: true,
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
    expect(composant.brouillon).toEqual(jasmine.objectContaining({ activite: 'c:c1', equipe: 'e1', depart_de: 'DOMICILE' }));
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

  it('le chef valide une ligne de son équipe', () => {
    composant.ouvrir('equipe');
    http.expectOne(r => r.method === 'GET' && r.url.endsWith('/releves-equipe/')).flush({ fiches: [
      { personne: 'Léa Petit', lignes: [{ ...LIGNE, rentre_le: '2026-11-16T12:00:00Z', heures: 5 }], total_heures: 5, heures_validees: 0, a_valider: 1 },
    ] });
    expect(composant.aValider).toBe(1);

    composant.relire(composant.fiches[0].lignes[0], 'valider');

    const requete = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/releves-equipe/'));
    expect(requete.request.body).toEqual({ ligne: 'l1', geste: 'valider', remarque: '' });
    requete.flush({});
  });

  it('le chef ne renvoie pas une ligne sans dire quoi revoir', () => {
    composant.onglet = 'equipe';
    composant.relire(LIGNE, 'renvoyer');
    expect(composant.erreur).toContain('à revoir');
    http.expectNone(r => r.method === 'POST');
  });

  it('filtre l\'activité : la mienne, ou celle de mes équipes', () => {
    composant.filtreActivite = 'moi';
    expect(composant.activite.map(a => a.quoi)).toEqual(['Planning : créneau matin']);
    composant.filtreActivite = 'equipe';
    expect(composant.activite.length).toBe(1);
  });

  it('déclare une manifestation avec ses kilomètres, sans équipe (26/11/2026)', () => {
    composant.releve = { ...composant.releve!, manifestations: [{ id: 'm1', nom: 'Course', debut: '2026-11-15T08:00:00Z' }] };
    composant.ajouter();
    composant.brouillon!.activite = 'm:m1';
    composant.brouillon!.kilometres = '42,5';
    composant.brouillon!.vehicule = 'VOITURE';
    composant.brouillon!.parti_le = composant.enLocal('2026-11-15T08:00:00Z');
    composant.brouillon!.rentre_le = composant.enLocal('2026-11-15T12:00:00Z');
    composant.enregistrer();
    const requete = http.expectOne(r => r.method === 'POST');
    expect(requete.request.body).toEqual(jasmine.objectContaining({ crise: null, manifestation: 'm1', equipe: null, kilometres: '42,5', vehicule: 'VOITURE' }));
    requete.flush({});
  });

  it('renonce au remboursement avec l\'adresse du reçu', () => {
    const f = { institution: 'a1', nom: 'Asso', annee: 2026, recus_fiscaux: true, kilometres: 120, montant: '48.00', abandon: null };
    composant.renonciation = f;
    composant.renoncer();
    expect(composant.erreur).toContain('adresse');
    composant.adresse = '3 allée des Pins';
    composant.renoncer();
    const requete = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/mon-releve/abandon/'));
    expect(requete.request.body).toEqual({ institution: 'a1', annee: 2026, adresse: '3 allée des Pins' });
    requete.flush({});
  });

  describe('relevé kilométrique', () => {
    it('les deux compteurs font les kilomètres', () => {
      expect(kmDesCompteurs('45 210', '45262')).toBe(52);
      expect(kmDesCompteurs('45210', '')).toBeNull();
      expect(kmDesCompteurs('1000', '900')).toBeNull();
    });

    it('le trajet se lit d\'un coup d\'œil', () => {
      expect(trajetDe({ ...LIGNE, lieu_depart: 'Domicile', lieu_arrivee: 'Floirac' })).toBe('Domicile → Floirac (A/R)');
      expect(trajetDe({ ...LIGNE, lieu_depart: 'Domicile', lieu_arrivee: 'Floirac', aller_retour: false })).toBe('Domicile → Floirac');
      expect(trajetDe(LIGNE)).toBe('');
    });

    it('envoie le trajet, et les kilomètres des compteurs plutôt que ceux saisis', () => {
      composant.modifier({ ...LIGNE, rentre_le: '2026-11-16T15:00:00Z' });
      Object.assign(composant.brouillon!, { compteur_depart: '100', compteur_arrivee: '146', kilometres: '999', motif: 'Balisage' });
      composant.enregistrer();
      const req = http.expectOne(r => r.method === 'PATCH' && r.url.endsWith('/mon-releve/l1/'));
      expect(req.request.body).toEqual(jasmine.objectContaining({ kilometres: '46', motif: 'Balisage', compteur_depart: '100' }));
    });

    it('un ticket part en multipart avec sa nature et son montant', () => {
      composant.fraisNature = 'STATIONNEMENT';
      composant.fraisMontant = '2,50';
      composant.ajouterFrais(LIGNE);
      const req = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/mon-releve/l1/frais/'));
      const corps = req.request.body as FormData;
      expect(corps.get('nature')).toBe('STATIONNEMENT');
      expect(corps.get('montant')).toBe('2,50');
    });

    it('choisir un véhicule déclaré en reprend le type', () => {
      composant.releve = { ...RELEVE, mes_vehicules: [{ id: 'v1', genre: 'DEUX_ROUES', libelle: 'Scooter', immatriculation: '', puissance_cv: null, designation: 'Scooter' }] };
      composant.ajouter();
      expect(composant.brouillon!.vehicule_personnel).toBe('v1');
      composant.choisirVehicule(composant.brouillon!);
      expect(composant.brouillon!.vehicule).toBe('DEUX_ROUES');
    });
  });
});
