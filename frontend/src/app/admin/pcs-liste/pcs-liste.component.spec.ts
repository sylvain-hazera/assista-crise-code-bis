import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { ActivatedRoute } from '@angular/router';

import { PcsListeComponent } from './pcs-liste.component';
import { PARAGRAPHES_EN_LISTE } from './pcs-listes.config';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';

/** Les paragraphes du plan tenus en liste : organigramme et fiches réflexes, moyens d'alerte,
 * exercices. Un même écran, décrit paragraphe par paragraphe. */
describe('PcsListeComponent', () => {
  let fixture: ComponentFixture<PcsListeComponent>;
  let http: HttpTestingController;
  const api = environment.apiUrl;

  function demarrer(paragraphe: string, lignes: unknown[], zones?: unknown[], equipes?: unknown[]) {
    TestBed.configureTestingModule({
      imports: [PcsListeComponent],
      providers: [...fournisseursDeTest(), { provide: ActivatedRoute, useValue: { snapshot: { data: { paragraphe } } } }],
    });
    http = TestBed.inject(HttpTestingController);
    monte = true;
    fixture = TestBed.createComponent(PcsListeComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/${PARAGRAPHES_EN_LISTE[paragraphe].ressource}/`).flush(lignes);
    if (zones) http.expectOne(r => r.url === `${api}/zones/`).flush(zones);
    if (equipes) http.expectOne(`${api}/teams/equipes-institution/`).flush(equipes);
    fixture.detectChanges();
  }
  const texte = () => (fixture.nativeElement as HTMLElement).textContent!;

  // Un test qui ne monte pas le composant n'a rien demandé au serveur : rien à vérifier alors.
  let monte = false;
  afterEach(() => { if (monte) http.verify(); monte = false; });

  it('chaque paragraphe dit à quoi il sert en crise et décrit des champs cohérents', () => {
    for (const [cle, p] of Object.entries(PARAGRAPHES_EN_LISTE)) {
      expect(p.aQuoiCaSert.length).withContext(cle).toBeGreaterThan(60);
      expect(p.champs.filter(c => c.type === 'choix').every(c => !!c.options?.length)).withContext(cle).toBeTrue();
    }
  });

  it('montre l’organigramme avec titulaire, suppléant, et dit quand la fiche est la fiche type', () => {
    demarrer('organisation', [{ id: 'f1', fonction: 'DOS', fonction_libelle: 'Maire — directeur des opérations de secours',
      libelle: '', equipe: null, titulaire: 'Maire d’essai', titulaire_telephone: '0600000001', suppleant: '', suppleant_telephone: '',
      personnes: { equipe: '', titulaire: 'Maire d’essai', titulaire_telephone: '0600000001', suppleant: '', suppleant_telephone: '' },
      consignes: '', fiche_type: '• Déclenche le plan.' }], undefined, []);

    expect(texte()).toContain('Maire — directeur des opérations de secours');
    expect(texte()).toContain('Pas de suppléant');
    expect(texte()).toContain('fiche type');
    expect(texte()).toContain("n'empêche d'ouvrir une crise");

    fixture.componentInstance.modifier(fixture.componentInstance.lignes[0]);
    fixture.detectChanges();
    expect(texte()).toContain('Déclenche le plan.');
  });

  it('relie une fonction à l’équipe qui la tient, et montre les personnes reprises de l’équipe', () => {
    demarrer('organisation', [{ id: 'f2', fonction: 'COORDINATION', fonction_libelle: 'Coordinateur des moyens et des actions',
      libelle: '', equipe: 'e1', titulaire: '', titulaire_telephone: '', suppleant: '', suppleant_telephone: '',
      personnes: { equipe: 'Cellule municipale', titulaire: 'Camille Responsable', titulaire_telephone: '',
                   suppleant: 'Dominique Adjoint', suppleant_telephone: '' },
      consignes: '', fiche_type: '' }], undefined, [{ id: 'e1', name: 'Cellule municipale' }, { id: 'e2', name: 'Équipe accueil' }]);
    const composant = fixture.componentInstance;

    // Rien n'a été saisi, et pourtant l'organigramme nomme les personnes : elles viennent de l'équipe.
    expect(texte()).toContain('Équipe : Cellule municipale');
    expect(texte()).toContain('Titulaire : Camille Responsable');
    expect(texte()).toContain('Suppléant : Dominique Adjoint');

    composant.ouvrirAjout();
    composant.saisie['fonction'] = 'SOUTIEN';
    composant.saisie['equipe'] = 'e2';
    composant.enregistrer();

    const requete = http.expectOne(r => r.url === `${api}/pcs-fonctions/` && r.method === 'POST');
    expect(requete.request.body).toEqual(jasmine.objectContaining({ fonction: 'SOUTIEN', equipe: 'e2', titulaire: '' }));
    requete.flush({ id: 'f3' });
    http.expectOne(r => r.url === `${api}/pcs-fonctions/` && r.method === 'GET').flush([]);
  });

  it('ajoute un moyen d’alerte, pour toute la commune quand aucun quartier n’est choisi', () => {
    demarrer('alerte', [], [{ id: 'z0', nom: 'Mon territoire' }, { id: 'z1', nom: 'Quartier bas' }]);
    const composant = fixture.componentInstance;
    // La zone créée d'office n'est pas un quartier : elle n'est pas proposée.
    expect(composant.zones.map(z => z.nom)).toEqual(['Quartier bas']);

    composant.ouvrirAjout();
    composant.saisie['type'] = 'SIRENE';
    composant.saisie['description'] = ' Toit de la mairie ';
    composant.enregistrer();

    const requete = http.expectOne(r => r.url === `${api}/pcs-moyens-alerte/` && r.method === 'POST');
    expect(requete.request.body).toEqual(jasmine.objectContaining({ type: 'SIRENE', description: 'Toit de la mairie', zone: null }));
    requete.flush({ id: 'm1' });
    http.expectOne(r => r.url === `${api}/pcs-moyens-alerte/` && r.method === 'GET').flush([]);
  });

  it('affiche le refus du serveur quand un exercice est daté dans le futur', () => {
    demarrer('exercices', []);
    const composant = fixture.componentInstance;
    composant.ouvrirAjout();
    composant.saisie['theme'] = 'Crue';
    composant.enregistrer();

    http.expectOne(r => r.url === `${api}/pcs-exercices/` && r.method === 'POST')
      .flush({ date: ["Un exercice se consigne une fois joué, pas à l'avance."] }, { status: 400, statusText: 'Bad Request' });

    expect(composant.erreur).toContain('une fois joué');
    expect(composant.formulaireOuvert).toBeTrue();
  });
});
