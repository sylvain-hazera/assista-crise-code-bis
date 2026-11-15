import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { VeilleComponent } from './veille.component';
import { environment } from '../../../environments/environment';
import {
  EvenementRoutier, EvenementsRoutiers, MeteoForets, ObservationMeteo, ObservationsMeteo,
  RestrictionsEau, RisqueAvalanche, StationCarburant, StationsCarburant, VigilanceCrues, VigilanceDepartement,
  VigilanceMeteo, ZonesBrulees,
} from '../../shared/models/veille.model';

const api = environment.apiUrl;

function departement(code: string, nom: string, couleurJ: number, couleurJ1 = 1): VigilanceDepartement {
  return {
    departement_code: code, nom, couleur_j: couleurJ, couleur_j1: couleurJ1,
    detail: {
      J: {
        debut: '2026-11-15T09:00:00Z', fin: '2026-11-15T23:00:00Z', couleur: couleurJ,
        phenomenes: couleurJ >= 2 ? [{
          id: 1, couleur: couleurJ,
          periodes: [{ debut: '2026-11-15T14:00:00Z', fin: '2026-11-15T22:00:00Z', couleur: couleurJ }],
        }] : [],
      },
      J1: { debut: '2026-11-15T23:00:00Z', fin: '2026-11-16T23:00:00Z', couleur: couleurJ1, phenomenes: [] },
    },
    bulletin: [{ rubrique: 'Situation', alea: '', titre: 'Faits nouveaux', lignes: ['Rafales à 110 km/h.'] }],
    publie_le: '2026-11-15T09:00:19Z', releve_le: '2026-11-15T09:10:00Z',
  };
}

const VIGILANCE: VigilanceMeteo = {
  disponible: true, source: 'Météo-France', perime: false,
  releve_le: '2026-11-15T09:10:00Z', publie_le: '2026-11-15T09:00:19Z',
  phenomenes: { '1': 'vent violent', '4': 'crues' },
  couleurs: { '1': 'vert', '2': 'jaune', '3': 'orange', '4': 'rouge' },
  france: departement('FRA', 'France', 3),
  mon_departement: departement('42', 'Loire', 3),
  departements: [departement('42', 'Loire', 3), departement('69', 'Rhône', 2)],
  vignettes: ['J', 'J1'],
};

const ENTETE = {
  source: 'Source de test', releve_le: '2026-11-15T09:10:00Z', perime: false,
  centre: { latitude: 45.44, longitude: 4.39 }, rayon_km: 30, emprise_connue: true, tronque: false,
};

function evenement(reference: string, categorie: EvenementRoutier['categorie'], libelle: string): EvenementRoutier {
  return {
    reference, categorie, categorie_libelle: libelle, natures: [libelle], gravite: 'high',
    route: 'N88', commune_nom: 'Saint-Chamond', description: 'Poids lourd couché.', localisation: '',
    gestionnaire: 'DIR Centre-Est', departement_code: '42', latitude: 45.47, longitude: 4.51,
    latitude_fin: null, longitude_fin: null, debut: '2026-11-15T08:00:00Z', fin: null,
    mis_a_jour_le: '2026-11-15T09:00:00Z',
  };
}

const ROUTES: EvenementsRoutiers = {
  ...ENTETE,
  resultats: [evenement('f1', 'FERMETURE', 'Route fermée'), evenement('t1', 'TRAVAUX', 'Travaux')],
};

function station(reference: string, disponibles: string[], ruptures: string[]): StationCarburant {
  return {
    reference, adresse: '1 rue de la Veille', ville: `Ville ${reference}`, code_postal: '42000',
    latitude: 45.44, longitude: 4.39, carburants_disponibles: disponibles,
    ruptures_temporaires: ruptures, ruptures_definitives: [], prix: {}, automate_24_24: true,
    mis_a_jour_le: new Date().toISOString(),
  };
}

const STATIONS: StationsCarburant = {
  ...ENTETE,
  bilan: { total: 3, en_rupture: 2, a_sec: 1 },
  resultats: [station('pleine', ['Gazole'], []), station('partielle', ['Gazole'], ['E10']),
              station('vide', [], ['Gazole', 'E10'])],
};

