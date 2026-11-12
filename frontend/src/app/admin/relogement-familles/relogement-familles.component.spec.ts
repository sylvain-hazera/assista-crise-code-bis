import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { RelogementFamillesComponent } from './relogement-familles.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { DossierRelogement, SyntheseRelogement } from '../../shared/models/relogement.model';

/**
 * Ce que ces tests tiennent :
 *
 * 1. **L'ordre par défaut est une hiérarchie d'urgence**, pas un ordre alphabétique : sans
 *    solution d'abord, puis terme dépassé, puis terme proche. Une liste triée par nom ferait
 *    ouvrir la page sans que rien ne ressorte, et c'est l'écran qui dit où regarder.
 * 2. **Le bilan vient du serveur**, et le texte produit en reprend les chiffres tels quels :
 *    un point de situation qui diverge de la page affichée ne vaut rien.
 * 3. **Les filtres portent sur ce qui décide** : sans solution, terme proche, vulnérabilité.
 */
describe('RelogementFamillesComponent', () => {
  let composant: RelogementFamillesComponent;
  let http: HttpTestingController;

  function dossier(partiel: Partial<DossierRelogement>): DossierRelogement {
    return {
      id: 'd1', crise: 'c1', nom_referent: 'Famille A', nombre_adultes: 2, nombre_enfants: 1,
      nombre_personnes: 3, personnes_vulnerables: false, animaux: false, besoin_pmr: false,
      statut: 'HEBERGE', statut_libelle: 'Hébergée', date_ouverture: '2026-11-01',
      solutions: [], date_creation: '2026-11-01', date_maj: '2026-11-01',
      ...partiel,
    } as DossierRelogement;
  }

  function solution(jours: number | null) {
    return {
      id: 's1', dossier_relogement: 'd1', type_solution: 'TEMPORAIRE',
      type_solution_libelle: 'Solution temporaire', titre_occupation: 'HOTEL',
      titre_occupation_libelle: 'Hôtel ou meublé', date_debut: '2026-11-01',
      en_cours: true, jours_restants: jours, date_creation: '2026-11-01',
    } as DossierRelogement['solution_courante'];
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting()],
      imports: [RelogementFamillesComponent],
    });
    composant = TestBed.createComponent(RelogementFamillesComponent).componentInstance;
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.match(() => true);
    http.verify();
  });

  it('met en tête les foyers sans solution, puis les termes dépassés', () => {
    composant.dossiers = [
      dossier({ id: 'ok', nom_referent: 'A', solution_courante: solution(90) }),
      dossier({ id: 'depasse', nom_referent: 'B', solution_courante: solution(-5) }),
      dossier({ id: 'sans', nom_referent: 'C', solution_courante: null,
                statut: 'EN_RECHERCHE' }),
      dossier({ id: 'proche', nom_referent: 'D', solution_courante: solution(7) }),
    ];

    expect(composant.dossiersAffiches.map(d => d.id))
      .toEqual(['sans', 'depasse', 'proche', 'ok']);
  });

  it('ne range pas un dossier clos parmi les urgences', () => {
    // Il est sorti du dispositif, il n'est pas à la rue : le remonter en tête ferait courir
    // après une famille qui n'a besoin de rien.
    composant.dossiers = [
      dossier({ id: 'clos', solution_courante: null, statut: 'CLOS_SANS_SUITE' }),
      dossier({ id: 'heberge', solution_courante: solution(60) }),
    ];

    expect(composant.dossiersAffiches.map(d => d.id)).toEqual(['heberge', 'clos']);
  });

  it('filtre sur les foyers sans solution', () => {
    composant.dossiers = [
      dossier({ id: 'sans', solution_courante: null, statut: 'EN_RECHERCHE' }),
      dossier({ id: 'avec', solution_courante: solution(30) }),
    ];
    composant.filtreSansSolution = true;

    expect(composant.dossiersAffiches.map(d => d.id)).toEqual(['sans']);
  });

  it('cherche sur le nom, la commune et l\'hébergeur', () => {
    composant.dossiers = [
      dossier({ id: 'a', nom_referent: 'Famille Durand' }),
      dossier({ id: 'b', nom_referent: 'Famille Martin',
                commune_origine_nom: 'Saint-Priest' }),
    ];
    composant.recherche = 'priest';

    expect(composant.dossiersAffiches.map(d => d.id)).toEqual(['b']);
  });

  it('écrit un point de situation à partir des chiffres du serveur', () => {
    // Même source que les tuiles : un bilan recompté à l'écran finirait par diverger.
    composant.synthese = {
      crise: 'c1', crise_nom: 'Crue de test', date_arrete: '2026-11-12',
      foyers: 12, personnes: 31, adultes: 19, enfants: 12,
      foyers_avec_personnes_vulnerables: 3, par_statut: {}, par_type_solution_courante: {},
      relogees_durablement: 4, sans_solution: 2, sans_solution_ids: [],
      arrivent_a_terme: 3, arrivent_a_terme_ids: [], termes_depasses: 1,
      termes_depasses_ids: [], jours_alerte_terme: 30,
    } as SyntheseRelogement;

    const texte = composant.bilanTexte;

    expect(texte).toContain('12 foyer(s) suivi(s), soit 31 personne(s)');
    expect(texte).toContain('4 foyer(s) relogé(s) durablement');
    expect(texte).toContain('2 foyer(s) sans solution');
    expect(texte).toContain('1 hébergement(s) dont le terme est dépassé');
  });
});
