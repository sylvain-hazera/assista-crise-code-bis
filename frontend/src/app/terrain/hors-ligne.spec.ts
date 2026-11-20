import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { fournisseursDeTest } from '../testing/test-providers';
import { environment } from '../../environments/environment';
import { CoffreChiffre } from '../services/coffre-chiffre';
import { HorsLigneService } from './hors-ligne.service';
import { TerrainMissionsComponent } from './missions/terrain-missions.component';

const api = environment.apiUrl;
const attendre = (ms = 30) => new Promise(r => setTimeout(r, ms));

/** Lit l'entrée brute dans IndexedDB, sans la déchiffrer. */
function brut(base: string, cle: string): Promise<any> {
  return new Promise((resolve, reject) => {
    const d = indexedDB.open(base, 1);
    d.onsuccess = () => {
      const g = d.result.transaction('coffre', 'readonly').objectStore('coffre').get(cle);
      g.onsuccess = () => { resolve(g.result); d.result.close(); };
      g.onerror = () => reject(g.error);
    };
    d.onerror = () => reject(d.error);
  });
}

describe('Terrain hors ligne', () => {
  let http: HttpTestingController;
  let horsLigne: HorsLigneService;

  beforeEach(async () => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    http = TestBed.inject(HttpTestingController);
    horsLigne = TestBed.inject(HorsLigneService);
    await horsLigne.effacer();
  });
  afterEach(async () => { await horsLigne.effacer(); });

  it('le coffre chiffre : rien de lisible dans IndexedDB, tout relu ensuite', async () => {
    const coffre = new CoffreChiffre('essai-coffre');
    await coffre.deposer('m', { titre: 'Évacuation rue des Pins' });
    const entree = await brut('essai-coffre', 'm');
    expect(new TextDecoder().decode(entree.chiffre)).not.toContain('Pins');
    expect(await coffre.lire('m')).toEqual({ titre: 'Évacuation rue des Pins' });
    await coffre.vider();
    expect(await coffre.lire('m')).toBeNull();
  });

  it('rejoue la file dans l\'ordre, s\'arrête sans réseau, abandonne ce que le serveur refuse', async () => {
    await horsLigne.differer({ genre: 'statut_mission', mission: 'a', statut: 'EN_COURS', faite_le: '' });
    await attendre(2);
    await horsLigne.differer({ genre: 'statut_mission', mission: 'b', statut: 'TERMINEE', faite_le: '' });
    await attendre(2);
    await horsLigne.differer({ genre: 'accuse', ids: ['n1'], etape: 'LUE', faite_le: '' });
    expect(horsLigne.enAttente()).toBe(3);

    let envoi = horsLigne.envoyer();
    await attendre();
    http.expectOne(`${api}/missions/a/`).flush({}, { status: 403, statusText: 'Interdit' });   // refusé : abandonné
    await attendre();
    http.expectOne(`${api}/missions/b/`).error(new ProgressEvent('error'));                     // pas de réseau : on s'arrête
    expect(await envoi).toBe(0);
    expect(horsLigne.enAttente()).toBe(2);

    envoi = horsLigne.envoyer();
    await attendre();
    const b = http.expectOne(`${api}/missions/b/`);
    expect(b.request.body).toEqual({ statut: 'TERMINEE' });
    b.flush({});
    await attendre();
    const lu = http.expectOne(`${api}/mes-notifications/accuser/`);
    expect(lu.request.body).toEqual({ ids: ['n1'], etape: 'LUE' });
    lu.flush({ avancees: 1 });
    expect(await envoi).toBe(2);
    expect(horsLigne.enAttente()).toBe(0);
  });

  it('sans réseau : les missions de la dernière lecture, et « Je commence » mis en attente', async () => {
    const missions = [{ id: 'm1', titre: 'Sacs de sable', crise: 'c', equipe_ids: [], statut: 'EN_PREPARATION' }];
    let fixture = TestBed.createComponent(TerrainMissionsComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/missions/`).flush(missions);
    await attendre(60);

    fixture = TestBed.createComponent(TerrainMissionsComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/missions/`).error(new ProgressEvent('error'));
    await attendre(60);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Hors ligne : missions telles qu\'elles étaient');
    expect(fixture.nativeElement.textContent).toContain('Sacs de sable');

    (fixture.nativeElement.querySelector('button.principal') as HTMLButtonElement).click();
    http.expectOne(`${api}/missions/m1/`).error(new ProgressEvent('error'));
    await attendre(60);
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('partira au retour du réseau');
    expect(horsLigne.enAttente()).toBe(1);
    expect((await horsLigne.enFile())[0].valeur).toEqual(jasmine.objectContaining({ mission: 'm1', statut: 'EN_COURS' }));
  });
});
