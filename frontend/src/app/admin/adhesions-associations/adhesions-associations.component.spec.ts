import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { AdhesionsAssociationsComponent, DemandeAdhesionAdmin } from './adhesions-associations.component';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('AdhesionsAssociationsComponent', () => {
  const D: DemandeAdhesionAdmin = {
    id: 'd1', nom: 'FCBA', activite: 'Signaleurs', commune_nom: 'Floirac', echelon_libelle: 'Département', territoire: 'Gironde',
    agrement: '', statut: 'EN_ATTENTE', statut_libelle: 'En attente', motif_refus: '', date_demande: '2026-11-26T10:00:00Z',
    demandeur: 'Paul', demandeur_email: 'paul@exemple.fr', fonction: 'Président', telephone: '', doublons: [],
  };

  it('refuse seulement avec un motif, puis transmet le geste', () => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(), provideHttpClientTesting()], imports: [AdhesionsAssociationsComponent] });
    const fixture = TestBed.createComponent(AdhesionsAssociationsComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(r => r.params.get('toutes') === '1').flush({ demandes: [D] });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Gironde');
    const c = fixture.componentInstance;
    c.traiter(D, 'refuser');
    expect(c.erreur).toContain('pourquoi');
    c.motif = 'Doublon';
    c.traiter(D, 'refuser');
    const requete = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/associations/demandes/d1/'));
    expect(requete.request.body).toEqual({ geste: 'refuser', motif: 'Doublon' });
    requete.flush({});
    http.match(() => true);
  });
});
