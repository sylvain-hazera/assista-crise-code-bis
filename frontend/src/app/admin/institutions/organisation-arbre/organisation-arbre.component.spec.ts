import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { OrganisationArbreComponent } from './organisation-arbre.component';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { NoeudOrganisation } from '../../../services/organisation.service';

describe('OrganisationArbreComponent', () => {
  const reserve: NoeudOrganisation = { id: 'r', nom: 'Réserve communale du Porge', actif: true, type_code: 'rcsc', type_libelle: 'RCSC',
    rcsc: true, commune: 'Le Porge', membres: 1, equipes: [], filles: [] };
  const mairie: NoeudOrganisation = { id: 'm', nom: 'Mairie du Porge', actif: true, type_code: 'mairie', type_libelle: 'Mairie',
    rcsc: false, commune: 'Le Porge', membres: 2, equipes: [], filles: [reserve] };

  it('affiche la mairie et sa réserve, et se replie', () => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(), provideHttpClientTesting()], imports: [OrganisationArbreComponent] });
    const fixture = TestBed.createComponent(OrganisationArbreComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(r => r.url.endsWith('/organisation/')).flush({ arbres: [mairie] });
    fixture.detectChanges();
    const texte = (fixture.nativeElement as HTMLElement).textContent || '';
    expect(texte).toContain('Mairie du Porge');
    expect(texte).toContain('Réserve communale du Porge');
    expect(fixture.componentInstance.icone(reserve)).toBe('shield');
    expect(fixture.componentInstance.totalFilles(mairie)).toBe(1);
    fixture.componentInstance.basculer('m');
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).not.toContain('Réserve communale du Porge');
    http.verify();
  });
});
