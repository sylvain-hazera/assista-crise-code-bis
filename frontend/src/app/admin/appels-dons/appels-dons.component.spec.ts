import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { AppelsDonsComponent } from './appels-dons.component';
import { ChoixDonComponent } from './choix-don.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';
import { AppelAuxDons, FamilleCatalogueDon } from '../../shared/models/appel-dons.model';

const CATALOGUE: FamilleCatalogueDon[] = [
  { famille: 'VETEMENTS', libelle: 'Vêtements et chaussures', articles: [
    { designation: 'T-shirt', publics: ['HOMME', 'GARCON'], mesure: 'haut', neuf_exige: false, quantite: 4, quantite_urgence: 2, tailles: { HOMME: ['M', 'L'], GARCON: ['8 ans'] } },
    { designation: 'Chaussures', publics: ['HOMME'], mesure: 'pointure', neuf_exige: false, quantite: 1, quantite_urgence: 1, tailles: { HOMME: ['42', '43'] } },
    { designation: 'Body', publics: ['BEBE'], mesure: 'haut', neuf_exige: true, quantite: 6, quantite_urgence: 3, tailles: { BEBE: ['6 mois'] } }] },
  { famille: 'PUERICULTURE', libelle: 'Puériculture', articles: [
    { designation: 'Chauffe-biberon', publics: ['BEBE'], mesure: '', neuf_exige: false, quantite: 1, quantite_urgence: 1, tailles: {} }] },
];

function ligne(id: string, designation: string, voulue: number, promise: number, extra: object = {}) {
  return { id, famille: designation === 'Chauffe-biberon' ? 'PUERICULTURE' : 'VETEMENTS', designation, public: '', taille: '', neuf_exige: false, precision: '',
    libelle: designation, message: '', nb_beneficiaires: 1, pour_qui: 'pour 1 homme', formulation: `${designation} — pour 2 hommes (${voulue} pièces)`,
    quantite_urgente: 0, urgent: false, quantite_voulue: voulue, quantite_recue: 0, quantite_promise: promise, reste: voulue - promise, engagements: [], ...extra };
}

const APPEL = {
  id: 'ap1', institution_nom: 'Mairie de La Teste', crise: null, crise_nom: 'Feu', titre: 'Familles sinistrées', description: '', statut: 'OUVERT',
  statut_libelle: 'Ouvert', point: null, point_nom: null, depot: null, depot_nom: null, livraison_adresse: 'Salle des fêtes', livraison_horaires: '',
  contact_nom: 'Mme Roy', contact_telephone: '', contact_email: '', delai_engagement_jours: 7, le_mien: false, envois: [],
  portee_km: 100, portee: 'dans un rayon de 100 km', distance_km: 52,
  besoins: [ligne('b1', 'T-shirt', 7, 3), ligne('b2', 'Chauffe-biberon', 1, 1)],
  avancement: { lignes: 2, lignes_couvertes: 1, pieces_voulues: 8, pieces_recues: 0, pieces_promises: 4, pieces_restantes: 4 },
} as unknown as AppelAuxDons;

