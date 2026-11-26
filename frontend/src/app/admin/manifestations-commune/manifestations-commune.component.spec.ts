import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { ManifestationsCommuneComponent, PartageMairie } from './manifestations-commune.component';
import { fournisseursDeTest } from '../../testing/test-providers';

describe('ManifestationsCommuneComponent', () => {
  const P: PartageMairie = {
    id: 'p1', commune_code: '33167', mairie: 'Mairie', invitation_libelle: 'Prévenue',
    lignes: [
      { element: 'CONTACT_JOUR_J', libelle: 'Contact mairie le jour J', explication: '…', reserve_mairie: false, origine: 'DEMANDE_ASSOCIATION', statut: 'DEMANDE', statut_libelle: 'En attente de la mairie', en_vigueur: false, crise: null },
      { element: 'INTERVENTION_CRISE', libelle: 'Intervenir sur une crise ouverte', explication: '…', reserve_mairie: true, origine: null, statut: null, statut_libelle: 'Non demandé', en_vigueur: false, crise: null },
    ],
    manifestation: { id: 'm1', titre: 'Course', type_libelle: 'Manifestation', lieu: '', organisateur: '', debut: '2027-03-01T08:00:00Z', fin: '2027-03-01T12:00:00Z', statut: 'PUBLIEE', statut_libelle: 'Publiée', association: 'Radio-club' },
    referent_nom: '', referent_telephone: '', consignes: '', arrete: '', en_vigueur: false, crises_ouvertes: [],
  };

  it('accepte une demande, et refuse de faire intervenir sans crise ouverte', () => {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest(), provideHttpClientTesting()], imports: [ManifestationsCommuneComponent] });
    const fixture = TestBed.createComponent(ManifestationsCommuneComponent);
    const http = TestBed.inject(HttpTestingController);
    fixture.detectChanges();
    http.expectOne(r => r.url.endsWith('/manifestations-commune/')).flush({ partages: [P] });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Course');
    const c = fixture.componentInstance;
    c.geste(P, P.lignes[0], 'accepter');
    const requete = http.expectOne(r => r.method === 'POST' && r.url.endsWith('/manifestations-commune/p1/'));
    expect(requete.request.body).toEqual({ geste: 'accepter', element: 'CONTACT_JOUR_J' });
    requete.flush(P);
    c.geste(P, P.lignes[1], 'offrir');
    expect(c.erreur).toContain('Aucune crise');
    http.match(() => true);
  });
});
