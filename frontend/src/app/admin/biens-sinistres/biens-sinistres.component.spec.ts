import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { BiensSinistresComponent } from './biens-sinistres.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';
import { BienSinistre } from '../../shared/models/bien-sinistre.model';

/** Biens sinistrés autres que les habitations : le dossier d'une voiture brûlée, à remettre à
 * son propriétaire. */
describe('BiensSinistresComponent', () => {
  let fixture: ComponentFixture<BiensSinistresComponent>;
  let composant: BiensSinistresComponent;
  let http: HttpTestingController;
  const api = environment.apiUrl;
  const texte = () => (fixture.nativeElement as HTMLElement).textContent!;
  const VOITURE: BienSinistre = {
    id: 'b1', crise: 'c1', type_bien: 'VEHICULE', designation: 'Renault Clio grise', identification: 'AB-123-CD',
    description: 'Entièrement calcinée.', adresse: 'Devant le 14 allée des Pins', latitude: 44.63, longitude: -1.14,
    nature_degats: 'FEU', statut_evaluation: 'DETRUITE', proprietaire_nom: 'Jeanne Durand', proprietaire_email: 'jeanne@exemple.fr',
    proprietaire_telephone: '', nb_photos: 2,
  };

  function demarrer(biens: BienSinistre[] = [VOITURE]) {
    fixture = TestBed.createComponent(BiensSinistresComponent);
    composant = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne(r => r.url.startsWith(`${api}/crises`)).flush([{ id: 'c1', name: 'Feu de la Teste', is_open: true }]);
    const liste = http.expectOne(r => r.url === `${api}/biens-sinistres/`);
    expect(liste.request.params.get('crise')).toBe('c1');       // une seule crise ouverte : choisie d'office
    liste.flush(biens);
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [BiensSinistresComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('liste les biens de la crise avec leur état, leur cause et leur propriétaire', () => {
    demarrer();
    expect(texte()).toContain('Renault Clio grise');
    expect(texte()).toContain('Détruite');
    expect(texte()).toContain('Feu (incendie, feu de forêt)');
    expect(texte()).toContain('Jeanne Durand');
  });

  it('enregistre un nouveau bien, sans cause tant qu’aucun dégât n’est constaté', () => {
    demarrer([]);
    composant.nouveau();
    composant.brouillon!.designation = '  ';
    composant.enregistrer();
    expect(composant.erreur).toContain('Dites de quel bien il s’agit');
    http.expectNone(r => r.method === 'POST');

    Object.assign(composant.brouillon!, { designation: 'Barque en bois', type_bien: 'BATEAU', statut_evaluation: 'PAS_DE_DEGATS', nature_degats: 'FEU' });
    composant.enregistrer();
    const creation = http.expectOne(r => r.method === 'POST' && r.url === `${api}/biens-sinistres/`);
    expect(creation.request.body.crise).toBe('c1');
    expect(creation.request.body.nature_degats).toBe('');
    creation.flush({ ...VOITURE, id: 'b2', designation: 'Barque en bois' });
    http.expectOne(r => r.url === `${api}/biens-sinistres/`).flush([]);
    expect(composant.brouillon!.id).toBe('b2');
  });

  it('dépose les photos sur le bien et envoie le rapport au propriétaire après confirmation', () => {
    demarrer();
    composant.ouvrir(VOITURE);
    const photos = http.expectOne(r => r.url.startsWith(`${api}/documents`));
    expect(photos.request.urlWithParams).toContain('bien=b1');
    photos.flush([]);

    const champ = { files: [new File(['x'], 'avant.jpg', { type: 'image/jpeg' })], value: 'x' } as unknown as HTMLInputElement;
    composant.deposerPhotos({ target: champ } as unknown as Event);
    const depot = http.expectOne(r => r.method === 'POST' && r.url.startsWith(`${api}/documents`));
    expect((depot.request.body as FormData).get('bien')).toBe('b1');
    depot.flush({ id: 'p1', nom_fichier: 'avant.jpg', date_upload: '2026-11-16T10:00:00Z' });
    http.expectOne(r => r.url === `${api}/biens-sinistres/`).flush([VOITURE]);
    expect(composant.photos.length).toBe(1);

    spyOn(window, 'confirm').and.returnValue(true);
    composant.envoyerAuProprietaire();
    http.expectOne(`${api}/biens-sinistres/b1/envoyer-au-proprietaire/`)
      .flush({ ...VOITURE, rapport_envoye_le: '2026-11-16T10:05:00Z', envoye_a: 'j•••••@exemple.fr' });
    expect(composant.message).toContain('Rapport envoyé à j•••••@exemple.fr');
  });

  it('demande la crise avant d’ajouter un bien quand plusieurs sont ouvertes', () => {
    fixture = TestBed.createComponent(BiensSinistresComponent);
    composant = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne(r => r.url.startsWith(`${api}/crises`)).flush([{ id: 'c1', name: 'A', is_open: true }, { id: 'c2', name: 'B', is_open: true }]);
    http.expectOne(r => r.url === `${api}/biens-sinistres/`).flush([]);

    composant.nouveau();
    expect(composant.brouillon).toBeNull();
    expect(composant.erreur).toContain('Choisissez d’abord la crise');
  });
});