describe('AppelsDonsComponent', () => {
  let fixture: ComponentFixture<AppelsDonsComponent>;
  let composant: AppelsDonsComponent;
  let http: HttpTestingController;
  const api = `${environment.apiUrl}/dons`;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [AppelsDonsComponent], providers: fournisseursDeTest() });
    fixture = TestBed.createComponent(AppelsDonsComponent);
    composant = fixture.componentInstance;
    http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(`${api}/catalogue/`).flush({ familles: CATALOGUE });
    http.expectOne(r => r.url === `${api}/appels/` && r.params.get('autres') === '1').flush([APPEL]);
    http.match(() => true).forEach(r => r.flush(r.request.url.endsWith('/etat/') ? { depots: [], articles: [] } : []));
    fixture.detectChanges();
  });

  it('montre une ligne couverte comme fermée, et laisse s’engager sur ce qui reste', () => {
    composant.ouvrir(APPEL);
    fixture.detectChanges();
    const page = fixture.nativeElement as HTMLElement;
    expect(page.textContent).toContain('couvert');                   // le chauffe-biberon : plus rien à collecter
    expect(page.textContent).toContain('T-shirt — pour 2 hommes (7 pièces)');   // un besoin se dit pour des personnes
    expect(page.querySelectorAll('button.btn-primary').length).toBe(1); // un seul « Je m'engage », sur le T-shirt

    composant.promesses['b1'] = 4;
    composant.engager(APPEL.besoins[0]);
    const envoi = http.expectOne(`${api}/appels/ap1/engager/`);
    expect(envoi.request.body).toEqual({ besoin: 'b1', quantite: 4 });
    envoi.flush({ ...APPEL, besoins: [ligne('b1', 'T-shirt', 7, 7, { engagements: [{ id: 'e1', quantite: 4, statut: 'PROMIS', statut_libelle: 'Promis', le_mien: true }] }), APPEL.besoins[1]] });
    expect(composant.message).toContain('Annoncez votre envoi sous 7 jours');
    expect(composant.mesPromesses).toEqual([{ id: 'e1', libelle: 'T-shirt', quantite: 4 }]);

    composant.preparerAnnonce();
    composant.annoncer();
    expect(http.expectOne(`${api}/appels/ap1/annoncer-envoi/`).request.body.engagements).toEqual(['e1']);
  });

  it('dit jusqu’où l’appel est lancé et à quelle distance on en est, et laisse son auteur l’élargir', () => {
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Lancé dans un rayon de 100 km — à 52 km de vous');

    composant.ouvrir({ ...APPEL, le_mien: true, distance_km: null });
    composant.changerPortee(100);                                    // inchangé : rien ne part
    http.expectNone(`${api}/appels/ap1/`);
    composant.changerPortee(null);
    const envoi = http.expectOne(`${api}/appels/ap1/`);
    expect(envoi.request.body).toEqual({ id: 'ap1', portee_km: null });
    envoi.flush({ ...APPEL, le_mien: true, portee_km: null, portee: 'dans toute la France' });
    expect(composant.message).toContain('dans toute la France');
  });

  it('affiche le refus quand la ligne vient d’être couverte par une autre institution', () => {
    composant.ouvrir(APPEL);
    composant.promesses['b1'] = 4;
    composant.engager(APPEL.besoins[0]);
    http.expectOne(`${api}/appels/ap1/engager/`).flush({ detail: 'Il n\'en reste que 1 à couvrir pour « T-shirt »' }, { status: 400, statusText: 'Bad Request' });
    expect(composant.erreur).toContain('Il n\'en reste que 1');
  });

  it('propose le trousseau de chacun dans ses tailles, une ligne par personne', () => {
    composant.nouveauFoyer();
    composant.foyer!.personnes = [{ public: 'HOMME', age: 41, taille_haut: 'L', taille_bas: '', pointure: '43' }, { public: 'BEBE', age: 0, taille_haut: '6 mois', taille_bas: '', pointure: '' }];
    expect(composant.grille(composant.foyer!.personnes[0], 'pointure')).toEqual(['42', '43']);

    composant.proposerTrousseau();

    const besoins = composant.foyer!.besoins.map(b => `${composant.libelle(b)} × ${b.quantite}`);
    expect(besoins).toEqual(['T-shirt, homme, L × 4', 'Chaussures, homme, 43 × 1', 'Body, bébé, 6 mois × 6', 'Chauffe-biberon, bébé × 1']);
    expect(composant.foyer!.besoins[0].quantite_urgence).toBe(2);    // deux T-shirts tout de suite, quatre pour durer
    // Une ligne de plus est le besoin d'une AUTRE personne : elle ne se fond pas dans la première.
    composant.ajouterBesoin({ famille: 'VETEMENTS', designation: 'T-shirt', public: 'HOMME', taille: 'L', neuf_exige: false, quantite: 2 });
    expect(composant.foyer!.besoins.length).toBe(5);
    expect(composant.foyer!.besoins[4].quantite_urgence).toBe(1);
  });
});

describe('ChoixDonComponent', () => {
  it('exige la taille quand l’article en a, et rend une ligne précise', () => {
    TestBed.configureTestingModule({ imports: [ChoixDonComponent] });
    const composant = TestBed.createComponent(ChoixDonComponent).componentInstance;
    composant.catalogue = CATALOGUE;
    const choisi = jasmine.createSpy('choisi');
    composant.choisi.subscribe(choisi);

    composant.famille = 'VETEMENTS';
    composant.article = CATALOGUE[0].articles[0];
    composant.surArticle();
    expect(composant.public).toBe('HOMME');
    expect(composant.quantite).toBe(4);
    expect(composant.complet).toBeFalse();                           // pas encore de taille
    composant.taille = 'L';
    composant.quantite = 3;
    composant.message = ' Son maillot bleu ';
    composant.ajouter();

    expect(choisi).toHaveBeenCalledWith({ famille: 'VETEMENTS', designation: 'T-shirt', public: 'HOMME', taille: 'L', neuf_exige: false, quantite: 3,
      quantite_urgence: 1, message: 'Son maillot bleu' });
  });
});
