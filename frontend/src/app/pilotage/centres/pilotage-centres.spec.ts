import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';
import { CentrePilotage, PilotageService } from '../pilotage.service';
import { PilotageCentresComponent, niveauJauge } from './pilotage-centres.component';
import { PilotageCentreComponent } from './pilotage-centre.component';

const api = environment.apiUrl;
const attendre = (ms = 20) => new Promise(r => setTimeout(r, ms));
const centre = (champs: Partial<CentrePilotage> = {}): CentrePilotage => ({
  id: 'p1', nom: 'Gymnase', type: 'HEBERGEMENT', type_libelle: "Centre d'accueil des personnes", etat: 'OUVERT',
  ouvert_le: '2026-11-23T08:00:00Z', ferme_le: null,
  occupation: { presents: 9, capacite: 10, taux: 0.9, presque_plein: true, plein: false,
                par_type: [{ type: 'EVACUE', libelle: 'Personne évacuée', nombre: 7 }], arrivees_24h: 12, departs_24h: 3 },
  manques: [{ article: 'Eau (pack)', niveau: 'FAIBLE' }], equipes: [{ id: 't1', nom: 'Gymnase', effectif: 4 }],
  sur_place_creneau: 2, responsables: [{ nom: 'Camille', telephone: '0600000000' }], peut_gerer: true, accepte_animaux: false,
  ...champs,
});

describe('Pilotage — centres (23/11/2026)', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.removeItem('pilotage-crise');
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(),
      { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ id: 'p1' }), queryParamMap: convertToParamMap({ onglet: 'registre' }) } } }] });
    http = TestBed.inject(HttpTestingController);
  });

  it('la jauge passe à l\'orange à 90 %, au rouge plein', () => {
    expect(niveauJauge(centre())).toBe('presque');
    expect(niveauJauge(centre({ occupation: { ...centre().occupation, presque_plein: false, taux: 0.5 } }))).toBe('ok');
    expect(niveauJauge(centre({ occupation: { ...centre().occupation, plein: true } }))).toBe('plein');
    expect(niveauJauge(centre({ occupation: { ...centre().occupation, capacite: null } }))).toBe('inconnu');
  });

  it('la liste : orientation, jauge, manques, et une arrivée enregistrée en un geste', async () => {
    const pilotage = TestBed.inject(PilotageService);
    pilotage.choisir('c1');
    const fixture = TestBed.createComponent(PilotageCentresComponent);
    fixture.detectChanges();
    const liste = { crise: 'c1', alertes: 1, centres: [centre()],
                    orientation: { cherchent_un_centre: { declarations: 2, personnes: 5 }, relogement: { en_recherche: 3, heberges: 1, reloges: 0 } } };
    http.expectOne(r => r.url === `${api}/pilotage/centres/`).flush(liste);
    fixture.detectChanges();
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('cherchent un centre');
    expect(texte).toContain('Eau (pack)');
    expect(fixture.nativeElement.querySelector('.jauge').getAttribute('data-niveau')).toBe('presque');
    expect(pilotage.alertesCentres()).toBe(1);

    fixture.componentInstance.ouvrirArrivee(centre());
    fixture.componentInstance.nombre = 3;
    const promesse = fixture.componentInstance.enregistrerArrivee(centre());
    const req = http.expectOne(`${api}/registre-presences/`);
    expect(req.request.body).toEqual({ point: 'p1', type_personne: 'EVACUE', nombre: 3 });
    req.flush({ id: 'r9' });
    await promesse;
    http.expectOne(r => r.url === `${api}/pilotage/centres/`).flush(liste);
    expect(fixture.componentInstance.arriveePour()).toBeNull();
    fixture.destroy();
  });

  it('le détail : registre, puis une sortie', async () => {
    const fixture = TestBed.createComponent(PilotageCentreComponent);
    fixture.detectChanges();
    const detail = { ...centre(), adresse: null, mouvements: [], stock: [], planning: [],
      registre: [{ id: 'r1', type: 'EVACUE', libelle: 'Personne évacuée', nombre: 4, arrivee: '2026-11-23T09:00:00Z', nom: 'Famille Durand', commentaire: null }],
      categories: [{ type: 'EVACUE', libelle: 'Personne évacuée' }] };
    http.expectOne(`${api}/pilotage/centres/p1/`).flush(detail);
    await attendre();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Famille Durand');
    const promesse = fixture.componentInstance.sortie('r1');
    http.expectOne(`${api}/registre-presences/r1/sortie/`).flush({});
    await attendre();
    http.expectOne(`${api}/pilotage/centres/p1/`).flush({ ...detail, registre: [] });
    await promesse;
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Personne n\'est enregistré');
    fixture.destroy();
  });
});
