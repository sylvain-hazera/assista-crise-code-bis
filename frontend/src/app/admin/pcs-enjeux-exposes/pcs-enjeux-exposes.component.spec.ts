import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { EnjeuxExposes, PcsEnjeuxExposesComponent } from './pcs-enjeux-exposes.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';

/** Paragraphe 1.3 : ce que l'eau atteint, à partir de quel niveau — des hypothèses, dites telles. */
describe('PcsEnjeuxExposesComponent', () => {
  let fixture: ComponentFixture<PcsEnjeuxExposesComponent>;
  let http: HttpTestingController;
  const url = `${environment.apiUrl}/dossier-pcs/enjeux-exposes/`;

  const DONNEES: EnjeuxExposes = {
    commune_code: '42207', simulation_disponible: true, niveaux_m: [1, 2], niveau_max_m: 2, atteints: 2, non_situes: 1,
    en_zone_officielle: 0, zonages_officiels: { releve: false, releve_le: null, complet: false, couches: [] },
    enjeux: [
      { nature: "Lieu d'accueil ou point", categorie: "Centre d'accueil", nom: 'Gymnase', situe: true, seuil_m: 1, effectif: 120, zone_officielle: '' },
      { nature: 'Site sensible', categorie: "Établissement d'enseignement", nom: 'Collège', situe: true, seuil_m: 2, effectif: 400, zone_officielle: '' },
      { nature: 'Site sensible', categorie: 'Accueil du jeune enfant', nom: 'Crèche du haut', situe: true, seuil_m: null, effectif: 30, zone_officielle: '' },
      { nature: 'Site sensible', categorie: 'Autre', nom: 'Sans coordonnées', situe: false, seuil_m: null, effectif: null, zone_officielle: '' },
    ],
  };

  function demarrer(donnees: EnjeuxExposes) {
    fixture = TestBed.createComponent(PcsEnjeuxExposesComponent);
    fixture.detectChanges();
    http.expectOne(url).flush(donnees);
    fixture.detectChanges();
  }
  const texte = () => (fixture.nativeElement as HTMLElement).textContent!;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [PcsEnjeuxExposesComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    // Le bloc commun « Ce que l'État publie pour la commune » lit son relevé à l'affichage (18/11/2026).
    http.match(r => r.method === 'GET' && r.url.endsWith('/dossier-pcs/georisques/')).forEach(r => r.flush({ commune_code: '42186', releve: false, releve_le: null, complet: false, rubriques: [], sismicite: '', radon: '', catnat: { nombre: 0, derniers: [] }, azi: [], tri: [], mouvements: [], cavites: 0 }));
    http.verify();
  });

  it('dit pour chaque enjeu le niveau d’eau qui l’atteint, et compte ce qui est dans l’eau au niveau regardé', () => {
    demarrer(DONNEES);
    const composant = fixture.componentInstance;

    expect(texte()).toContain('hypothèses, pas des prévisions');
    expect(texte()).toContain('atteint à partir de 1 m');
    expect(texte()).toContain("au sec jusqu'à 2 m");
    expect(texte()).toContain('non situé');
    expect(composant.nombreAtteints).toBe(2);          // au plus haut niveau simulé

    composant.niveau = 1;
    fixture.detectChanges();
    expect(composant.nombreAtteints).toBe(1);          // le gymnase seul, dès 1 m
    expect(fixture.nativeElement.querySelectorAll('tr.atteint').length).toBe(1);
    expect(texte()).toContain("À 1 m : 1 enjeu dans l'eau");
  });

  it('renvoie à la simulation quand elle n’a pas tourné, plutôt que d’afficher « rien d’atteint »', () => {
    demarrer({ ...DONNEES, simulation_disponible: false, niveaux_m: [], niveau_max_m: null });

    expect(texte()).toContain("La simulation d'inondation n'a pas été lancée");
    expect(fixture.nativeElement.querySelector('table')).toBeNull();
  });

  it('demande le relevé des zones officielles à notre serveur, puis les montre une fois relevées', () => {
    demarrer(DONNEES);
    const bouton = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
      .find(b => b.textContent!.includes('Relever auprès de Géorisques'))!;

    bouton.click();
    // Un seul relevé pour tout Géorisques, le même bouton que sur « Risques de la commune ».
    http.expectOne(r => r.method === 'POST' && r.url === `${environment.apiUrl}/dossier-pcs/georisques/`)
      .flush({ commune_code: '42186', releve: false, releve_le: null, complet: false, rubriques: [], sismicite: '', radon: '', catnat: { nombre: 0, derniers: [] }, azi: [], tri: [], mouvements: [], cavites: 0 });
    fixture.detectChanges();
    expect(texte()).toContain('Relevé demandé');

    fixture.componentInstance.charger();
    http.expectOne(url).flush({
      ...DONNEES, en_zone_officielle: 1,
      enjeux: [{ ...DONNEES.enjeux[0], zone_officielle: 'débordement moyen (centennal, réf. PPRI)' }],
      zonages_officiels: { releve: true, releve_le: '2026-11-16T21:00:00Z', complet: true,
        couches: [{ couche: 'c', libelle: 'débordement moyen (centennal, réf. PPRI)', relevee: true, presente: true }] },
      // Le même relevé rapporte les plans de prévention (17/11/2026) : le bouton ne disparaît
      // que quand les deux sont là.
      plans_prevention: { releve: true, releve_le: '2026-11-16T21:00:00Z', complet: true, plans: [{
        id_gaspar: '33DREAL20170013', famille: 'Risques naturels', libelle: 'PPR Bordeaux (revision)', modele: 'PPRN-I',
        bassin: '', en_revision: true, zonage_existe: true, modifie_le: null,
        zones: [{ nom: 'Rouge non urbanisé', regle: 'Interdiction' }],
      }] },
    });
    fixture.detectChanges();
    expect(texte()).toContain('1 enjeu en zone officielle');
    expect(texte()).toContain('PPR Bordeaux (revision)');
    expect(texte()).toContain('Rouge non urbanisé (interdiction)');
    expect(texte()).not.toContain('Relever auprès de Géorisques');
  });

  it('dit qu’il n’y a rien à croiser tant que le plan n’a ni site ni lieu d’accueil', () => {
    demarrer({ ...DONNEES, enjeux: [], atteints: 0, non_situes: 0 });

    expect(texte()).toContain("il n'y a rien à croiser");
  });
});
