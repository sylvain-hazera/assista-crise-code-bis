import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { PersonnesVulnerablesComponent } from './personnes-vulnerables.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';
import { EtatRegistreVulnerables } from '../../shared/models/habilitation-registre.model';
import { EtatRattachement, ExpositionRegistre, PersonneVulnerable } from '../../shared/models/vulnerabilite.model';

/**
 * Édition PDF du registre des personnes vulnérables : l'annexe nominative du plan communal de
 * sauvegarde. Elle ne se propose qu'à qui tient le registre, et jamais sans confirmation.
 */
describe('PersonnesVulnerablesComponent — édition du registre', () => {
  let fixture: ComponentFixture<PersonnesVulnerablesComponent>;
  let http: HttpTestingController;
  const api = environment.apiUrl;

  const ETAT: EtatRegistreVulnerables = {
    institution: 'i1', institution_nom: 'Mairie de Saint-Chamond', habilitation: null,
    a_un_titre: true, lecture_seule_administrateur: false, engagement_signe: true,
    engagement_a_signer: false, engagement_signe_le: '2026-11-01T10:00:00Z',
    engagement_version_signee: '2026-10', engagement_version_courante: '2026-10',
    texte_engagement: '', rappel_bandeau: 'Secret professionnel.', peut_designer: false,
  };

  function fiche(id: string, commune: string): PersonneVulnerable {
    return {
      id, institution_declarante: 'i1', commune_code: commune, nom: 'Exemple', prenom: 'Jeanne',
      adresse: '1 rue du Test', categorie_ids: [], mode_consentement: 'VOLONTAIRE', actif: true,
      date_creation: '2026-11-01T10:00:00Z', date_maj: '2026-11-01T10:00:00Z',
    } as PersonneVulnerable;
  }

  function demarrer(etat: Partial<EtatRegistreVulnerables>, fiches: PersonneVulnerable[]) {
    fixture = TestBed.createComponent(PersonnesVulnerablesComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/habilitations-registre-vulnerables/mon-etat/`).flush({ ...ETAT, ...etat });
    http.expectOne(`${api}/personnes-vulnerables/`).flush(fiches);
    // Qui tient le registre voit aussi où en est le rattachement aux adresses (une seule commune).
    http.match(r => r.url === `${api}/personnes-vulnerables/rattachement/`).forEach(r => r.flush(rattachement));
    http.match(r => r.url === `${api}/personnes-vulnerables/exposition/`).forEach(r => r.flush(exposition));
    fixture.detectChanges();
  }
  let rattachement: EtatRattachement = { releve_disponible: true, fiches: 1, rattachees: 1, exactes: 0, a_rattacher: [] };
  let exposition: ExpositionRegistre = { seuils: {}, degats: {}, non_situees: 0 };

  const boutonEdition = (): HTMLButtonElement | null =>
    Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
      .find(b => b.textContent!.includes('Éditer le registre')) ?? null;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [PersonnesVulnerablesComponent], providers: fournisseursDeTest() });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('propose l’édition à qui tient le registre, et la demande au serveur après confirmation', () => {
    demarrer({}, [fiche('p1', '42207')]);
    spyOn(window, 'confirm').and.returnValue(true);
    spyOn(URL, 'createObjectURL').and.returnValue('blob:essai');
    spyOn(URL, 'revokeObjectURL');

    boutonEdition()!.click();

    const requete = http.expectOne(r => r.url === `${api}/personnes-vulnerables/pdf/`);
    expect(requete.request.params.get('commune_code')).toBe('42207');
    expect(requete.request.responseType).toBe('blob');
    requete.flush(new Blob(['%PDF'], { type: 'application/pdf' }));
    expect(URL.createObjectURL).toHaveBeenCalled();
    expect(fixture.componentInstance.editionEnCours).toBeFalse();
  });

  it('ne demande rien au serveur si la personne renonce devant le rappel du secret', () => {
    demarrer({}, [fiche('p1', '42207')]);
    const confirmer = spyOn(window, 'confirm').and.returnValue(false);

    boutonEdition()!.click();

    expect(confirmer.calls.mostRecent().args[0]).toContain('secret professionnel');
    http.expectNone(r => r.url === `${api}/personnes-vulnerables/pdf/`);
  });

  it('ne propose pas l’édition à la lecture d’exploitation de l’administrateur', () => {
    demarrer({ lecture_seule_administrateur: true }, [fiche('p1', '42207')]);

    expect(boutonEdition()).toBeNull();
  });

  it('fait choisir la commune quand le registre tenu par délégation en couvre plusieurs', () => {
    demarrer({}, [fiche('p1', '42207'), fiche('p2', '42218')]);
    const confirmer = spyOn(window, 'confirm').and.returnValue(true);
    spyOn(URL, 'createObjectURL').and.returnValue('blob:essai');
    spyOn(URL, 'revokeObjectURL');

    boutonEdition()!.click();
    expect(confirmer).not.toHaveBeenCalled();
    expect(fixture.componentInstance.errorMessage).toContain('Choisissez la commune');
    http.expectNone(r => r.url === `${api}/personnes-vulnerables/pdf/`);

    fixture.componentInstance.communeAImprimer = '42218';
    boutonEdition()!.click();
    const requete = http.expectOne(r => r.url === `${api}/personnes-vulnerables/pdf/`);
    expect(requete.request.params.get('commune_code')).toBe('42218');
    requete.flush(new Blob(['%PDF'], { type: 'application/pdf' }));
  });

  describe('rattachement aux adresses de la commune', () => {
    beforeEach(() => {
      rattachement = { releve_disponible: true, fiches: 2, rattachees: 1, exactes: 1, a_rattacher: [
        { id: 'p2', nom: 'Jeanne Exemple', adresse: '3 chemin du Moulin', lien_perdu: false,
          propositions: [{ ban_id: 'b3', adresse: '3 Chemin du Moulin 42400 Saint-Chamond', exacte: true }] }] };
      exposition = { seuils: { p1: 1.5 }, degats: { p1: 'Dégâts forts' }, non_situees: 1 };
    });
    afterEach(() => {
      rattachement = { releve_disponible: true, fiches: 1, rattachees: 1, exactes: 0, a_rattacher: [] };
      exposition = { seuils: {}, degats: {}, non_situees: 0 };
    });

    it('dit combien de fiches sont rattachées, et ce que le lien apprend de chacune', () => {
      demarrer({}, [{ ...fiche('p1', '42207'), adresse_ban_id: 'b1' }, fiche('p2', '42207')]);
      const page = (fixture.nativeElement as HTMLElement).textContent!;

      expect(page).toContain('1 fiche sur 2');
      expect(page).toContain('eau dès 1,5 m (simulation) — dégâts forts');
      expect(fixture.nativeElement.querySelectorAll('.lien-adresse').length).toBe(1);
    });

    it('rattache une fiche à l’adresse proposée, ou toutes les identiques d’un coup', () => {
      demarrer({}, [{ ...fiche('p1', '42207'), adresse_ban_id: 'b1' }, fiche('p2', '42207')]);
      const composant = fixture.componentInstance;

      composant.rattacher('p2', 'b3');
      const requete = http.expectOne(`${api}/personnes-vulnerables/p2/rattacher/`);
      expect(requete.request.body).toEqual({ ban_id: 'b3' });
      requete.flush(fiche('p2', '42207'));
      http.expectOne(`${api}/personnes-vulnerables/`).flush([fiche('p1', '42207'), fiche('p2', '42207')]);
      http.expectOne(r => r.url === `${api}/personnes-vulnerables/rattachement/`).flush(rattachement);
      http.expectOne(r => r.url === `${api}/personnes-vulnerables/exposition/`).flush(exposition);

      composant.rattacherExactes();
      http.expectOne(`${api}/personnes-vulnerables/rattacher-exactes/`).flush({ ...rattachement, rattachees: 2, a_rattacher: [] });
      http.expectOne(`${api}/personnes-vulnerables/`).flush([fiche('p1', '42207'), fiche('p2', '42207')]);
      http.match(() => true).forEach(r => r.flush(r.request.url.endsWith('exposition/') ? exposition : rattachement));
    });

    it('ne demande rien de tout cela pour la lecture d’exploitation de l’administrateur', () => {
      demarrer({ lecture_seule_administrateur: true }, [fiche('p1', '42207')]);

      expect(fixture.componentInstance.rattachement).toBeNull();
    });
  });
});
