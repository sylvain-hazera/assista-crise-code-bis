import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { fournisseursDeTest } from '../testing/test-providers';
import { environment } from '../../environments/environment';
import { TerrainService } from './terrain.service';
import { TerrainMissionsComponent } from './missions/terrain-missions.component';
import { TerrainAlertesComponent } from './alertes/terrain-alertes.component';

const api = environment.apiUrl;

describe('Espace terrain', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    http = TestBed.inject(HttpTestingController);
  });
  afterEach(() => http.verify());

  it('se présente comme un appareil WEB, avec un identifiant tiré une fois', () => {
    localStorage.removeItem(TerrainService.INSTALLATION);
    const service = TestBed.inject(TerrainService);
    service.presenterLAppareil(false).subscribe();
    const requete = http.expectOne(`${api}/mon-appareil/`);
    expect(requete.request.body.plateforme).toBe('WEB');
    expect(requete.request.body.installation.length).toBeGreaterThanOrEqual(16);
    expect(requete.request.body.installation).toBe(TerrainService.installation());
    requete.flush({});
  });

  it('montre les missions en cours d\'abord, et enregistre « Je commence »', async () => {
    const fixture = TestBed.createComponent(TerrainMissionsComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/missions/`).flush([
      { id: 'a', titre: 'Ronde', crise: 'c', equipe_ids: [], statut: 'TERMINEE' },
      { id: 'b', titre: 'Sacs de sable', crise: 'c', equipe_ids: [], statut: 'EN_PREPARATION' },
      { id: 'c', titre: 'Évacuation', crise: 'c', equipe_ids: [], statut: 'EN_COURS' },
    ]);
    await new Promise(r => setTimeout(r, 60));          // la file locale est relue (IndexedDB)
    fixture.detectChanges();
    const titres = Array.from(fixture.nativeElement.querySelectorAll('h2')).map((h: any) => h.textContent.trim());
    expect(titres).toEqual(['Évacuation', 'Sacs de sable', 'Ronde']);

    const commencer: HTMLButtonElement = fixture.nativeElement.querySelectorAll('article')[1].querySelector('button');
    expect(commencer.textContent).toContain('Je commence');
    commencer.click();
    const patch = http.expectOne(`${api}/missions/b/`);
    expect(patch.request.method).toBe('PATCH');
    expect(patch.request.body).toEqual({ statut: 'EN_COURS' });
    patch.flush({ id: 'b', titre: 'Sacs de sable', crise: 'c', equipe_ids: [], statut: 'EN_COURS' });
    fixture.detectChanges();
    expect(fixture.componentInstance.missions().find(m => m.id === 'b')!.statut).toBe('EN_COURS');
  });

  it('accuse « vue » à l\'affichage et « lue » à l\'ouverture', () => {
    const fixture = TestBed.createComponent(TerrainAlertesComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/mes-notifications/`).flush([
      { id: 'n1', genre: 'MOBILISATION', genre_libelle: 'Mobilisation', titre: 'Renfort demandé', corps: 'Rendez-vous 14 h',
        urgent: true, institution_nom: 'Mairie', campagne: null, date_creation: '2026-11-20T10:00:00Z',
        date_remise: null, date_vue: null, date_lue: null, date_reponse: null },
    ]);
    const vue = http.expectOne(`${api}/mes-notifications/accuser/`);
    expect(vue.request.body).toEqual({ ids: ['n1'], etape: 'VUE' });
    vue.flush({ avancees: 1 });
    fixture.detectChanges();
    (fixture.nativeElement.querySelector('article') as HTMLElement).click();
    const lue = http.expectOne(`${api}/mes-notifications/accuser/`);
    expect(lue.request.body).toEqual({ ids: ['n1'], etape: 'LUE' });
    lue.flush({ avancees: 1 });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Rendez-vous 14 h');
  });
});
