import { TestBed } from '@angular/core/testing';

import { CriseLieuThemeComponent } from './crise-lieu-theme.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';

describe('CriseLieuThemeComponent — familles', () => {
  it('groupe les sous-besoins sous leur famille, même quand la famille n\'est pas écoutée', () => {
    TestBed.configureTestingModule({ providers: fournisseursDeTest(), imports: [CriseLieuThemeComponent] });
    const c = TestBed.createComponent(CriseLieuThemeComponent).componentInstance;
    c.besoins = [
      { id: 'f1', nom: 'Pompage & citernes', parent: null, actif: true, nature: null },
      { id: 'b1', nom: 'Pompage', parent: 'f1', actif: true, nature: null },
      { id: 'b2', nom: 'Cuve / citerne mobile', parent: 'f1', actif: true, nature: null },
      { id: 'b3', nom: 'Soutien psychologique', parent: 'f9', parent_nom: 'Secours & soins', actif: true, nature: null },
      { id: 'f2', nom: 'Transport', parent: null, actif: true, nature: null },
    ];
    expect(c.familles).toEqual([
      { nom: 'Pompage & citernes', sousBesoins: ['Cuve / citerne mobile', 'Pompage'] },
      { nom: 'Secours & soins', sousBesoins: ['Soutien psychologique'] },
      { nom: 'Transport', sousBesoins: [] },
    ]);
  });
});
