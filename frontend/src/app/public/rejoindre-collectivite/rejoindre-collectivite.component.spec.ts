import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, convertToParamMap } from '@angular/router';
import { HttpTestingController } from '@angular/common/http/testing';

import { RejoindreCollectiviteComponent } from './rejoindre-collectivite.component';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('RejoindreCollectiviteComponent', () => {
  function creer() {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(),
        { provide: ActivatedRoute, useValue: { snapshot: { paramMap: convertToParamMap({ jeton: 'abc' }) } } }],
      imports: [RejoindreCollectiviteComponent],
    });
    const f = TestBed.createComponent(RejoindreCollectiviteComponent);
    f.detectChanges();
    return { f, http: TestBed.inject(HttpTestingController) };
  }

  it('exige la convention quand la collectivité ne l\'a pas signée', () => {
    const { f, http } = creer();
    http.expectOne(r => r.url.endsWith('/rejoindre-collectivite/abc/'))
      .flush({ institution: 'Mairie - Rive-de-Gier', type: 'mairie', invite_par: 'Réserve Résilience', convention_requise: true });
    const c = f.componentInstance;
    c.saisie = { prenom: 'Claire', nom: 'Fontaine', email: 'claire@commune.fr', telephone: '', fonction: 'Maire', convention: false };
    expect(c.peutEnvoyer).toBeFalse();
    c.saisie.convention = true;
    expect(c.peutEnvoyer).toBeTrue();
  });

  it('un lien invalide le dit', () => {
    const { f, http } = creer();
    http.expectOne(r => r.url.endsWith('/rejoindre-collectivite/abc/')).flush({}, { status: 404, statusText: 'Not Found' });
    expect(f.componentInstance.etat).toBe('invalide');
  });
});
