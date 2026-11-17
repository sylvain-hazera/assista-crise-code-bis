import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { BilanImportQuartiers, CouchesCartoComponent } from './couches-carto.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';

/** Sortir les couches vers un logiciel de cartographie, faire entrer les quartiers : toujours
 * un aperçu avant de créer, et jamais le registre des personnes vulnérables. */
describe('CouchesCartoComponent', () => {
  let fixture: ComponentFixture<CouchesCartoComponent>;
  let composant: CouchesCartoComponent;
  let http: HttpTestingController;
  const url = `${environment.apiUrl}/couches-carto`;
  const texte = () => (fixture.nativeElement as HTMLElement).textContent!;
  const APERCU: BilanImportQuartiers = {
    enregistre: false, crees: 1, remplaces: 0, laisses: 1, ignores: 0,
    lignes: [{ nom: 'Quartier Nord', action: 'CREE', remarque: 'converti depuis le Lambert 93' },
             { nom: 'Centre', action: 'EXISTE', remarque: 'un quartier de ce nom existe déjà : laissé tel quel' }],
  };

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [CouchesCartoComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(CouchesCartoComponent);
    composant = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne(`${url}/`).flush([
      { couche: 'quartiers', libelle: 'Quartiers et zones de la commune', objets: 3 },
      { couche: 'zonages-officiels', libelle: 'Zones inondables officielles (Géorisques)', objets: 0 },
    ]);
    fixture.detectChanges();
  });

  afterEach(() => http.verify());

  it('liste les couches, télécharge celle qu’on demande et ne propose rien pour une couche vide', () => {
    spyOn(URL, 'createObjectURL').and.returnValue('blob:essai');
    spyOn(URL, 'revokeObjectURL');
    expect(texte()).toContain('Le registre des personnes vulnérables ne sort jamais par ici');
    const boutons = Array.from(fixture.nativeElement.querySelectorAll('table button') as NodeListOf<HTMLButtonElement>);
    expect(boutons[1].disabled).toBeTrue();
    expect(boutons[1].textContent).toContain('Rien à exporter');

    boutons[0].click();
    const requete = http.expectOne(`${url}/quartiers/`);
    expect(requete.request.responseType).toBe('blob');
    requete.flush(new Blob(['{}'], { type: 'application/geo+json' }));
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it('montre un aperçu qui ne crée rien, puis importe seulement à la demande', () => {
    composant.fichier = new File(['{}'], 'quartiers.geojson');
    composant.envoyer(false);
    const apercu = http.expectOne(`${url}/quartiers/importer/`);
    expect((apercu.request.body as FormData).has('enregistrer')).toBeFalse();
    apercu.flush(APERCU);
    fixture.detectChanges();
    expect(texte()).toContain('rien n\'est encore créé');
    expect(texte()).toContain('converti depuis le Lambert 93');
    expect(texte()).toContain('existe déjà');

    composant.remplacer = true;
    composant.envoyer(true);
    const envoi = http.expectOne(`${url}/quartiers/importer/`);
    expect((envoi.request.body as FormData).get('enregistrer')).toBe('1');
    expect((envoi.request.body as FormData).get('remplacer')).toBe('1');
    envoi.flush({ ...APERCU, enregistre: true, crees: 1, remplaces: 1 });
    http.expectOne(`${url}/`).flush([]);
    fixture.detectChanges();
    expect(texte()).toContain('Import terminé');
    expect(composant.fichier).toBeNull();
  });

  it('affiche l’explication du serveur quand le fichier n’est pas une couche', () => {
    composant.fichier = new File(['x'], 'quartiers.shp');
    composant.envoyer(false);
    http.expectOne(`${url}/quartiers/importer/`).flush(
      { fichier: ['Ce fichier n\'est pas un GeoJSON. Depuis QGIS : clic droit sur la couche, Exporter, format GeoJSON.'] },
      { status: 400, statusText: 'Bad Request' });
    fixture.detectChanges();
    expect(texte()).toContain('Depuis QGIS');
    expect(composant.apercu).toBeNull();
  });
});
