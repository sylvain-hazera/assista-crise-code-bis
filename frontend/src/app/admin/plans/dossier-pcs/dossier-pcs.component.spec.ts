import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { DossierPcsComponent } from './dossier-pcs.component';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { environment } from '../../../../environments/environment';
import { DossierPcs } from '../../../services/dossier-pcs.service';

/**
 * Le panneau du document du plan communal de sauvegarde : il montre ce que le document
 * reprendra, ce qui manque (avec le chemin pour le combler), et sort le PDF.
 */
describe('DossierPcsComponent', () => {
  let fixture: ComponentFixture<DossierPcsComponent>;
  let http: HttpTestingController;
  const url = `${environment.apiUrl}/dossier-pcs`;

  const DOSSIER: DossierPcs = {
    institution: 'i1', institution_nom: 'Mairie de Saint-Chamond',
    commune: { nom: 'Saint-Chamond', code: '42207', population: 35339 },
    arrete_numero: '', arrete_date: null, lieu_pcc: '', lieu_pcc_repli: '', modalites_activation: '',
    paragraphes: [
      { numero: '1.1', titre: 'Risques de la commune', route: '/admin/pcs-risques', reutilise: 'Rattachés aux dispositifs.', nombre: 2, etat: 'RENSEIGNE' },
      { numero: '2.2', titre: 'Zones et quartiers', route: '/admin/zones', reutilise: 'Facultatif.', nombre: 0, etat: 'VIDE' },
    ],
    equipes_par_point: {},
    revisions: [],
    manques: [
      { partie: 'Arrêté', message: "Le numéro et la date de l'arrêté ne sont pas renseignés.", ou: 'Mon plan de sauvegarde', route: '/admin/plans' },
      { partie: 'Enjeux', message: "Aucun site sensible n'est retenu au plan.", ou: 'Sites sensibles', route: '/admin/sites-sensibles' },
    ],
    contenu: { risques: 2, sites_sensibles: 0, dispositifs: 1, missions_types: 3, interlocuteurs: 5, membres: 4, equipes: 2, points: 1 },
  };

  function demarrer(dossier: DossierPcs = DOSSIER) {
    fixture = TestBed.createComponent(DossierPcsComponent);
    fixture.detectChanges();
    http.expectOne(`${url}/`).flush(dossier);
    fixture.detectChanges();
  }
  const texte = () => (fixture.nativeElement as HTMLElement).textContent!;
  const bouton = (libelle: string) =>
    Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
      .find(b => b.textContent!.includes(libelle))!;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [DossierPcsComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('dit ce que le document reprendra et ce qui manque, avec le chemin pour le combler', () => {
    demarrer();

    expect(texte()).toContain('2 risques');
    expect(texte()).toContain('1 dispositif (3 missions types)');
    expect(texte()).toContain('Ce qui reste à compléter (2)');
    const lien = fixture.nativeElement.querySelector('.manques a') as HTMLAnchorElement;
    expect(lien.getAttribute('href')).toBe('/admin/sites-sensibles');
    // Ce qui se complète ici même ne renvoie pas vers la page où l'on est déjà.
    expect(fixture.nativeElement.querySelectorAll('.manques a').length).toBe(1);
  });

  it('donne à chaque paragraphe du plan son écran, son état et son utilité', () => {
    demarrer();

    const lignes = Array.from(fixture.nativeElement.querySelectorAll('.paragraphes tbody tr')) as HTMLElement[];
    expect(lignes.length).toBe(2);
    expect(lignes[0].querySelector('a')!.getAttribute('href')).toBe('/admin/pcs-risques');
    expect(lignes[0].textContent).toContain('renseigné (2)');
    expect(lignes[1].textContent).toContain('à compléter');
    expect(texte()).toContain("Aucun n'est obligatoire pour ouvrir une crise");
  });

  it('enregistre la partie administrative et relit ce qui manque', () => {
    demarrer();
    bouton('Modifier').click();
    fixture.detectChanges();
    const composant = fixture.componentInstance;
    composant.saisie.arrete_numero = '2026-021';
    composant.saisie.arrete_date = '2026-11-16';

    composant.enregistrer();

    const requete = http.expectOne(`${url}/`);
    expect(requete.request.method).toBe('PATCH');
    expect(requete.request.body.arrete_numero).toBe('2026-021');
    requete.flush({ ...DOSSIER, arrete_numero: '2026-021', arrete_date: '2026-11-16', manques: [DOSSIER.manques[1]] });
    fixture.detectChanges();
    expect(texte()).toContain('n° 2026-021');
    expect(texte()).toContain('Ce qui reste à compléter (1)');
  });

  it('inscrit une mise à jour au tableau du plan', () => {
    demarrer();
    fixture.componentInstance.objetRevision = '  Annuaire revu  ';

    fixture.componentInstance.ajouterRevision();

    const requete = http.expectOne(`${url}/revisions/`);
    expect(requete.request.body).toEqual({ objet: 'Annuaire revu' });
    requete.flush({ ...DOSSIER, revisions: [{ date: '2026-11-16', objet: 'Annuaire revu', auteur: 'Agent' }] });
    fixture.detectChanges();
    expect(texte()).toContain('Annuaire revu');
    expect(fixture.componentInstance.objetRevision).toBe('');
  });

  it('édite le plan en PDF à la demande', () => {
    demarrer();
    spyOn(URL, 'createObjectURL').and.returnValue('blob:essai');
    spyOn(URL, 'revokeObjectURL');

    bouton('Éditer le plan').click();

    const requete = http.expectOne(`${url}/document/`);
    expect(requete.request.responseType).toBe('blob');
    requete.flush(new Blob(['%PDF'], { type: 'application/pdf' }));
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it('édite aussi le DICRIM, le document public des habitants', () => {
    demarrer();
    spyOn(URL, 'createObjectURL').and.returnValue('blob:essai');
    spyOn(URL, 'revokeObjectURL');

    bouton('Éditer le DICRIM').click();

    http.expectOne(`${url}/dicrim/`).flush(new Blob(['%PDF'], { type: 'application/pdf' }));
    expect(URL.createObjectURL).toHaveBeenCalled();
  });

  it("ne montre rien à un compte sans collectivité, plutôt qu'un panneau vide", () => {
    fixture = TestBed.createComponent(DossierPcsComponent);
    fixture.detectChanges();
    http.expectOne(`${url}/`).flush({ detail: 'refus' }, { status: 403, statusText: 'Forbidden' });
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.dossier-pcs')).toBeNull();
  });
});
