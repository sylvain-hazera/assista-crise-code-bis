import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { environment } from '../../../../environments/environment';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { NoeudEquipe, Team } from '../../../shared/models/team.model';
import { NoeudsEquipeComponent } from './noeuds-equipe.component';

const api = `${environment.apiUrl}/teams/e1/noeuds`;
const noeud = (champs: Partial<NoeudEquipe>): NoeudEquipe => ({
  id: 'n1', protocole: 'MESHTASTIC', identifiant: 'a1b2c3d4', nom: 'ALPH-1', etat: 'EN_RESERVE', etat_libelle: 'En réserve',
  confie_a: null, confie_a_nom: null, appareil: null, configure_le: null, moyen_configuration: '', a_jour: false, remarque: '', ...champs,
});

describe('Nœuds dédiés de l’équipe (25/11/2026)', () => {
  let http: HttpTestingController;

  function creer(noeuds: NoeudEquipe[]) {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(NoeudsEquipeComponent);
    fixture.componentRef.setInput('equipe', { id: 'e1', name: 'Alpha', members_info: [{ id: 'u1', nom: 'Léa' }] } as Team);
    fixture.detectChanges();
    http.expectOne(`${api}/`).flush({ version_plan: 'v1', noeuds });
    fixture.detectChanges();
    return fixture;
  }

  it('montre l’état, la mise à jour des canaux, et la configuration à distance pour Meshtastic seulement', () => {
    const fixture = creer([noeud({}), noeud({ id: 'n2', protocole: 'MESHCORE', identifiant: 'ab', nom: '', a_jour: true, configure_le: '2026-11-25T10:00:00Z', moyen_configuration: 'BLUETOOTH' })]);
    const page = fixture.nativeElement as HTMLElement;
    const mt = page.querySelector('[data-noeud="a1b2c3d4"]')!.textContent!;
    const mc = page.querySelector('[data-noeud="ab"]')!.textContent!;
    expect(mt).toContain('jamais configuré');
    expect(mt).toContain('Configurer à distance');
    expect(mc).toContain('canaux à jour');
    expect(mc).not.toContain('Configurer à distance');
  });

  it('configurer à distance puis confier à un membre', () => {
    const fixture = creer([noeud({})]);
    const composant = fixture.componentInstance;
    composant.aDistance(composant.noeuds[0]);
    http.expectOne(`${api}/n1/configurer-a-distance/`).flush({ taches: 2, passerelle: 'Passerelle Rive', prerequis: 'Clé d’admin.' });
    http.expectOne(`${api}/`).flush({ version_plan: 'v1', noeuds: [noeud({ a_jour: true })] });
    expect(composant.message).toContain('Passerelle Rive');
    composant.etat(composant.noeuds[0], 'u1');
    const requete = http.expectOne(`${api}/n1/`);
    expect(requete.request.body).toEqual({ confie_a: 'u1' });
    requete.flush(noeud({ etat: 'CONFIE', etat_libelle: 'Confié', confie_a: 'u1', confie_a_nom: 'Léa' }));
    expect(composant.noeuds[0].etat).toBe('CONFIE');
  });

  it('ajouter un nœud ; une erreur du serveur est montrée', () => {
    const fixture = creer([]);
    const composant = fixture.componentInstance;
    composant.identifiant = '!A1B2C3D4';
    composant.ajouter();
    http.expectOne(`${api}/`).flush({ error: 'Ce nœud est déjà dédié à l’équipe « Bravo ».' }, { status: 400, statusText: 'Bad Request' });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[role="alert"]')?.textContent).toContain('Bravo');
  });
});
