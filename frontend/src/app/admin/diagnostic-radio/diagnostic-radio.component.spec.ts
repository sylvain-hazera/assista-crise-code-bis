import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { DiagnosticRadioComponent } from './diagnostic-radio.component';
import { environment } from '../../../environments/environment';
import { DiagnosticLiaisons } from '../../shared/models/administration-meshtastic.model';

const VIDE: DiagnosticLiaisons = {
  sens_unique: [], desequilibrees: [], inaudibles: [], sourds: [],
  puissance_connue: false, noeuds_puissance_connue: 0,
  calcule_le: '2026-11-07T10:00:00Z',
};

const UN_SOURD: DiagnosticLiaisons['sourds'][number] = {
  node_num: 0x1a2b3c4d, nom: 'Relais Pilat', ecart_db: 12.5, nb_voisins: 3, nb_concordantes: 3,
  puissance_connue: false,
  mesures: [
    {
      partenaire: 0x2000, nom_partenaire: 'Mairie', entendu_chez_partenaire: 10,
      entendu_chez_lui: -2.5, ecart_db: 12.5, borne: false, correction_db: 0,
      puissance_connue: false,
    },
    {
      partenaire: 0x3000, nom_partenaire: 'Caserne', entendu_chez_partenaire: 8,
      entendu_chez_lui: null, ecart_db: 25.5, borne: true, correction_db: 0,
      puissance_connue: false,
    },
  ],
};

describe('DiagnosticRadioComponent', () => {
  let http: HttpTestingController;
  const url = `${environment.apiUrl}/contacts-meshtastic/analyse-liaisons/`;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [DiagnosticRadioComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function demarrer(reponse: DiagnosticLiaisons = VIDE) {
    const fixture = TestBed.createComponent(DiagnosticRadioComponent);
    fixture.detectChanges();
    http.expectOne(url).flush(reponse);
    // Le second detectChanges n'est pas superflu : sans lui le gabarit est encore celui de
    // l'état « calcul en cours », et toute assertion sur le texte rendu lit la page d'avant.
    fixture.detectChanges();
    return fixture;
  }

  it('calcule au chargement et une seule fois', () => {
    const composant = demarrer().componentInstance;
    expect(composant.chargement).toBeFalse();
    expect(composant.diagnostic).toEqual(VIDE);
    // Calcul lourd : jamais en boucle.
    http.expectNone(url);
  });

  it('recalcule seulement sur demande explicite', () => {
    const composant = demarrer().componentInstance;
    composant.calculer();
    const second = http.expectOne(url);
    expect(second.request.method).toBe('GET');
    second.flush({ ...VIDE, noeuds_puissance_connue: 2, puissance_connue: true });
    expect(composant.diagnostic?.noeuds_puissance_connue).toBe(2);
  });

  it('dit pourquoi un réseau sans anomalie peut aussi être un réseau sans assez de mesures', () => {
    const fixture = demarrer();
    expect(fixture.componentInstance.aucuneConclusion).toBeTrue();
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('au moins 3 réceptions');
  });

  it('avertit en toutes lettres quand aucune puissance n’est connue', () => {
    // Le point qui décide de la confiance à accorder : non corrigé, un nœud qui émet plus fort
    // que ses voisins peut passer pour sourd.
    const fixture = demarrer({ ...VIDE, sourds: [UN_SOURD] });
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).toContain('Aucune puissance d\'émission connue');
    expect(texte).toContain('non corrigé');
  });

  it('ne crie plus quand la puissance est connue', () => {
    const fixture = demarrer({
      ...VIDE, puissance_connue: true, noeuds_puissance_connue: 4,
      sourds: [{ ...UN_SOURD, puissance_connue: true }],
    });
    const texte = fixture.nativeElement.textContent as string;
    expect(texte).not.toContain('Aucune puissance');
    expect(texte).toContain('corrigé');
  });

  it('distingue une mesure réciproque d’une simple borne basse', () => {
    // Une borne basse dit « il l'a reçu sous son seuil », pas de combien : l'afficher comme une
    // mesure ferait croire à une précision qui n'existe pas.
    const composant = demarrer({ ...VIDE, sourds: [UN_SOURD] }).componentInstance;
    expect(composant.libelleMesure(UN_SOURD.mesures[0])).toBe('12.5 dB');
    expect(composant.libelleMesure(UN_SOURD.mesures[1])).toContain('au moins');
    expect(composant.libelleMesure(UN_SOURD.mesures[1])).toContain('jamais rapporté');
  });

  it('ne déplie les mesures d’un relais que sur demande', () => {
    const composant = demarrer({ ...VIDE, sourds: [UN_SOURD] }).componentInstance;
    expect(composant.sourdDeplie).toBeNull();
    composant.basculerSourd(UN_SOURD.node_num);
    expect(composant.sourdDeplie).toBe(UN_SOURD.node_num);
    composant.basculerSourd(UN_SOURD.node_num);
    expect(composant.sourdDeplie).toBeNull();
  });

  it('affiche l’origine de la preuve d’une liaison à sens unique', () => {
    // « voisinage » est plafonné à 10 voisins : la preuve est plus faible que « passerelle », et
    // l'interface doit le laisser voir.
    const fixture = demarrer({
      ...VIDE,
      sens_unique: [{
        preuve: 'voisinage', entend: 1, entendu: 2, nom_entend: 'A', nom_entendu: 'B',
        snr: 3, nombre: 7, sources: ['VOISINAGE'], distance_km: 4.2,
      }],
    });
    expect(fixture.nativeElement.textContent).toContain('voisinage');
  });

  it('explique un refus 403 au lieu d’une erreur générique', () => {
    const fixture = TestBed.createComponent(DiagnosticRadioComponent);
    fixture.detectChanges();
    http.expectOne(url).flush(null, { status: 403, statusText: 'Forbidden' });
    expect(fixture.componentInstance.erreur).toContain('institutionnels');
  });

  it('formate le numéro de nœud comme le reste du projet', () => {
    const composant = demarrer().componentInstance;
    expect(composant.hexa(0x1a2b3c4d)).toBe('!1a2b3c4d');
  });
});
