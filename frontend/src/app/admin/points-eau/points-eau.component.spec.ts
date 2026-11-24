import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { AuthService } from '../../auth/services/auth.service';
import { environment } from '../../../environments/environment';
import { fournisseursDeTest } from '../../testing/test-providers';
import { infobullePointEau } from '../../shared/components/common/map/map.component';
import { PointEau } from '../../shared/models/veille.model';
import { SignalementPEI } from '../../services/points-eau.service';
import { PointsEauComponent } from './points-eau.component';

const api = `${environment.apiUrl}/points-eau`;
const signalement = (champs: Partial<SignalementPEI> = {}): SignalementPEI => ({
  id: 's1', genre: 'INDISPONIBLE', genre_libelle: 'Indisponible', statut: 'A_VALIDER', statut_libelle: 'À valider par la commune',
  pei: 7, pei_source: 'OSM', pei_ref: '123', latitude: 45.44, longitude: 4.387, precision_m: 8, type_pei: '', source_eau: '',
  debit_estime: null, volume_estime: null, commentaire: 'Capot arraché', commune_code: '42218', auteur: 'Jean Réserve',
  observe_le: '2026-11-24T09:00:00Z', traite_le: null, traite_par: null, motif_decision: '', numero_sdis: '', transmis_le: null,
  photos: [{ id: 'd1', commentaire: '' }], ...champs,
});
const couverture = { attribution_osm: '© contributeurs OpenStreetMap (ODbL)', releves: 2, a_valider_ma_commune: 1, departements: [
  { departement: '42', osm_releve_le: '2026-11-24T08:00:00Z', osm_nombre: 2559, osm_erreur: null, sdis_importe_le: null, sdis_nombre: 0, terrain_nombre: 0 },
] };

describe("Points d'eau incendie (24/11/2026)", () => {
  let http: HttpTestingController;

  function creer(admin: boolean) {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), { provide: AuthService, useValue: { isAdmin: () => admin } }],
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(PointsEauComponent);
    fixture.detectChanges();
    http.expectOne(r => r.url === `${api}/signalements/` && r.params.get('statut') === 'A_VALIDER').flush([signalement()]);
    http.expectOne(`${api}/couverture/`).flush(couverture);
    fixture.detectChanges();
    return fixture;
  }

  it('la commune valide ; un rejet exige un motif', () => {
    const fixture = creer(false);
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('Capot arraché');
    expect(texte).toContain('1 signalement(s) attendent votre commune');
    expect(texte).not.toContain("Import d'une base SDIS");

    fixture.componentInstance.decider(signalement(), 'rejeter');
    http.expectNone(`${api}/signalements/s1/decider/`);
    expect(fixture.componentInstance.erreur).toContain('motif');

    fixture.componentInstance.decider(signalement(), 'valider');
    const decision = http.expectOne(`${api}/signalements/s1/decider/`);
    expect(decision.request.body).toEqual({ geste: 'valider', motif: '' });
    decision.flush(signalement({ statut: 'VALIDE' }));
    http.expectOne(r => r.url === `${api}/signalements/`).flush([]);
    http.expectOne(`${api}/couverture/`).flush({ ...couverture, a_valider_ma_commune: 0 });
  });

  it("l'import d'une base SDIS est réservé à l'administrateur", () => {
    const fixture = creer(true);
    fixture.componentInstance.choisir('import');
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('datakode/schema-pei');
    fixture.componentInstance.importer();
    expect(fixture.componentInstance.erreur).toContain('département');
    fixture.componentInstance.departementImport = '43';
    fixture.componentInstance.fichierImport = new File(['insee;type_pei'], 'pei.csv');
    fixture.componentInstance.importer();
    const envoi = http.expectOne(`${api}/import/`);
    expect((envoi.request.body as FormData).get('departement')).toBe('43');
    envoi.flush({ departement: '43', importes: 10, nouveaux: 10, supprimes: 0, refuses: 1, refus: [{ ligne: 3, raison: 'insee manquant' }] });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('10 points importés');
    expect(fixture.nativeElement.textContent).toContain('insee manquant');
  });

  it('la fenêtre de la carte dit la source et l’attribution OSM', () => {
    const point = {
      id: 1, source: 'OSM', ref: '9', type_pei: 'PI', type_libelle: "Poteau d'incendie", source_eau: 'reseau_aep',
      diametre: 100, debit: 60, volume: null, ref_terrain: 'BI-12', gestionnaire: '', statut: '', etat: 'INCONNU',
      etat_terrain_le: null, date_controle: null, releve_le: '2026-11-24T08:00:00Z', insee: '42218', latitude: 45.44,
      longitude: 4.38, attribution: '© contributeurs OpenStreetMap (ODbL)', distance_km: null,
    } as PointEau;
    const html = infobullePointEau(point, t => t);
    expect(html).toContain("Poteau d'incendie");
    expect(html).toContain('60 m³/h');
    expect(html).toContain('indicatif');
    expect(html).toContain('OpenStreetMap (ODbL)');
  });
});
