import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';

import { PersonnesVulnerablesComponent } from './personnes-vulnerables.component';
import { fournisseursDeTest } from '../../testing/test-providers';
import { environment } from '../../../environments/environment';
import { EtatRegistreVulnerables } from '../../shared/models/habilitation-registre.model';
import { PersonneVulnerable } from '../../shared/models/vulnerabilite.model';

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
    fixture.detectChanges();
  }

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
});
