import { TestBed } from '@angular/core/testing';
import { HttpTestingController } from '@angular/common/http/testing';
import { environment } from '../../../../environments/environment';
import { fournisseursDeTest } from '../../../testing/test-providers';
import { Team } from '../../../shared/models/team.model';
import { CanalRadioEquipeComponent } from './canal-radio-equipe.component';
import { TeamsComponent } from '../teams.component';

const api = `${environment.apiUrl}/teams/e1`;

const equipe = (): Team => ({
  id: 'e1', name: 'Radio', indicatif: 'RADIO',
  canaux_radio: {
    meshtastic: { nom: 'AC-RADIO', personnalise: false, cle_fournie: false, repris: false, empreinte: 'AB12CD34', actif: true, sur_passerelle: false },
    meshcore: { nom: 'ADRA42', personnalise: true, cle_fournie: true, repris: false, empreinte: 'FFEE0011', actif: true, sur_passerelle: false },
  },
} as Team);

describe('Canal radio de l’équipe (25/11/2026)', () => {
  let http: HttpTestingController;

  function creer(peutGerer = true) {
    TestBed.configureTestingModule({ providers: [...fournisseursDeTest()] });
    http = TestBed.inject(HttpTestingController);
    const fixture = TestBed.createComponent(CanalRadioEquipeComponent);
    fixture.componentRef.setInput('equipe', equipe());
    fixture.componentRef.setInput('peutGerer', peutGerer);
    fixture.detectChanges();
    return fixture;
  }

  it('montre le canal par défaut et le canal de la structure, jamais de clé ; pas de régénération d’une clé fournie', () => {
    const page = creer().nativeElement as HTMLElement;
    const mt = page.querySelector('[data-protocole="MESHTASTIC"]')!.textContent!;
    const mc = page.querySelector('[data-protocole="MESHCORE"]')!.textContent!;
    expect(mt).toContain('AC-RADIO');
    expect(mt).toContain('par défaut');
    expect(mt).toContain('Régénérer la clé');
    expect(mc).toContain('ADRA42');
    expect(mc).toContain('fournie par la structure');
    expect(mc).toContain('FFEE0011');
    expect(mc).not.toContain('Régénérer la clé');
    expect(mc).toContain('Revenir au canal par défaut');
  });

  it('sans droit de gestion, aucun bouton', () => {
    const page = creer(false).nativeElement as HTMLElement;
    expect(page.querySelector('button')).toBeNull();
  });

  it('propose d’abord de reprendre un canal de la passerelle, puis l’enregistre', () => {
    const fixture = creer();
    const composant = fixture.componentInstance;
    composant.ouvrir('MESHCORE');
    http.expectOne(`${api}/canaux-passerelle/`).flush({
      canaux: [{ id: 'c9', protocole: 'MESHCORE', nom: 'ADRA-INT', passerelle: 'Passerelle ADRASEC', public: false, deja_le_notre: false, empreinte: '01020304' }],
      entendus_sans_cle: 2,
    });
    fixture.detectChanges();
    expect(composant.mode).toBe('passerelle');
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('2 canal(aux) entendu(s)');

    const emis: unknown[] = [];
    composant.modifie.subscribe(e => emis.push(e));
    composant.reprendre = 'c9';
    composant.enregistrer();
    const requete = http.expectOne(`${api}/canal-radio/`);
    expect(requete.request.body).toEqual({ protocole: 'MESHCORE', reprendre: 'c9' });
    requete.flush({ canaux_radio: equipe().canaux_radio, indicatif: 'RADIO' });
    expect(emis.length).toBe(1);
  });

  it('notre nom et notre clé : la clé part une fois, puis le champ est vidé', () => {
    const fixture = creer();
    const composant = fixture.componentInstance;
    composant.ouvrir('MESHTASTIC');
    http.expectOne(`${api}/canaux-passerelle/`).flush({ canaux: [], entendus_sans_cle: 0 });
    expect(composant.mode).toBe('notre-cle');
    composant.nom = 'ADRA42';
    composant.cle = 'ABEiM0RVZneImaq7zN3u/w==';
    composant.enregistrer();
    const requete = http.expectOne(`${api}/canal-radio/`);
    expect(requete.request.body).toEqual({ protocole: 'MESHTASTIC', nom: 'ADRA42', cle: 'ABEiM0RVZneImaq7zN3u/w==', en_clair: false });
    requete.flush({ canaux_radio: equipe().canaux_radio, indicatif: 'RADIO' });
    expect(composant.cle).toBe('');
  });

  it('une erreur du serveur est montrée telle quelle', () => {
    const fixture = creer();
    const composant = fixture.componentInstance;
    composant.ouvrir('MESHCORE');
    http.expectOne(`${api}/canaux-passerelle/`).flush({ canaux: [], entendus_sans_cle: 0 });
    composant.mode = 'cle-generee';
    composant.nom = 'ADRA42';
    composant.enregistrer();
    http.expectOne(`${api}/canal-radio/`).flush({ error: 'Le canal « ADRA42 » est déjà celui d’une autre équipe.' }, { status: 400, statusText: 'Bad Request' });
    fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[role="alert"]')?.textContent).toContain('autre équipe');
  });

  it('l’indicatif proposé à la création suit la règle du serveur', () => {
    expect(TeamsComponent.proposerIndicatif('Équipe Alpha')).toBe('ALPHA');
    expect(TeamsComponent.proposerIndicatif('Bénévoles — Rive-de-Gier')).toBe('BENEVO');
    expect(TeamsComponent.proposerIndicatif('X')).toBe('');
  });
});
