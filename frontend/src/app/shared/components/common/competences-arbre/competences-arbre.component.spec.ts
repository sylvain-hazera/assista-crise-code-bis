import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { environment } from '../../../../../environments/environment';
import { CompetencesArbreComponent } from './competences-arbre.component';

describe('CompetencesArbreComponent (arbre partagé : Proposer mon aide et fiche de bénévole)', () => {
  const api = environment.apiUrl;
  const CATALOGUE = [
    { id: 't', nom: 'Technique', parent: null, active: true },
    { id: 'p', nom: 'Pompage', parent: 't', active: true },
    { id: 'e', nom: 'Électricité', parent: 't', active: true },
    { id: 'x', nom: 'Retirée', parent: null, active: false },
  ];

  function creer() {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()], imports: [CompetencesArbreComponent] });
    const fixture = TestBed.createComponent(CompetencesArbreComponent);
    fixture.detectChanges();
    TestBed.inject(HttpTestingController).expectOne(`${api}/competences/`).flush(CATALOGUE);
    return fixture.componentInstance;
  }

  it('range les sous-thèmes sous leur thème et ne propose pas une compétence désactivée', () => {
    const c = creer();
    expect(c.groupes.map(g => [g.parent.nom, g.children.map(x => x.nom)])).toEqual([['Technique', ['Pompage', 'Électricité']]]);
  });

  it('cocher un thème coche ses sous-thèmes, le décocher les retire tous', () => {
    const c = creer();
    const emis: string[][] = [];
    c.selectionChange.subscribe(l => emis.push(l.map(x => x.id)));
    c.basculerGroupe(c.groupes[0]);
    expect(emis.at(-1)).toEqual(['t', 'p', 'e']);
    expect(c.etat(c.groupes[0])).toBe('all');
    c.basculer(CATALOGUE[1]);
    expect(c.etat(c.groupes[0])).toBe('some');
    c.basculerGroupe(c.groupes[0]);
    c.basculerGroupe(c.groupes[0]);
    expect(emis.at(-1)).toEqual([]);
  });
});
