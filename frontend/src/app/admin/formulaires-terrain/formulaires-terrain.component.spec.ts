import { TestBed } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { FormulairesTerrainComponent } from './formulaires-terrain.component';
import { FormulaireTerrainService } from '../../services/formulaire-terrain.service';
import { fournisseursDeTest } from '../../testing/test-providers';
import { FormulaireTerrain } from '../../shared/models/formulaire-terrain.model';

/** Formulaires de terrain : ce que l'écran pose comme question, et ce qu'il envoie. */
describe('FormulairesTerrainComponent', () => {
  let composant: FormulairesTerrainComponent;
  let service: FormulaireTerrainService;

  const FORMULAIRE = {
    id: 'f1', titre: 'Logements', description: '', actif: true, peut_gerer: true, nb_reponses: 0,
    questions: [
      { cle: 'habitable', libelle: 'Habitable ?', type: 'OUI_NON', obligatoire: true },
      { cle: 'a_reloger', libelle: 'À reloger', type: 'NOMBRE', obligatoire: true, si: { cle: 'habitable', valeur: false } },
      { cle: 'degats', libelle: 'Dégâts', type: 'CHOIX_MULTIPLE', obligatoire: false, options: ['Toiture', 'Eau'] },
    ],
  } as unknown as FormulaireTerrain;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [...fournisseursDeTest(), provideHttpClientTesting()],
      imports: [FormulairesTerrainComponent],
    });
    composant = TestBed.createComponent(FormulairesTerrainComponent).componentInstance;
    service = TestBed.inject(FormulaireTerrainService);
    composant.ouvrirSaisie(FORMULAIRE);
  });

  afterEach(() => TestBed.inject(HttpTestingController).match(() => true));

  it('ne pose une question conditionnelle que si sa condition est remplie', () => {
    const relogement = FORMULAIRE.questions[1];
    expect(composant.estPosee(relogement)).toBeFalse();
    composant.saisie['habitable'] = false;
    expect(composant.estPosee(relogement)).toBeTrue();
  });

  it('n\'envoie ni les questions masquées ni les réponses vides', async () => {
    const envoyees: any[] = [];
    spyOn(service, 'repondre').and.callFake(async (r) => { envoyees.push(r); return 'envoyee'; });
    spyOn(service, 'enAttente').and.resolveTo(0);
    composant.saisie = { habitable: true, a_reloger: 4, degats: [] };

    await composant.envoyerReponse();

    expect(envoyees[0].donnees).toEqual({ habitable: true });
    expect(envoyees[0].identifiant_client).toMatch(/^[0-9a-f-]{36}$/);
    expect(composant.saisie).toEqual({});               // prêt pour la suivante
  });

  it('dit clairement qu\'une réponse attend le retour du réseau', async () => {
    spyOn(service, 'repondre').and.resolveTo('en_attente');
    spyOn(service, 'enAttente').and.resolveTo(1);
    composant.saisie = { habitable: true };

    await composant.envoyerReponse();

    expect(composant.message).toContain('Pas de réseau');
    expect(composant.enAttente).toBe(1);
  });

  it('garde la saisie quand le serveur refuse la réponse', async () => {
    spyOn(service, 'repondre').and.rejectWith({ error: { detail: '« À reloger » attend une réponse.' } });
    composant.saisie = { habitable: false };

    await composant.envoyerReponse();

    expect(composant.erreur).toBe('« À reloger » attend une réponse.');
    expect(composant.saisie).toEqual({ habitable: false });
  });

  it('coche et décoche dans une liste à choix multiples', () => {
    composant.cocher('degats', 'Eau');
    composant.cocher('degats', 'Toiture');
    composant.cocher('degats', 'Eau');
    expect(composant.saisie['degats']).toEqual(['Toiture']);
  });

  it('ne propose en condition qu\'une question déjà enregistrée, placée avant', () => {
    composant.composer(FORMULAIRE);
    expect(composant.conditionsPossibles(0)).toEqual([]);
    expect(composant.conditionsPossibles(2).map(q => q.cle)).toEqual(['habitable']);
  });
});