function mesure(station: string, nom: string, champs: Partial<ObservationMeteo> = {}): ObservationMeteo {
  return {
    station, nom, altitude_m: 395, latitude: 45.53, longitude: 4.29, distance_km: 12.4,
    mesure_le: '2026-11-15T09:12:00Z', temperature_c: 16.4, humidite_pct: 59, vent_kmh: 23,
    vent_direction: 180, rafale_kmh: 32, pluie_6min_mm: 0, neige_cm: null,
    heure_le: '2026-11-15T09:00:00Z', pluie_1h_mm: 1.5, rafale_1h_kmh: 46, pluie_24h_mm: 6.5,
    heures_cumulees: 7, ...champs,
  };
}

const OBSERVATIONS: ObservationsMeteo = {
  ...ENTETE,
  resultats: [
    mesure('42005001', 'ST ETIENNE-BOUTHEON'),
    mesure('42101001', 'PILAT GRAIX', { rafale_1h_kmh: 96 }),
    mesure('42039003', 'CHALMAZEL', { vent_kmh: null, vent_direction: null, rafale_kmh: null, rafale_1h_kmh: null }),
  ],
};

const CRUES: VigilanceCrues = {
  ...ENTETE,
  resultats: [
    { code: 'LO13', nom: 'Gier', niveau: 3, couleur: 'orange', publie_le: '2026-11-15T08:55:47Z' },
    { code: 'LO12', nom: 'Furan', niveau: 1, couleur: 'vert', publie_le: '2026-11-15T08:55:47Z' },
  ],
};

const EAU: RestrictionsEau = {
  source: 'VigiEau', releve_le: '2026-11-15T09:10:00Z', perime: false, date_donnees: '2026-11-14',
  libelles: { vigilance: 'Vigilance', alerte: 'Alerte', alerte_renforcee: 'Alerte renforcée', crise: 'Crise' },
  mon_departement: {
    departement_code: '42', nom: 'Loire', niveau: 'alerte_renforcee',
    niveau_superficielle: 'alerte_renforcee', niveau_souterraine: 'alerte', niveau_potable: '',
  },
  departements: [],
};

const FORETS_HORS_SAISON: MeteoForets = {
  source: 'Météo-France', releve_le: '2026-11-15T09:10:00Z', perime: false,
  en_saison: false, compris: true,
  libelles: { '1': 'faible', '2': 'modéré', '3': 'élevé', '4': 'très élevé' },
  mon_departement: null, departements: [],
};

const FEUX: ZonesBrulees = {
  ...ENTETE,
  resultats: [{
    reference: '288759', date_feu: '2026-10-16T12:19:00Z', commune_nom: 'Pélussin',
    departement_nom: 'Loire', surface_ha: 42, latitude: 45.41, longitude: 4.68, distance_km: 23.4,
  }],
};

const EN_PLAINE: RisqueAvalanche = {
  ...ENTETE, libelles: { '1': 'faible', '2': 'limité', '3': 'marqué', '4': 'fort', '5': 'très fort' }, resultats: [],
};

