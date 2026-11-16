import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { MissionsComponent } from './missions.component';
import { Mission } from '../../shared/models/mission.model';
import { environment } from '../../../environments/environment';

/** Missions d'intérêt général et dossiers génériques (16/11/2026). Une garde du feu n'est pas la
 * réponse à un appel à l'aide : c'est l'institution qui la demande. Ce qui est vérifié : la page
 * dit que l'intitulé est générique, n'offre l'ouverture d'un dossier qu'aux missions concernées,
 * et l'ouvre auprès de notre serveur. */
describe('MissionsComponent', () => {
  const api = environment.apiUrl;
  const GARDE: Mission = {
    id: 'm1', titre: 'Garde du feu', description: 'Massif du Pilat', crise: 'c1', crise_nom: "Risque d'incendie",
    equipe_ids: ['e1'], equipes_noms: ['Réserve communale'], statut: 'EN_COURS',
    institution: 'i1', institution_nom: 'Mairie de Saint-Étienne', interet_general: true,
    dossiers_generiques: [], salon_matrix: { id: 's1', room_id: null, pret: false },
  };
  const ORDINAIRE: Mission = { ...GARDE, id: 'm2', titre: 'Dégagement des routes', interet_general: false };
  let fixture: ComponentFixture<MissionsComponent>;
  let component: MissionsComponent;
  let http: HttpTestingController;

  function demarrer(missions: Mission[] = [GARDE, ORDINAIRE]) {
    fixture = TestBed.createComponent(MissionsComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
    http.expectOne(`${api}/missions/`).flush(missions);
    http.match(() => true).forEach(demande => demande.flush([]));
    fixture.detectChanges();
  }

  const texte = () => (fixture.nativeElement as HTMLElement).textContent ?? '';

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [MissionsComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('signale les missions d’intérêt général dans la liste', () => {
    demarrer();
    const lignes: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('tbody tr'));

    expect(lignes[0].textContent).toContain('Intérêt général');
    expect(lignes[1].textContent).not.toContain('Intérêt général');
  });

  it('dit, à la création, que l’intitulé est générique et ce qu’est une mission d’intérêt général', () => {
    demarrer();
    component.openCreate();
    fixture.detectChanges();

    expect(texte()).toContain('Intitulé générique');
    expect(texte()).toContain('jamais une personne ni une adresse');
    expect(texte()).toContain('personne n\'a appelé à l\'aide');
    expect(component.missionForm.value.interet_general).toBeFalse();
  });

  it('envoie la case « intérêt général » avec la mission', () => {
    demarrer();
    component.openCreate();
    component.missionForm.patchValue({ titre: 'Ronde de nuit', crise: 'c1', interet_general: true });
    component.submitCreate();

    const demande = http.expectOne(r => r.method === 'POST' && r.url === `${api}/missions/`);
    expect(demande.request.body.interet_general).toBeTrue();
    demande.flush({ ...GARDE, id: 'm3', titre: 'Ronde de nuit' });
    http.match(() => true).forEach(d => d.flush([]));
  });

  it('montre qui commande la mission et l’état de son salon', () => {
    demarrer();
    component.openDetail(GARDE);
    fixture.detectChanges();

    expect(texte()).toContain('commandée par Mairie de Saint-Étienne');
    expect(texte()).toContain('Salon de la mission en cours de création');
  });

  it('n’offre d’ouvrir un dossier que sur une mission d’intérêt général en cours', () => {
    demarrer();

    expect(component.peutOuvrirDossier(GARDE)).toBeTrue();
    expect(component.peutOuvrirDossier(ORDINAIRE)).toBeFalse();
    expect(component.peutOuvrirDossier({ ...GARDE, statut: 'TERMINEE' })).toBeFalse();
    component.openDetail(ORDINAIRE);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.ouvrir-dossier')).toBeNull();
  });

  it('ouvre un dossier générique auprès de notre serveur, prérempli avec l’intitulé de la mission', () => {
    demarrer();
    component.openDetail(GARDE);
    component.commencerOuvertureDossier(GARDE);
    fixture.detectChanges();

    expect(component.ouvertureDossier!.titre).toBe('Garde du feu');
    expect(component.ouvertureDossier!.equipe_id).toBe('e1');       // une seule équipe : la sienne
    expect(texte()).toContain('à la demande de');
    expect(texte()).toContain('Mairie de Saint-Étienne');

    component.ouvertureDossier!.description = 'Garde du samedi';
    component.ouvrirDossier();
    const demande = http.expectOne(`${api}/missions/m1/ouvrir-dossier/`);
    expect(demande.request.body).toEqual({ description: 'Garde du samedi', titre: 'Garde du feu', equipe_id: 'e1' });
    demande.flush({ id: 'd1', numero: 'DOS-1234', titre: 'Garde du feu', mission: 'm1', generique: true });

    expect(component.ouvertureDossier).toBeNull();
    expect(component.dossiersForMission('m1').length).toBe(1);
  });

  it('refuse un dossier sans description, sans rien envoyer', () => {
    demarrer();
    component.openDetail(GARDE);
    component.commencerOuvertureDossier(GARDE);
    component.ouvrirDossier();

    expect(component.erreurOuverture).toContain('Décrivez');
  });

  it('affiche le refus du serveur', () => {
    demarrer();
    component.openDetail(GARDE);
    component.commencerOuvertureDossier(GARDE);
    component.ouvertureDossier!.description = 'Garde';
    component.ouvrirDossier();
    http.expectOne(`${api}/missions/m1/ouvrir-dossier/`).flush(
      { error: 'Seule l\'institution qui commande cette mission peut y ouvrir un dossier.' },
      { status: 403, statusText: 'Interdit' });

    expect(component.erreurOuverture).toContain('qui commande cette mission');
    expect(component.ouvertureDossier).not.toBeNull();
  });
});
