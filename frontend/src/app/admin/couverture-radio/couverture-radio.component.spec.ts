import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { CouvertureRadioComponent } from './couverture-radio.component';
import { environment } from '../../../environments/environment';
import {
  BilanLiaison, CalibrationRadio, CouvertureRadioSite,
} from '../../shared/models/couverture-radio.model';

function couverture(partiel: Partial<CouvertureRadioSite> = {}): CouvertureRadioSite {
  return {
    id: 'c1', nom: 'Château d\'eau', latitude: 45.43, longitude: 4.39, node_num: null,
    hauteur_antenne_m: 25, hauteur_cible_m: 2, preset: 'LONG_FAST', puissance_dbm: 27,
    rayon_max_km: 25, nb_rayons: 72, pas_m: 500, perte_environnement_db: 12, calibre: false,
    surface_estimee_km2: 184.2, points_sans_altitude: 0, nombre_points: 1420,
    statut: 'TERMINEE', erreur: null,
    date_lancement: '2026-11-07T08:00:00Z', date_calcul: '2026-11-07T08:01:00Z',
    ...partiel,
  };
}

const BILAN: BilanLiaison = {
  marge_db: 14.2, distance_m: 8300, diffraction_db: 4.1,
  obstacle: { distance_km: 0.4, hauteur_m: 60 },
  parametres: {
    preset: 'LONG_FAST', hauteur_site_m: 20, hauteur_cible_m: 2, puissance_dbm: 27,
    gains_dbi: 4.3, pertes_db: 1.5, marge_securite_db: 6, perte_environnement_db: 12,
    calibre: false, seuil_dbm: -130.5, rayon_max_km: 40,
  },
};

describe('CouvertureRadioComponent', () => {
  let http: HttpTestingController;
  const urlCouvertures = `${environment.apiUrl}/couvertures-radio`;
  const urlCalibrations = `${environment.apiUrl}/calibrations-radio`;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [CouvertureRadioComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    // Le polling peut avoir une requête en vol : on la vide avant de vérifier.
    http.match(`${urlCouvertures}/`).forEach((r) => r.flush([]));
    http.verify();
  });

  function demarrer(couvertures: CouvertureRadioSite[] = [], calibrations: CalibrationRadio[] = []) {
    const fixture = TestBed.createComponent(CouvertureRadioComponent);
    fixture.detectChanges();
    http.match(`${urlCouvertures}/`).forEach((r) => r.flush(couvertures));
    http.expectOne(`${urlCalibrations}/`).flush(calibrations);
    fixture.detectChanges();
    return fixture;
  }

  it('avertit en toutes lettres quand le modèle n’est pas calibré', () => {
    // Le point qui décide de la confiance : sans calibration, c'est une indication de relief.
    const texte = demarrer().nativeElement.textContent as string;
    expect(texte).toContain('Modèle non calibré');
    expect(texte).toContain('indication de relief');
  });

  it('annonce la calibration quand elle existe', () => {
    const fixture = demarrer([], [{
      id: 'k1', preset: 'LONG_FAST', liaisons_retenues: 12, ecart_median_db: 17.4,
      perte_environnement_db: 17, exemples: [], date_calcul: '2026-11-07T07:00:00Z',
    }]);
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('calibré sur');
    expect(texte).toContain('12');
    expect(texte).not.toContain('Modèle non calibré');
  });

  it('ignore une calibration qui n’a pas conclu', () => {
    // perte_environnement_db nul = moins de cinq liaisons exploitables : ne pas s'en servir.
    const composant = demarrer([], [{
      id: 'k0', preset: 'LONG_FAST', liaisons_retenues: 2, ecart_median_db: 9.0,
      perte_environnement_db: null, exemples: [], date_calcul: '2026-11-07T07:00:00Z',
    }]).componentInstance;
    expect(composant.derniereCalibration).toBeNull();
  });

  it('calcule un bilan de liaison et le rend lisible', () => {
    const fixture = demarrer();
    const composant = fixture.componentInstance;
    composant.liaison = { ...composant.liaison, lat_a: 45.43, lon_a: 4.39, lat_b: 45.46, lon_b: 4.42 };
    composant.analyser();

    const requete = http.expectOne(`${urlCouvertures}/analyser-liaison/`);
    expect(requete.request.body.hauteur_a_m).toBe(20);
    requete.flush(BILAN);
    fixture.detectChanges();

    expect(composant.bilan).toEqual(BILAN);
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('passe');
    expect(texte).toContain('14.2');
    // L'obstacle déterminant est expliqué : ce n'est pas le plus haut, et ça surprend.
    expect(texte).toContain('Fresnel');
  });

  it('n’envoie rien si une coordonnée manque', () => {
    const composant = demarrer().componentInstance;
    composant.liaison = { ...composant.liaison, lat_a: 45.0, lon_a: null, lat_b: 45.1, lon_b: 4.1 };
    composant.analyser();
    http.expectNone(`${urlCouvertures}/analyser-liaison/`);
  });

  it('traduit la marge en verdict, avec un seuil de justesse', () => {
    // 6 dB est la marge d'évanouissement déjà intégrée : en dessous, la liaison existe mais ne
    // tient pas par mauvais temps.
    const composant = demarrer().componentInstance;
    expect(composant.verdict(-3).texte).toBe('ne passe pas');
    expect(composant.verdict(2).texte).toContain('justesse');
    expect(composant.verdict(12).texte).toBe('passe');
    expect(composant.verdict(30).texte).toContain('largement');
  });

  it('met la couverture en file et recharge la liste', () => {
    const fixture = demarrer();
    const composant = fixture.componentInstance;
    composant.site = { ...composant.site, nom: ' Crêt ', latitude: 45.43, longitude: 4.39 };
    composant.lancerCouverture();

    const requete = http.expectOne(`${urlCouvertures}/calculer/`);
    expect(requete.request.body.nom).toBe('Crêt');          // espaces retirés
    requete.flush(couverture({ statut: 'EN_COURS' }));
    http.match(`${urlCouvertures}/`).forEach((r) => r.flush([couverture({ statut: 'EN_COURS' })]));
    http.expectOne(`${urlCalibrations}/`).flush([]);
    expect(composant.calcul_en_file).toBeTrue();
  });

  it('signale une couverture non calibrée et les trous d’altimétrie', () => {
    const fixture = demarrer([couverture({ points_sans_altitude: 42 })]);
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('non calibré');
    expect(texte).toContain('sous-estimation possible');
  });

  it('affiche le motif d’un échec de calcul plutôt que de le taire', () => {
    const fixture = demarrer([couverture({
      statut: 'ECHEC', erreur: "Le service d'altimétrie IGN n'a pas assez répondu.",
      surface_estimee_km2: null,
    })]);
    expect(fixture.nativeElement.textContent).toContain("altimétrie IGN");
  });

  it('explique un refus 403 au lieu d’une erreur générique', () => {
    const fixture = TestBed.createComponent(CouvertureRadioComponent);
    fixture.detectChanges();
    http.match(`${urlCouvertures}/`).forEach((r) =>
      r.flush(null, { status: 403, statusText: 'Forbidden' }));
    http.expectOne(`${urlCalibrations}/`).flush([]);
    expect(fixture.componentInstance.erreur).toContain('institutionnels');
  });
});