describe('VeilleComponent', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [VeilleComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  function demarrer(reponses: { vigilance?: VigilanceMeteo; routes?: EvenementsRoutiers; stations?: StationsCarburant;
                                observations?: ObservationsMeteo; crues?: VigilanceCrues; eau?: RestrictionsEau;
                                forets?: MeteoForets; feux?: ZonesBrulees; avalanche?: RisqueAvalanche } = {}) {
    const fixture = TestBed.createComponent(VeilleComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/vigilance-meteo/`).flush(reponses.vigilance ?? VIGILANCE);
    http.expectOne(`${api}/restrictions-eau/`).flush(reponses.eau ?? EAU);
    http.expectOne(`${api}/meteo-forets/`).flush(reponses.forets ?? FORETS_HORS_SAISON);
    http.expectOne(r => r.url === `${api}/vigilance-crues/`).flush(reponses.crues ?? CRUES);
    http.expectOne(r => r.url === `${api}/risque-avalanche/`).flush(reponses.avalanche ?? EN_PLAINE);
    http.expectOne(r => r.url === `${api}/zones-brulees/`).flush(reponses.feux ?? FEUX);
    http.expectOne(r => r.url === `${api}/observations-meteo/`).flush(reponses.observations ?? OBSERVATIONS);
    http.expectOne(r => r.url === `${api}/evenements-routiers/`).flush(reponses.routes ?? ROUTES);
    http.expectOne(r => r.url === `${api}/stations-carburant/`).flush(reponses.stations ?? STATIONS);
    fixture.detectChanges();
    return fixture;
  }

  const texte = (fixture: any) => (fixture.nativeElement as HTMLElement).textContent ?? '';

  it('ne parle qu’à notre serveur', () => {
    const fixture = TestBed.createComponent(VeilleComponent);
    fixture.detectChanges();

    const demandes = http.match(() => true);
    expect(demandes.length).toBe(9);
    // LE test de cette page : aucun appel ne sort vers un service tiers.
    for (const demande of demandes) expect(demande.request.url.startsWith(api)).toBeTrue();
    const images: HTMLImageElement[] = Array.from(fixture.nativeElement.querySelectorAll('img'));
    expect(images.every(image => image.src.includes('/vigilance-meteo/vignette/'))).toBeTrue();
  });

  it('affiche la vigilance du département, sa couleur et ses horaires', () => {
    const fixture = demarrer();
    const bloc: HTMLElement = fixture.nativeElement.querySelector('.mon-departement');

    expect(bloc.getAttribute('data-couleur')).toBe('3');
    expect(bloc.textContent).toContain('Loire (42)');
    expect(bloc.textContent).toContain('Vent violent');
    expect(bloc.textContent).toContain('orange');
    expect(bloc.querySelector('.horaire')).not.toBeNull();
    expect(bloc.textContent).toContain('Rafales à 110 km/h.');
  });

  it('liste les départements en vigilance et sert les deux cartes nationales depuis le serveur', () => {
    const fixture = demarrer();
    const lignes = fixture.nativeElement.querySelectorAll('.liste-nationale tbody tr');
    const images: HTMLImageElement[] = Array.from(fixture.nativeElement.querySelectorAll('.vignettes img'));

    expect(lignes.length).toBe(2);
    expect(images.map(image => image.getAttribute('src'))).toEqual([
      `${api}/vigilance-meteo/vignette/J/`, `${api}/vigilance-meteo/vignette/J1/`]);
    expect(images.every(image => !!image.alt)).toBeTrue();
  });

  it('charge le détail d’un autre département à la demande', () => {
    const fixture = demarrer();
    const bouton: HTMLButtonElement = fixture.nativeElement.querySelectorAll('.liste-nationale button')[1];
    bouton.click();

    const demande = http.expectOne(r => r.url === `${api}/vigilance-meteo/` && r.params.get('departement') === '69');
    demande.flush({ ...VIGILANCE, mon_departement: departement('69', 'Rhône', 2) });
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.mon-departement').textContent).toContain('Rhône (69)');
  });

  it('dit qu’un relevé est ancien au lieu de le présenter comme actuel', () => {
    const fixture = demarrer({ vigilance: { ...VIGILANCE, perime: true } });

    expect(texte(fixture)).toContain('Relevé ancien');
    expect(texte(fixture)).toContain('vigilance.meteofrance.fr');
  });

  it('dit qu’aucun relevé n’existe encore, sans rien inventer', () => {
    const vide: VigilanceMeteo = {
      ...VIGILANCE, disponible: false, france: null, mon_departement: null, departements: [], vignettes: [],
    };
    const fixture = demarrer({ vigilance: vide });

    expect(texte(fixture)).toContain('Aucun relevé pour l\'instant');
    expect(fixture.nativeElement.querySelector('.mon-departement')).toBeNull();
  });

  it('affiche les mesures des stations et fait ressortir une rafale forte', () => {
    const fixture = demarrer();
    const lignes = Array.from(fixture.nativeElement.querySelectorAll('table.mesures tbody tr')) as HTMLElement[];

    expect(lignes.length).toBe(3);
    expect(lignes[0].textContent).toContain('ST ETIENNE-BOUTHEON');
    expect(lignes[0].textContent).toContain('16.4 °C');
    expect(lignes[0].textContent).toContain('23 km/h S');
    // La rafale affichée est la plus forte connue : celle de l'heure, pas celle de l'instant.
    expect(lignes[0].textContent).toContain('46 km/h');
    expect(lignes[0].textContent).toContain('sur 7 h');
    expect(lignes[0].classList.contains('remarquable')).toBeFalse();
    expect(lignes[1].classList.contains('remarquable')).toBeTrue();
    expect(lignes[1].textContent).toContain('96 km/h');
  });

  it('n’affiche jamais un vent nul pour une station qui ne mesure pas le vent', () => {
    const fixture = demarrer();
    const cellules = fixture.nativeElement.querySelectorAll('table.mesures tbody tr')[2].querySelectorAll('td');

    expect(cellules[3].textContent.trim()).toBe('—');
    expect(cellules[4].textContent.trim()).toBe('—');
    expect(fixture.componentInstance.rafale(OBSERVATIONS.resultats[2])).toBeNull();
  });

  it('liste les cours d’eau surveillés, le plus préoccupant d’abord, et rappelle la limite de Vigicrues', () => {
    const fixture = demarrer();
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-crues"]');
    const lignes = Array.from(bloc.querySelectorAll('.troncons li')) as HTMLElement[];

    expect(lignes.map(li => [li.querySelector('.couleur')!.textContent!.trim(), li.querySelector('strong')!.textContent]))
      .toEqual([['orange', 'Gier'], ['vert', 'Furan']]);
    expect(lignes[0].querySelector('.couleur')!.getAttribute('data-couleur')).toBe('3');
    // Un ruisseau absent de la liste n'est pas un ruisseau sans risque.
    expect(bloc.textContent).toContain('ne surveille que les principaux cours d\'eau');
  });

  it('donne le niveau de restriction d’eau du département et dit qu’il ne vaut pas pour toute commune', () => {
    const fixture = demarrer();
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-eau"]');

    expect(bloc.querySelector('.eau-departement')!.getAttribute('data-rang')).toBe('3');
    expect(bloc.textContent).toContain('Alerte renforcée');
    expect(bloc.textContent).toContain('Aucune restriction');          // l'eau potable
    expect(bloc.textContent).toContain('ne s\'applique pas forcément à votre commune');
    expect(bloc.querySelector('a[href="https://vigieau.gouv.fr"]')).not.toBeNull();
  });

  it('dit « hors saison » pour la météo des forêts au lieu de « rien à signaler »', () => {
    const fixture = demarrer();
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-feux"]');

    expect(bloc.textContent).toContain('Hors saison');
    expect(bloc.textContent).toContain('Pélussin');
    expect(bloc.textContent).toContain('42 ha');
    expect(bloc.textContent).toContain('Ce n\'est pas une alerte');
  });

  it('en saison, donne le danger de feu du département', () => {
    const fixture = demarrer({ forets: {
      ...FORETS_HORS_SAISON, en_saison: true,
      mon_departement: { departement_code: '42', nom: 'Loire', niveau_demain: 3, niveau_apres_demain: 4 },
      departements: [{ departement_code: '13', nom: 'Bouches-du-Rhône', niveau_demain: 4, niveau_apres_demain: 4 }],
    } });
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-feux"]');

    expect(bloc.textContent).toContain('élevé');
    expect(bloc.textContent).toContain('très élevé');
    expect(bloc.textContent).toContain('Bouches-du-Rhône');
  });

  it('signale une carte de danger de feu que le serveur n’a pas su lire', () => {
    const fixture = demarrer({ forets: { ...FORETS_HORS_SAISON, en_saison: true, compris: false } });

    expect(texte(fixture)).toContain('le serveur n\'a pas su la lire');
  });

  it('ne parle d’avalanche qu’aux territoires qui ont un massif à portée', () => {
    expect(demarrer().nativeElement.querySelector('section[aria-labelledby="titre-avalanche"]')).toBeNull();
  });

  it('en montagne, donne l’indice du massif, celui du lendemain et le résumé du bulletin', () => {
    const fixture = demarrer({ avalanche: { ...EN_PLAINE, resultats: [
      { massif_code: 1, nom: 'Chablais', chaine: 'Alpes du Nord', departement_nom: 'Haute-Savoie',
        risque: 4, risque_demain: 3, commentaire: 'Indice de risque fort.',
        resume: 'Départs spontanés : nombreux', publie_le: '2026-11-14T15:00:00Z', valide_jusqu_a: '2026-11-15T17:00:00Z' },
      { massif_code: 2, nom: 'Aravis', chaine: 'Alpes du Nord', departement_nom: 'Haute-Savoie',
        risque: null, risque_demain: null, commentaire: '', resume: '', publie_le: null, valide_jusqu_a: null },
    ] } });
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-avalanche"]');
    const lignes = bloc.querySelectorAll('.massifs li');

    expect(lignes[0].querySelector('.avalanche')!.getAttribute('data-niveau')).toBe('4');
    expect(lignes[0].textContent).toContain('fort');
    expect(lignes[0].textContent).toContain('Demain : marqué');
    expect(lignes[0].textContent).toContain('Départs spontanés : nombreux');
    // Un massif sans bulletin le dit, au lieu de passer pour un massif sans risque.
    expect(lignes[1].textContent).toContain('pas de bulletin');
    expect(bloc.textContent).toContain('ne dit rien d\'un couloir ou d\'une pente');
  });

  it('montre d’abord les fermetures et garde les travaux sur demande', () => {
    const fixture = demarrer();
    const liste = () => Array.from(fixture.nativeElement.querySelectorAll('.evenements li')) as HTMLElement[];

    expect(liste().map(li => li.getAttribute('data-categorie'))).toEqual(['FERMETURE']);

    fixture.componentInstance.avecTravaux = true;
    fixture.detectChanges();
    expect(liste().map(li => li.getAttribute('data-categorie'))).toEqual(['FERMETURE', 'TRAVAUX']);
  });

  it('rappelle que le réseau national n’est pas toutes les routes', () => {
    const fixture = demarrer({ routes: { ...ROUTES, resultats: [] } });

    expect(texte(fixture)).toContain('Aucune fermeture');
    // Une liste vide ne doit pas se lire comme « toutes les routes sont ouvertes ».
    expect(texte(fixture)).toContain('Réseau routier national seulement');
  });

  it('ne montre par défaut que les stations en rupture, et signale celles à sec', () => {
    const fixture = demarrer();
    const lignes = () => Array.from(fixture.nativeElement.querySelectorAll('section[aria-labelledby="titre-carburant"] tbody tr')) as HTMLElement[];

    expect(lignes().length).toBe(2);
    expect(lignes().filter(ligne => ligne.classList.contains('a-sec')).length).toBe(1);
    expect(fixture.nativeElement.querySelector('.bilan').textContent).toContain('3');

    fixture.componentInstance.toutesLesStations = true;
    fixture.detectChanges();
    expect(lignes().length).toBe(3);
  });

  it('redemande routes et stations quand le rayon change', () => {
    const fixture = demarrer();
    fixture.componentInstance.changerRayon(60);

    http.expectOne(r => r.url === `${api}/vigilance-crues/` && r.params.get('rayon_km') === '60').flush(CRUES);
    http.expectOne(r => r.url === `${api}/risque-avalanche/` && r.params.get('rayon_km') === '60').flush(EN_PLAINE);
    http.expectOne(r => r.url === `${api}/zones-brulees/` && r.params.get('rayon_km') === '60').flush(FEUX);
    http.expectOne(r => r.url === `${api}/observations-meteo/` && r.params.get('rayon_km') === '60').flush(OBSERVATIONS);
    http.expectOne(r => r.url === `${api}/evenements-routiers/` && r.params.get('rayon_km') === '60').flush(ROUTES);
    http.expectOne(r => r.url === `${api}/stations-carburant/` && r.params.get('rayon_km') === '60').flush(STATIONS);
    expect(fixture.componentInstance.rayonKm).toBe(60);
  });

  it('explique pourquoi rien ne s’affiche pour un compte sans commune', () => {
    const sansEmprise = { ...ENTETE, emprise_connue: false, centre: null, rayon_km: null };
    const fixture = demarrer({
      crues: { ...sansEmprise, resultats: [] },
      feux: { ...sansEmprise, resultats: [] },
      observations: { ...sansEmprise, resultats: [] },
      routes: { ...sansEmprise, resultats: [] },
      stations: { ...sansEmprise, bilan: { total: 0, en_rupture: 0, a_sec: 0 }, resultats: [] },
    });

    expect(texte(fixture)).toContain('rattaché à aucune commune');
  });

  it('affiche une erreur par bloc sans faire tomber les autres', () => {
    const fixture = TestBed.createComponent(VeilleComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/vigilance-meteo/`).flush(VIGILANCE);
    http.expectOne(`${api}/restrictions-eau/`).flush(EAU);
    http.expectOne(`${api}/meteo-forets/`).flush(FORETS_HORS_SAISON);
    http.expectOne(r => r.url === `${api}/vigilance-crues/`).flush(CRUES);
    http.expectOne(r => r.url === `${api}/risque-avalanche/`).flush(EN_PLAINE);
    http.expectOne(r => r.url === `${api}/zones-brulees/`).flush(FEUX);
    http.expectOne(r => r.url === `${api}/observations-meteo/`).flush(OBSERVATIONS);
    http.expectOne(r => r.url === `${api}/evenements-routiers/`).flush('', { status: 500, statusText: 'Erreur' });
    http.expectOne(r => r.url === `${api}/stations-carburant/`).flush(STATIONS);
    fixture.detectChanges();

    expect(texte(fixture)).toContain('Impossible de lire les événements routiers');
    expect(fixture.nativeElement.querySelector('.mon-departement')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.bilan')).not.toBeNull();
  });
});
