import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';

import { BandeauDelegationComponent } from './bandeau-delegation.component';
import { fournisseursDeTest } from '../../../../testing/test-providers';
import { RattachementService } from '../../../../services/rattachement.service';

function creer(etat: any) {
  TestBed.configureTestingModule({ providers: fournisseursDeTest(), imports: [BandeauDelegationComponent] });
  spyOn(TestBed.inject(RattachementService), 'institutionActive').and.returnValue(of(etat));
  const f = TestBed.createComponent(BandeauDelegationComponent);
  const emis: boolean[] = [];
  f.componentInstance.exportSeul.subscribe(v => emis.push(v));
  f.detectChanges();
  return { f, emis };
}

describe('BandeauDelegationComponent', () => {
  it("dit pour qui l'on agit par délégation", () => {
    const { f, emis } = creer({ active: 'm', institutions: [], export_seul: false,
      delegation_en_cours: { id: 'd', collectivite: 'Mairie de Rive-de-Gier', aasc: 'Réserve Résilience' } });
    expect(f.nativeElement.textContent).toContain('Vous agissez pour Mairie de Rive-de-Gier');
    expect(emis).toEqual([false]);
  });

  it("ne laisse que l'export quand la convention est rompue", () => {
    const { f, emis } = creer({ active: 'm', institutions: [], export_seul: true, delegation_en_cours: null });
    expect(f.nativeElement.textContent).toContain('Exporter toutes nos données');
    expect(emis).toEqual([true]);
  });
});
