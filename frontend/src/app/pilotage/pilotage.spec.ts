import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { Router, UrlTree } from '@angular/router';
import { Observable, firstValueFrom, isObservable, of } from 'rxjs';
import { fournisseursDeTest } from '../testing/test-providers';
import { environment } from '../../environments/environment';
import { AuthService } from '../auth/services/auth.service';
import { Dossier } from '../shared/models/dossier.model';
import { User } from '../shared/models/user.model';
import { PilotageService } from './pilotage.service';
import { pilotageGuard } from './pilotage.guard';
import { PILOTAGE_ROUTES } from './pilotage.routes';
import { PilotageLayoutComponent } from './pilotage-layout.component';
import { PilotageSituationComponent, dossiersPrioritaires } from './situation/pilotage-situation.component';
import { PilotageAlertesComponent } from './alertes/pilotage-alertes.component';

const api = environment.apiUrl;
const attendre = (ms = 20) => new Promise(r => setTimeout(r, ms));
const dossier = (champs: Partial<Dossier>): Dossier => ({
  id: 'd', numero: 'D-1', crise: 'c1', titre: 'Dossier', statut: 'EN_COURS', priorite: 'NORMALE',
  date_creation: '2026-11-21T08:00:00Z', ...champs,
} as Dossier);

describe('Poste de pilotage', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    localStorage.removeItem('pilotage-crise');
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    http = TestBed.inject(HttpTestingController);
  });

  it('fait remonter l\'urgent avant l\'important, sans les dossiers clos ni ceux d\'une autre crise', () => {
    const liste = dossiersPrioritaires([
      dossier({ id: 'imp', important: true, date_creation: '2026-11-21T07:00:00Z' }),
      dossier({ id: 'urg', priorite: 'URGENTE', date_creation: '2026-11-21T09:00:00Z' }),
      dossier({ id: 'urg-imp', priorite: 'URGENTE', important: true }),
      dossier({ id: 'clos', priorite: 'URGENTE', statut: 'CLOTURE' }),
      dossier({ id: 'autre', priorite: 'URGENTE', crise: 'c2' }),
      dossier({ id: 'normal' }),
    ], 'c1');
    expect(liste.map(d => d.id)).toEqual(['urg-imp', 'urg', 'imp']);
  });

  it('retient la crise suivie, et revient à la première ouverte si elle est close', async () => {
    const pilotage = TestBed.inject(PilotageService);
    pilotage.choisir('c2');
    const charge = pilotage.chargerCrises();
    http.expectOne(`${api}/crises/`).flush([
      { id: 'c1', name: 'Inondation', is_open: true }, { id: 'c2', name: 'Tempête', is_open: true },
      { id: 'c3', name: 'Ancienne', is_open: false },
    ]);
    await charge;
    expect(pilotage.criseId()).toBe('c2');
    expect(pilotage.crises().length).toBe(2);
    expect(localStorage.getItem('pilotage-crise')).toBe('c2');

    const recharge = pilotage.chargerCrises();
    http.expectOne(`${api}/crises/`).flush([{ id: 'c1', name: 'Inondation', is_open: true }]);
    await recharge;
    expect(pilotage.crise()?.name).toBe('Inondation');
  });

  it('la situation : chiffres, urgences, équipes engagées, et la main courante écrite sur place', async () => {
    TestBed.inject(PilotageService).crises.set([{ id: 'c1', name: 'Inondation de la Saône' } as never]);
    TestBed.inject(PilotageService).choisir('c1');
    const fixture = TestBed.createComponent(PilotageSituationComponent);
    fixture.detectChanges();
    await attendre();
    http.expectOne(`${api}/crises/c1/cellule/`).flush({ equipe_id: 'e', salon_room_id: null, salon_pret: false, compteurs: {
      dossiers_ressource_en_attente: 2, dossiers_moyen_en_attente: 1, dossiers_non_qualifies_en_attente: 1,
      retours_externes_non_lus: 0, institutions_acteur_en_attente: 0 } });
    http.expectOne(`${api}/dossiers/`).flush([
      dossier({ id: 'u', numero: 'D-7', titre: 'Personne âgée isolée', priorite: 'URGENTE', equipe_nom: 'Équipe Nord' }),
      dossier({ id: 'n', titre: 'Sacs de sable' }),
    ]);
    http.expectOne(`${api}/teams/`).flush([
      { id: 't1', name: 'Équipe Nord', assigned_crisis_ids: ['c1'], engagement_debut: '2026-11-21T06:00:00Z', mission_active_titre: 'Évacuation' },
      { id: 't2', name: 'Équipe Sud', assigned_crisis_ids: ['c1'], engagement_debut: null },
      { id: 't3', name: 'Ailleurs', assigned_crisis_ids: ['c9'], engagement_debut: '2026-11-21T06:00:00Z' },
    ]);
    const journal = http.expectOne(r => r.url === `${api}/journal-collectivite/`);
    expect(journal.request.params.get('crise')).toBe('c1');
    journal.flush([{ id: 'j1', crise: 'c1', auteur_nom: 'M. le maire', contenu: 'PC de crise ouvert', date_creation: '2026-11-21T07:00:00Z' }]);
    // Tableaux de situation (23/11/2026) : un bloc en échec s'affiche comme tel, sans bloquer les autres.
    http.expectOne(r => r.url === `${api}/pilotage/situation/`).flush({
      debut: null, calcule_le: '2026-11-23T10:00:00Z',
      veille: { vigilance_meteo: [{ departement: '69', aujourdhui: 'orange', demain: 'jaune' }], crues: [], stations: [], foyers_24h: 0, foudre_1h: 0 },
      accueil: { centres: [{ nom: 'Gymnase', capacite: 80, presents: 12 }], places: 80, presents: 12,
                 mises_en_securite: { declarations: 3, personnes: 7, cherchent_un_centre: 1 }, relogement: { en_recherche: 2, heberges: 1, reloges: 0 } },
      degats: { erreur: 'Indisponible pour le moment.' },
      moyens: { demandes_non_couvertes: [], offres_disponibles: [], renforts_24h: { demandes: 0, personnes: 0 } },
      radio: { canal_crise: { meshtastic: 'CriseSaone', meshcore: '#crisesaone' }, a_trier: 2,
               equipes: [{ nom: 'Équipe Nord', indicatif: 'NORD', transmissions: false, meshtastic: true, meshcore: false, dernier_message_radio: null }] },
    });
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('cherchent un centre');
    expect(fixture.nativeElement.textContent).toContain('@NORD');
    expect(fixture.nativeElement.textContent).toContain('2 message(s) radio à trier');
    expect(fixture.nativeElement.textContent).toContain('Indisponible pour le moment.');

    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('Inondation de la Saône');
    const chiffres = Array.from(fixture.nativeElement.querySelectorAll('.chiffre strong')).map((e: any) => e.textContent.replace(/\s+/g, ' ').trim());
    expect(chiffres).toEqual(['4', '1', '2', '1 / 2']);
    expect(texte).toContain('D-7 · Personne âgée isolée');
    expect(texte).toContain('Évacuation');
    expect(texte).not.toContain('Ailleurs');
    expect(texte).toContain('PC de crise ouvert');

    fixture.componentInstance.nouvelleEntree = 'Ouverture du gymnase comme centre d\'accueil';
    fixture.componentInstance.ecrire();
    const ecrit = http.expectOne(`${api}/journal-collectivite/`);
    expect(ecrit.request.method).toBe('POST');
    expect(ecrit.request.body).toEqual({ contenu: 'Ouverture du gymnase comme centre d\'accueil', crise: 'c1' });
    ecrit.flush({ id: 'j2', crise: 'c1', auteur_nom: 'Moi', contenu: 'Ouverture du gymnase comme centre d\'accueil',
                  date_creation: '2026-11-21T09:00:00Z' });
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.entrees li').textContent).toContain('gymnase');
    fixture.destroy();
  });

  it('les écrans du rail (Terrain ajouté, le standard nommé ainsi), et l\'administration à un geste', () => {
    spyOn(TestBed.inject(AuthService), 'canEnterAdminArea').and.returnValue(true);
    const fixture = TestBed.createComponent(PilotageLayoutComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/crises/`).flush([]);
    const onglets = Array.from(fixture.nativeElement.querySelectorAll('.rail a .libelle')).map((a: any) => a.textContent.trim());
    expect(onglets).toEqual(['Situation', 'Cellule', 'Terrain', 'Décisions', 'Carte', 'Dossiers', 'Standard', 'Alertes']);
    expect(fixture.nativeElement.querySelector('a.administration')).not.toBeNull();
    expect(PILOTAGE_ROUTES.map(r => r.path)).toEqual(['', 'situation', 'cellule', 'carte', 'dossiers', 'point', 'decisions', 'terrain', 'alertes']);
    fixture.destroy();
  });

  it('l\'horloge de crise : H+ en heures, puis en jours (23/11/2026)', () => {
    const fixture = TestBed.createComponent(PilotageLayoutComponent);
    const pilotage = TestBed.inject(PilotageService);
    const il_y_a = (min: number) => new Date(Date.now() - min * 60000).toISOString();
    pilotage.crises.set([{ id: 'c1', name: 'Crue', start_date: il_y_a(125.5) } as never]);
    pilotage.choisir('c1');
    expect(fixture.componentInstance.depuis()).toBe('2 h 05');
    pilotage.crises.set([{ id: 'c1', name: 'Crue', start_date: il_y_a(1440 + 190.5) } as never]);
    expect(fixture.componentInstance.depuis()).toBe('1 j 03 h');
    fixture.destroy();
  });

  it('le terrain : l\'alerte Danger en tête, prise en compte en un geste (23/11/2026)', async () => {
    const pilotage = TestBed.inject(PilotageService);
    pilotage.choisir('c1');
    pilotage.rafraichirTerrain();
    const alerte = { id: 'm1', auteur_nom: 'Léa', equipe_nom: 'Gier', type: 'DANGER', type_libelle: 'Danger', texte: 'Mur fissuré',
                     nombre: null, canal: 'MESHCORE', emis_le: '2026-11-23T10:00:00Z', dossier_numero: null, prioritaire: true };
    http.expectOne(r => r.url === `${api}/conversations/a-trier/`).flush({}, { status: 403, statusText: 'Forbidden' });
    http.expectOne(r => r.url === `${api}/cellule/points/`).flush({ cadence_h: 2, prochain: '2026-11-23T09:00:00Z', du: true, points: [] });
    http.expectOne(r => r.url === `${api}/messages-terrain/crise/`).flush({ alertes: [alerte], statuts: [{ ...alerte, statut: 'Danger signalé' }], derniers: [alerte] });
    expect(pilotage.pointDu()?.du).toBeTrue();
    expect(pilotage.alertesTerrain()).toBe(1);
    const promesse = pilotage.prendreEnCompte('m1');
    http.expectOne(`${api}/messages-terrain/m1/prendre-en-compte/`).flush({ ...alerte, pris_en_compte_le: '2026-11-23T10:01:00Z' });
    await promesse;
    http.expectOne(r => r.url === `${api}/conversations/a-trier/`).flush({}, { status: 403, statusText: 'Forbidden' });
    http.expectOne(r => r.url === `${api}/cellule/points/`).flush({ cadence_h: 2, prochain: null, du: false, points: [] });
    http.expectOne(r => r.url === `${api}/messages-terrain/crise/`).flush({ alertes: [], statuts: [], derniers: [] });
    expect(pilotage.alertesTerrain()).toBe(0);
    expect(pilotage.potCommun()).toBeNull();     // ce compte ne trie pas : pas de bloc
  });

  it('le pot commun : un message radio sans destinataire se range vers une équipe (23/11/2026)', async () => {
    const pilotage = TestBed.inject(PilotageService);
    pilotage.choisir('c1');
    pilotage.rafraichirTerrain();
    const pot = { conversation: 'k1', trie_par: 'REGULATION',
                  messages: [{ id: 'x1', texte: 'qui est sur la D88 ?', auteur: 'Léa', source: 'meshtastic', recu_par: 2, emis_le: '2026-11-23T10:00:00Z' }],
                  equipes: [{ id: 't1', nom: 'Alpha', indicatif: 'ALPHA' }] };
    http.expectOne(r => r.url === `${api}/conversations/a-trier/`).flush(pot);
    http.expectOne(r => r.url === `${api}/cellule/points/`).flush({}, { status: 403, statusText: 'Forbidden' });
    http.expectOne(r => r.url === `${api}/messages-terrain/crise/`).flush({ alertes: [], statuts: [], derniers: [] });
    expect(pilotage.aTrier()).toBe(1);
    const promesse = pilotage.ranger('x1', { equipe: 't1' });
    const req = http.expectOne(`${api}/conversations/a-trier/x1/ranger/`);
    expect(req.request.body).toEqual({ equipe: 't1' });
    req.flush({});
    await promesse;
    http.expectOne(r => r.url === `${api}/conversations/a-trier/`).flush({ ...pot, messages: [] });
    http.expectOne(r => r.url === `${api}/cellule/points/`).flush({}, { status: 403, statusText: 'Forbidden' });
    http.expectOne(r => r.url === `${api}/messages-terrain/crise/`).flush({ alertes: [], statuts: [], derniers: [] });
    expect(pilotage.aTrier()).toBe(0);
  });

  it('les alertes : la fiche s\'ouvre et l\'alerte passe lue', async () => {
    const fixture = TestBed.createComponent(PilotageAlertesComponent);
    fixture.detectChanges();
    await attendre();
    http.expectOne(`${api}/notifications/`).flush([
      { id: 'n1', titre: 'Nouvelle demande d\'hébergement', message: 'Famille de 4 personnes', lu: false,
        date_creation: '2026-11-21T08:00:00Z', details: [{ libelle: 'Commune', valeur: 'Mâcon' }] },
    ]);
    fixture.detectChanges();
    (fixture.nativeElement.querySelector('button.tete') as HTMLButtonElement).click();
    const lu = http.expectOne(`${api}/notifications/n1/`);
    expect(lu.request.body).toEqual({ lu: true });
    lu.flush({});
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Famille de 4 personnes');
    expect(fixture.nativeElement.textContent).toContain('Mâcon');
    fixture.destroy();
  });

  it('réservé aux rôles institutionnels : les autres vont sur Terrain', async () => {
    const auth = TestBed.inject(AuthService);
    spyOn(auth, 'fetchMe').and.returnValue(of({} as unknown as User));
    const institutionnel = spyOn(auth, 'isInstitutionalEffective').and.returnValue(false);
    const decision = async () => {
      const r = TestBed.runInInjectionContext(() => pilotageGuard({} as never, {} as never));
      return isObservable(r) ? firstValueFrom(r as Observable<boolean | UrlTree>) : r;
    };
    expect((await decision() as UrlTree).toString()).toBe('/terrain');
    institutionnel.and.returnValue(true);
    expect(await decision()).toBeTrue();
    expect(TestBed.inject(Router)).toBeTruthy();
  });
});
