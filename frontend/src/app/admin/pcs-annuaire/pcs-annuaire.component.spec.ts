import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { PcsAnnuaireComponent } from './pcs-annuaire.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';

/** Paragraphes 2.4 et 4.1 du plan : l'annuaire de crise a son écran. Il dit qui manque à
 * l'appel, sans que cela empêche quoi que ce soit. */
describe('PcsAnnuaireComponent', () => {
  let fixture: ComponentFixture<PcsAnnuaireComponent>;
  let http: HttpTestingController;
  const api = environment.apiUrl;
  const SIDPC = { id: 'c1', categorie: 'PREFECTURE', nom: 'SIDPC 42', organisme: 'Préfecture', email: null,
                  telephone: '+33477000000', notes: null, utilisateur: null, utilisateur_nom: null,
                  mode_alerte: 'TELEPHONE', actif: true, ordre: 0, departement_code: '42', institutions: ['i1'], institutions_noms: [] };

  function demarrer() {
    fixture = TestBed.createComponent(PcsAnnuaireComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/dossier-pcs/`).flush({ institution: 'i1', commune: { nom: 'Saint-Chamond', code: '42207', population: null } });
    http.expectOne(r => r.url === `${api}/interlocuteurs-alerte-pcs/` && r.params.get('institution') === 'i1').flush([SIDPC]);
    fixture.detectChanges();
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [PcsAnnuaireComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('range l’annuaire par catégorie et dit qui manque encore à l’appel', () => {
    demarrer();

    const texte = (fixture.nativeElement as HTMLElement).textContent!;
    expect(texte).toContain('SIDPC 42');
    expect(fixture.componentInstance.categoriesManquantes).toEqual(['Gendarmerie / Police', 'SDIS (secours)']);
    expect(texte).toContain("n'empêche pas d'ouvrir une crise");
  });

  it('ajoute un interlocuteur à l’annuaire de la commune', () => {
    demarrer();
    const composant = fixture.componentInstance;
    composant.ouvrirAjout('SDIS');
    composant.saisie.nom = ' CODIS 42 ';
    composant.saisie.telephone = '18';

    composant.enregistrer();

    const requete = http.expectOne(r => r.url === `${api}/interlocuteurs-alerte-pcs/` && r.method === 'POST');
    expect(requete.request.body).toEqual(jasmine.objectContaining({ categorie: 'SDIS', nom: 'CODIS 42', telephone: '18', email: null }));
    requete.flush({ ...SIDPC, id: 'c2', categorie: 'SDIS', nom: 'CODIS 42' });
    http.expectOne(r => r.url === `${api}/interlocuteurs-alerte-pcs/` && r.method === 'GET').flush([SIDPC]);
    expect(composant.formulaireOuvert).toBeFalse();
  });

  it('retire un contact de l’annuaire de la commune sans supprimer la fiche partagée', () => {
    demarrer();
    spyOn(window, 'confirm').and.returnValue(true);

    fixture.componentInstance.retirer(fixture.componentInstance.interlocuteurs[0]);

    const requete = http.expectOne(`${api}/interlocuteurs-alerte-pcs/c1/detacher/`);
    expect(requete.request.method).toBe('POST');
    requete.flush(SIDPC);
    http.expectOne(r => r.url === `${api}/interlocuteurs-alerte-pcs/` && r.method === 'GET').flush([]);
  });

  it('range les fiches par nom dans chaque rubrique, et affiche les communes voisines', () => {
    demarrer();
    const c = fixture.componentInstance;
    const fiche = (id: string, nom: string, categorie: string) => ({ ...SIDPC, id, nom, categorie } as any);
    c.interlocuteurs = [fiche('a', 'CCAS - Talence', 'ELU_PERSONNEL_COMMUNAL'), fiche('b', 'CCAS - Arès', 'ELU_PERSONNEL_COMMUNAL'),
                        fiche('c', 'Mairie - Le Haillan', 'COMMUNE_VOISINE')];
    const groupes = c.parCategorie;
    expect(groupes.find(g => g.libelle === 'Élu ou personnel communal')!.fiches.map(f => f.nom)).toEqual(['CCAS - Arès', 'CCAS - Talence']);
    expect(groupes.find(g => g.libelle === 'Commune voisine')!.fiches.length).toBe(1);
  });
});
