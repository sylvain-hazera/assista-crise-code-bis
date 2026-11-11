import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TeamsComponent } from './teams.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { Team, rangEchelon } from '../../shared/models/team.model';

describe('TeamsComponent', () => {
  let component: TeamsComponent;
  let fixture: ComponentFixture<TeamsComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [TeamsComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(TeamsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  /** Tri de l'arborescence de coordination (demande du 28/10/2026, ecrite le 11/11/2026).
   *
   * Sans ce tri, 127 equipes s'affichent dans l'ordre alphabetique et la Coordination
   * Nationale se retrouve entre deux departements. */
  describe('tri par echelon', () => {

    function equipe(nom: string, echelon: Team['echelon'], territoire = ''): Team {
      return {
        id: nom, name: nom, description: '', echelon, territoire_libelle: territoire,
        member_ids: [], assigned_crisis_ids: [], assigned_offer_ids: [],
        assigned_request_ids: [], assigned_information_ids: [], competence_ids: [],
        departements: [], communes: [], missions: [], color: '#000', leader: null,
      } as unknown as Team;
    }

    it('range du national au departemental, les equipes sans echelon en dernier', () => {
      component.teams = [
        equipe('Logistique', ''),
        equipe('Isere', 'DEPARTEMENTAL', 'Isere'),
        equipe('Nationale', 'NATIONAL', 'France'),
        equipe('ARA', 'REGIONAL', 'Auvergne-Rhone-Alpes'),
        equipe('Sud-Est', 'ZONE_DEFENSE', 'Sud-Est'),
      ];
      component.searchQuery = '';

      expect(component.filteredTeams.map(t => t.name)).toEqual([
        'Nationale', 'Sud-Est', 'ARA', 'Isere', 'Logistique',
      ]);
    });

    it('a echelon egal, le territoire departage', () => {
      component.teams = [
        equipe('b', 'DEPARTEMENTAL', 'Savoie'),
        equipe('a', 'DEPARTEMENTAL', 'Ain'),
      ];
      component.searchQuery = '';
      // Par LIBELLE et non par code : « 38 » ne dit rien a personne dans une liste.
      expect(component.filteredTeams.map(t => t.territoire_libelle)).toEqual(['Ain', 'Savoie']);
    });

    it('la recherche porte aussi sur le territoire', () => {
      component.teams = [
        equipe('Coordination Departementale', 'DEPARTEMENTAL', 'Isere'),
        equipe('Coordination Departementale bis', 'DEPARTEMENTAL', 'Savoie'),
      ];
      // Chercher « isere » doit trouver l'equipe : son nom ne contient pas le departement, et
      // c'est pourtant par departement qu'on la cherche.
      component.searchQuery = 'isere';
      expect(component.filteredTeams.length).toBe(1);
    });

    it('rangEchelon place une valeur inconnue avec les equipes sans echelon', () => {
      // Un echelon ajoute cote serveur et pas encore connu du frontend ne doit pas remonter en
      // tete par accident.
      expect(rangEchelon('INCONNU' as never)).toBe(rangEchelon(''));
      expect(rangEchelon(null)).toBe(rangEchelon(undefined));
      expect(rangEchelon('NATIONAL')).toBeLessThan(rangEchelon('DEPARTEMENTAL'));
    });
  });

  describe('encadrement', () => {

    it('estEncadrant lit la liste de l\'equipe selectionnee', () => {
      component.selectedTeam = { membres_encadrement: ['u1'] } as unknown as Team;
      expect(component.estEncadrant('u1')).toBeTrue();
      expect(component.estEncadrant('u2')).toBeFalse();
    });

    it('ne plante pas sans equipe selectionnee', () => {
      component.selectedTeam = null;
      expect(component.estEncadrant('u1')).toBeFalse();
    });
  });
});
