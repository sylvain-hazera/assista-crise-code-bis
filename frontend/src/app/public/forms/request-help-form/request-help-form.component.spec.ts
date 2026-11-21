import { ComponentFixture, TestBed } from '@angular/core/testing';

import { RequestHelpFormComponent } from './request-help-form.component';
import { fournisseursDeTest } from '../../../testing/test-providers';

describe('RequestHelpFormComponent', () => {
  let component: RequestHelpFormComponent;
  let fixture: ComponentFixture<RequestHelpFormComponent>;

  beforeEach(async () => {
    await TestBed.configureTestingModule({
      providers: fournisseursDeTest(),
      imports: [RequestHelpFormComponent]
    })
    .compileComponents();

    fixture = TestBed.createComponent(RequestHelpFormComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('types proposés selon les thèmes à l\'écoute', () => {
    beforeEach(() => {
      component.typesDemandeMap = new Map([
        ['Matériel', 'id-mat'], ['Pompage', 'id-pomp'], ['Manitou', 'id-mani'], ['Transport', 'id-tr'],
      ]);
      component.needTypeOptions = [
        { value: '', label: 'Dropdown' },
        { value: 'Matériel', label: 'Matériel' }, { value: 'Transport', label: 'Transport' },
      ];
      component.childrenByParentType = new Map([
        ['Matériel', [{ value: 'Pompage', label: 'Pompage' }, { value: 'Manitou', label: 'Manitou' }]],
      ]);
    });

    it('propose le parent quand seule une sous-catégorie est à l\'écoute, et seulement elle', () => {
      component.typesDemandeAutorises = ['id-pomp'];
      expect(component.needTypeOptionsFiltrees.map(o => o.value)).toEqual(['Matériel']);
      component.needsType.at(0).setValue('Matériel');
      expect(component.childrenFor(0).map(c => c.value)).toEqual(['Pompage']);
    });

    it('garde toutes les sous-catégories quand le parent est à l\'écoute', () => {
      component.typesDemandeAutorises = ['id-mat'];
      component.needsType.at(0).setValue('Matériel');
      expect(component.childrenFor(0).map(c => c.value)).toEqual(['Pompage', 'Manitou']);
    });

    it('ne propose pas un type sans rien à l\'écoute', () => {
      component.typesDemandeAutorises = ['id-tr'];
      expect(component.needTypeOptionsFiltrees.map(o => o.value)).toEqual(['Transport']);
    });
  });
});
