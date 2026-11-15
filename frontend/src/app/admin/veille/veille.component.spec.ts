import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter } from '@angular/router';

import { VeilleComponent } from './veille.component';
import { environment } from '../../../environments/environment';
import {
  ArretesCirculation, Circulation, TronconCirculation, HauteursEau, StationHydrometrique, NiveauMer, NiveauxMer, AntenneIndisponible, AntennesIndisponibles, QualiteAir, FoyersActifs, Radioactivite, Seismes, Volcans, EvenementRoutier, EvenementsRoutiers, MeteoForets, ObservationMeteo, ObservationsMeteo, RafalesPrevues, PrecipitationsHiver,
  RestrictionsEau, RisqueAvalanche, SanteUrgences, StationCarburant, StationsCarburant, VigilanceCrues, VigilanceDepartement,
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

/** Rafales prévues sur la commune : 36 km/h puis 60 à 80, puis 80 à 100 à partir de 18 h 15. */
const RAFALES: RafalesPrevues = {
  source: 'Météo-France', releve_le: '2026-11-15T17:05:00Z', perime: false, calcul: '2026-11-15T16:00:00Z',
  coins: [[-5.505, 51.505], [10.005, 51.505], [10.005, 40.995], [-5.505, 40.995]],
  echeances: ['2026-11-15T17:00:00Z', '2026-11-15T17:15:00Z', '2026-11-15T17:30:00Z'],
  legende: [40, 60, 80, 100, 120, 140].map(seuil => ({ a_partir_de_kmh: seuil, couleur: '#7c46cc' })),
  ici: {
    latitude: 45.44, longitude: 4.39, couvert: true, maximum_kmh: 80,
    paliers: [
      { echeance: '2026-11-15T17:00:00Z', a_partir_de_kmh: 0 },
      { echeance: '2026-11-15T17:15:00Z', a_partir_de_kmh: 60 },
      { echeance: '2026-11-15T17:30:00Z', a_partir_de_kmh: 80 },
    ],
  },
};
/** Sur la commune : rien, puis neige humide, puis pluie verglaçante à 17 h 30. */
const HIVER: PrecipitationsHiver = {
  source: 'Météo-France', releve_le: '2026-11-15T17:05:00Z', perime: false, calcul: '2026-11-15T16:00:00Z',
  coins: [[-5.505, 51.505], [10.005, 51.505], [10.005, 40.995], [-5.505, 40.995]],
  echeances: ['2026-11-15T17:00:00Z', '2026-11-15T17:15:00Z', '2026-11-15T17:30:00Z'],
  legende: [
    { cle: 'VERGLAS', libelle: 'Pluie ou bruine verglaçante', couleur: '#db2777' },
    { cle: 'NEIGE', libelle: 'Neige', couleur: '#38bdf8' },
    { cle: 'NEIGE_HUMIDE', libelle: 'Neige humide, pluie et neige mêlées', couleur: '#4f46e5' },
  ],
  ici: {
    latitude: 45.44, longitude: 4.39, couvert: true, pire: 'VERGLAS',
    familles: [
      { echeance: '2026-11-15T17:00:00Z', famille: '' },
      { echeance: '2026-11-15T17:15:00Z', famille: 'NEIGE_HUMIDE' },
      { echeance: '2026-11-15T17:30:00Z', famille: 'VERGLAS' },
    ],
  },
};
const HIVER_AU_SEC: PrecipitationsHiver = {
  ...HIVER, ici: { ...HIVER.ici!, pire: '', familles: HIVER.ici!.familles.map(f => ({ ...f, famille: '' as const })) },
};

const RAFALES_CALMES: RafalesPrevues = {
  ...RAFALES, ici: { ...RAFALES.ici!, maximum_kmh: 0, paliers: RAFALES.ici!.paliers.map(p => ({ ...p, a_partir_de_kmh: 0 })) },
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

/** Saint-Étienne, à 13 km : indice 2, et une dégradation annoncée à 4 dans la nuit. */
const AIR: QualiteAir = {
  ...ENTETE, source: 'Données météo fournies par OpenWeather',
  libelles: { 1: 'bon', 2: 'correct', 3: 'moyen', 4: 'mauvais', 5: 'très mauvais' },
  plus_proche: {
    code: '42218', nom: 'Saint-Étienne', departement: '42', indice: 2, libelle: 'correct',
    composants: { pm2_5: 4.1, pm10: 6, no2: 12.3, o3: 64.3, so2: 0.2, co: 131 },
    mesure_le: '2026-11-15T21:00:00Z', pire_24h: 4, pire_24h_libelle: 'mauvais', pire_24h_le: '2026-11-16T03:00:00Z',
    latitude: 45.44, longitude: 4.39, distance_km: 13.5,
  },
  resultats: [],
};
const AIR_VIDE: QualiteAir = { ...AIR, plus_proche: null };

const ANTENNE: AntenneIndisponible = {
  cle: 'Orange|0692290587', operateur: 'Orange', commune: 'Lyon', gravite: 'TOTALE', voix_hs: true, donnees_hs: true,
  technologies: { voix4g: 'HS', data4g: 'HS', data5g: 'HS', voix2g: 'OK' }, motif: 'INCIDENT',
  depuis: '2026-11-14T07:50:00Z', debut_declare: true, latitude: 45.755, longitude: 4.842, distance_km: 0.8,
};
/** Autour de Lyon : deux pannes récentes, et les déclarations de 2022 d'un opérateur, écartées. */
const ANTENNES: AntennesIndisponibles = {
  ...ENTETE, source: 'Arcep - déclarations des opérateurs', jour_du_fichier: '2026-11-15',
  ecartees: 26, ecartees_par_operateur: { 'Bouygues Telecom': 25, Orange: 1 }, par_operateur: { Orange: 1, SFR: 1 },
  resultats: [
    ANTENNE,
    { ...ANTENNE, cle: 'SFR|0692290587', operateur: 'SFR', gravite: 'PARTIELLE', voix_hs: false, motif: 'MAINTENANCE',
      technologies: { data4g: 'HS' }, depuis: '2026-11-10T22:00:00Z', debut_declare: false, distance_km: 3.2 },
  ],
};
const ANTENNES_VIDES: AntennesIndisponibles = {
  ...ANTENNES, ecartees: 0, ecartees_par_operateur: {}, par_operateur: {}, resultats: [],
};

const MAREGRAPHE: NiveauMer = {
  code: '5', nom: 'LE CONQUET', etat: 'FORTE', niveau_m: 6.41, niveau_le: '2026-11-15T19:30:00Z',
  maree_attendue_m: 5.83, surcote_cm: 58, incertitude_cm: 12.4, pleine_mer_le: '2026-11-15T22:30:00Z',
  pleine_mer_niveau_m: 7.12, maximum_m: 7.51, maximum_le: '2026-09-29T17:40:00Z', jours_ajustes: 180,
  latitude: 48.36, longitude: -4.78, distance_km: 21,
};
/** Autour de Brest : une forte surcote, un marégraphe dont la marée n'est pas encore calculée,
 * et un troisième sans mesure récente. */
const MER: NiveauxMer = {
  ...ENTETE, source: 'Shom - réseaux de marégraphes REFMAR',
  bilan: { FORTE: 1, MARQUEE: 0, NORMALE: 0, INCONNUE: 2 },
  resultats: [
    MAREGRAPHE,
    { ...MAREGRAPHE, code: '3', nom: 'BREST', etat: 'INCONNUE', niveau_m: 5.69, maree_attendue_m: null,
      surcote_cm: null, incertitude_cm: null, pleine_mer_le: null, pleine_mer_niveau_m: null,
      maximum_m: null, maximum_le: null, jours_ajustes: null },
    { ...MAREGRAPHE, code: '9', nom: 'MUET', etat: 'INCONNUE', niveau_m: null, surcote_cm: null },
  ],
};
const MER_VIDE: NiveauxMer = { ...MER, bilan: { FORTE: 0, MARQUEE: 0, NORMALE: 0, INCONNUE: 0 }, resultats: [] };

const STATION_EAU: StationHydrometrique = {
  code: 'K058000101', nom: 'L’Ondaine à Unieux - Le Pertuiset', cours_eau: 'l’Ondaine', tendance: 'HAUSSE_RAPIDE',
  hauteur_m: 0.66, hauteur_le: '2026-11-15T19:30:00Z', variation_1h_cm: 35.9, variation_3h_cm: 48,
  debit_m3s: 1.39, latitude: 45.409, longitude: 4.252, distance_km: 11.3,
};
/** Autour de Saint-Étienne : une station en hausse rapide, une stable, une sans mesure récente. */
const HAUTEURS: HauteursEau = {
  ...ENTETE, source: 'Hub’Eau - plate-forme nationale d’hydrométrie',
  bilan: { HAUSSE_RAPIDE: 1, HAUSSE: 0, STABLE: 1, BAISSE: 0, INCONNUE: 1 },
  resultats: [
    STATION_EAU,
    { ...STATION_EAU, code: 'K060001001', nom: 'La Loire à Saint-Just-Saint-Rambert', tendance: 'STABLE',
      hauteur_m: 417.02, variation_1h_cm: 1, variation_3h_cm: null, debit_m3s: 37 },
    { ...STATION_EAU, code: 'K000000001', nom: 'Sonde muette', tendance: 'INCONNUE', hauteur_m: null,
      variation_1h_cm: null, variation_3h_cm: null, debit_m3s: null },
  ],
};
const HAUTEURS_VIDES: HauteursEau = {
  ...HAUTEURS, bilan: { HAUSSE_RAPIDE: 0, HAUSSE: 0, STABLE: 0, BAISSE: 0, INCONNUE: 0 }, resultats: [],
};

const TRONCON: TronconCirculation = {
  code: 'MYL42.D2', axe: 'A72', sens: 'OUEST_EST', etat: 'SATURE', origine: 'OFFICIEL',
  vitesse_kmh: 8, debit_veh_h: 820, mesure_le: '2026-11-15T18:24:00Z', vitesse_habituelle_kmh: 88,
  cote: -1, latitude: 45.458, longitude: 4.407, distance_km: 2.4,
};
/** Autour de Saint-Étienne : un tronçon saturé (exploitant), un dense (estimé), deux fluides, un sans mesure. */
const CIRCULATION: Circulation = {
  ...ENTETE, source: 'Bison Futé - directions interdépartementales des routes',
  bilan: { BLOQUE: 0, SATURE: 1, DENSE: 1, FLUIDE: 2, INCONNU: 1 },
  resultats: [
    TRONCON,
    { ...TRONCON, code: 'MYL42.F2', axe: 'N88', sens: 'SUD_NORD', etat: 'DENSE', origine: 'ESTIME',
      vitesse_kmh: 46.4, vitesse_habituelle_kmh: null, distance_km: 5.3 },
    { ...TRONCON, code: 'MYL42.H1', axe: 'N88', sens: 'NORD_SUD', etat: 'FLUIDE', vitesse_kmh: 67 },
    { ...TRONCON, code: 'MYL42.H2', axe: 'N88', sens: 'SUD_NORD', etat: 'FLUIDE', vitesse_kmh: 71 },
    { ...TRONCON, code: 'MYL42.95', axe: 'A72', sens: '', etat: 'INCONNU', origine: '', vitesse_kmh: null },
  ],
};
const CIRCULATION_FLUIDE: Circulation = {
  ...CIRCULATION, bilan: { BLOQUE: 0, SATURE: 0, DENSE: 0, FLUIDE: 2, INCONNU: 0 },
  resultats: CIRCULATION.resultats.filter(t => t.etat === 'FLUIDE'),
};
const CIRCULATION_VIDE: Circulation = {
  ...CIRCULATION, bilan: { BLOQUE: 0, SATURE: 0, DENSE: 0, FLUIDE: 0, INCONNU: 0 }, resultats: [],
};

const ARRETES: ArretesCirculation = {
  ...ENTETE, bilan: { FERMETURE: 2, POIDS_LOURDS: 5, ALTERNAT: 1 },
  resultats: [
    { reference: 'a1', categorie: 'FERMETURE', categorie_libelle: 'Circulation interdite',
      description: 'Travaux de voirie', autorite: 'Ville de Saint-Étienne', voies: 'Rue Henri Gandais',
      tonnage_max: null, debut: '2026-11-01T07:00:00Z', fin: '2026-12-31T17:00:00Z',
      url: 'https://dialog.beta.gouv.fr/regulations/a1', latitude: 45.43, longitude: 4.38 },
    { reference: 'a2', categorie: 'FERMETURE', categorie_libelle: 'Circulation interdite',
      description: 'Voie piétonne', autorite: 'Ville de Saint-Étienne', voies: 'Rue des Martyrs',
      tonnage_max: null, debut: '2010-01-01T00:00:00Z', fin: null, url: '', latitude: 45.44, longitude: 4.39 },
  ],
};

const SANTE: SanteUrgences = {
  source: 'Santé publique France', releve_le: '2026-11-15T09:10:00Z', perime: false,
  departement_code: '42', departement_nom: 'Loire',
  indicateurs: [
    { pathologie: 'GRIPPE', libelle: 'Grippe', semaine: '2026-S45', debut_semaine: '2026-11-02',
      taux_urgences: 241.2, taux_urgences_precedent: 180, taux_sos: 1136.4, tendance: 'hausse' },
    { pathologie: 'COVID', libelle: 'Covid-19', semaine: '2026-S45', debut_semaine: '2026-11-02',
      taux_urgences: 30, taux_urgences_precedent: null, taux_sos: null, tendance: '' },
  ],
};

const RADIO: Radioactivite = {
  ...ENTETE,
  resultats: [
    { station: 1039, nom: 'ST-ETIENNE', latitude: 45.443, longitude: 4.387, distance_km: 0.4,
      proche_installation: false, debit_nsv_h: 99, bruit_de_fond_nsv_h: 105.2, ecart_nsv_h: -6.2,
      valide: true, mesure_le: '2026-11-15T15:40:12Z' },
    { station: 2001, nom: 'ST-ALBAN', latitude: 45.40, longitude: 4.75, distance_km: 28.3,
      proche_installation: true, debit_nsv_h: 131, bruit_de_fond_nsv_h: null, ecart_nsv_h: null,
      valide: false, mesure_le: '2026-11-15T15:40:12Z' },
  ],
};

const SEISMES: Seismes = {
  ...ENTETE,
  resultats: [
    { reference: 's1', date: '2026-11-13T08:39:02Z', magnitude: 3.2, profondeur_km: 5.2, lieu: 'Montbrison',
      zone: 'France hexagonale', nature: 'earthquake', nature_libelle: 'Séisme', latitude: 45.53, longitude: 4.10, distance_km: 25 },
    { reference: 't1', date: '2026-11-12T10:00:00Z', magnitude: 1.9, profondeur_km: 0, lieu: 'Saint-Just',
      zone: 'France hexagonale', nature: 'quarry blast', nature_libelle: 'Tir de carrière', latitude: 45.5, longitude: 4.2, distance_km: 18 },
  ],
};

const fournaise = (aPortee: boolean) => ({
  code: 'FOURNAISE', nom: 'Piton de la Fournaise', territoire: 'La Réunion', latitude: -21.244, longitude: 55.708,
  observatoire: 'OVPF-IPGP', url: 'https://www.ipgp.fr/observation/ovs/ovpf/',
  seismes_7_jours: 12, seismes_7_jours_precedents: 4, magnitude_max: 2.3,
  dernier_seisme: '2026-11-15T08:00:00Z', distance_km: aPortee ? 24 : 9300, a_portee: aPortee,
});
const VOLCANS = (aPortee: boolean): Volcans => ({
  source: 'BCSF-Rénass', releve_le: '2026-11-15T09:10:00Z', perime: false, rayon_km: 15, volcans: [fournaise(aPortee)],
});

const FOYERS: FoyersActifs = {
  ...ENTETE, sources_fixes: 3,
  resultats: [{ reference: 'f1', date: '2026-11-15T12:30:00Z', latitude: 45.51, longitude: 4.41,
                distance_km: 8.2, confiance: 'nominale', puissance_mw: 10.1, satellite: 'N20', source_fixe: false }],
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
                                forets?: MeteoForets; feux?: ZonesBrulees; avalanche?: RisqueAvalanche;
                                arretes?: ArretesCirculation; sante?: SanteUrgences; circulation?: Circulation; hauteurs?: HauteursEau; mer?: NiveauxMer;
                                antennes?: AntennesIndisponibles; air?: QualiteAir;
                                radio?: Radioactivite; seismes?: Seismes; volcans?: Volcans;
                                foyers?: FoyersActifs; rafales?: RafalesPrevues; hiver?: PrecipitationsHiver } = {}) {
    const fixture = TestBed.createComponent(VeilleComponent);
    fixture.detectChanges();
    http.expectOne(`${api}/vigilance-meteo/`).flush(reponses.vigilance ?? VIGILANCE);
    http.expectOne(`${api}/restrictions-eau/`).flush(reponses.eau ?? EAU);
    http.expectOne(`${api}/volcans/`).flush(reponses.volcans ?? VOLCANS(false));
    http.expectOne(`${api}/sante-urgences/`).flush(reponses.sante ?? SANTE);
    http.expectOne(`${api}/meteo-forets/`).flush(reponses.forets ?? FORETS_HORS_SAISON);
    http.expectOne(r => r.url === `${api}/rafales-prevues/`).flush(reponses.rafales ?? RAFALES_CALMES);
    http.expectOne(r => r.url === `${api}/precipitations-hiver/`).flush(reponses.hiver ?? HIVER_AU_SEC);
    http.expectOne(r => r.url === `${api}/vigilance-crues/`).flush(reponses.crues ?? CRUES);
    http.expectOne(r => r.url === `${api}/radioactivite/`).flush(reponses.radio ?? RADIO);
    http.expectOne(r => r.url === `${api}/seismes/`).flush(reponses.seismes ?? SEISMES);
    http.expectOne(r => r.url === `${api}/risque-avalanche/`).flush(reponses.avalanche ?? EN_PLAINE);
    http.expectOne(r => r.url === `${api}/foyers-actifs/`).flush(reponses.foyers ?? FOYERS);
    http.expectOne(r => r.url === `${api}/zones-brulees/`).flush(reponses.feux ?? FEUX);
    http.expectOne(r => r.url === `${api}/observations-meteo/`).flush(reponses.observations ?? OBSERVATIONS);
    http.expectOne(r => r.url === `${api}/qualite-air/`).flush(reponses.air ?? AIR_VIDE);
    http.expectOne(r => r.url === `${api}/antennes-indisponibles/`).flush(reponses.antennes ?? ANTENNES_VIDES);
    http.expectOne(r => r.url === `${api}/niveaux-mer/`).flush(reponses.mer ?? MER_VIDE);
    http.expectOne(r => r.url === `${api}/hauteurs-eau/`).flush(reponses.hauteurs ?? HAUTEURS_VIDES);
    http.expectOne(r => r.url === `${api}/circulation/`).flush(reponses.circulation ?? CIRCULATION_VIDE);
    http.expectOne(r => r.url === `${api}/arretes-circulation/`).flush(reponses.arretes ?? ARRETES);
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
    expect(demandes.length).toBe(22);
    // LE test de cette page : aucun appel ne sort vers un service tiers.
    for (const demande of demandes) expect(demande.request.url.startsWith(api)).toBeTrue();
    const images: HTMLImageElement[] = Array.from(fixture.nativeElement.querySelectorAll('img'));
    expect(images.every(image => image.src.includes('/vigilance-meteo/vignette/'))).toBeTrue();
  });

  /** Neige, verglas, grêle prévus (15/11/2026) : la page dit le plus dangereux de ce qui est
   * prévu sur la commune, et se tait quand rien de tel n'est annoncé. */
  describe('neige et verglas prévus sur la commune', () => {
    const bloc = (fixture: any): HTMLElement => fixture.nativeElement.querySelector('.hiver-ici');

    it('demande la lecture locale à notre serveur', () => {
      const fixture = TestBed.createComponent(VeilleComponent);
      fixture.detectChanges();

      expect(http.expectOne(r => r.url === `${api}/precipitations-hiver/`).request.params.get('ici')).toBe('1');
      http.match(() => true);
    });

    it('dit le plus dangereux de ce qui est prévu et sa première heure', () => {
      const fixture = demarrer({ hiver: HIVER });

      expect(bloc(fixture).textContent).toContain('pluie ou bruine verglaçante');
      expect(bloc(fixture).textContent).toMatch(/vers \d\d:30/);
      expect(bloc(fixture).classList).toContain('fort');
      expect(bloc(fixture).textContent).toContain('pas la quantité ni la tenue au sol');
    });

    it('n’habille pas la neige humide en danger', () => {
      const fixture = demarrer({ hiver: { ...HIVER, ici: { ...HIVER.ici!, pire: 'NEIGE_HUMIDE' } } });

      expect(bloc(fixture).textContent).toContain('neige humide');
      expect(bloc(fixture).textContent).toMatch(/vers \d\d:15/);
      expect(bloc(fixture).classList).not.toContain('fort');
    });

    it('se tait quand rien de tel n’est prévu, ou hors de la métropole', () => {
      expect(bloc(demarrer({ hiver: HIVER_AU_SEC }))).toBeNull();
    });
  });

  /** Qualité de l'air (15/11/2026) : une estimation par modèle dans la ville de la liste la plus
   * proche. La page doit donner la source (mention obligatoire) et dire ce que ce n'est pas. */
  describe('qualité de l’air', () => {
    const bloc = (fixture: any): HTMLElement => fixture.nativeElement.querySelector('[aria-labelledby="titre-air"]');

    it('donne l’indice, les polluants et la ville où ils sont estimés', () => {
      const fixture = demarrer({ air: AIR });

      expect(bloc(fixture).querySelector('h2')!.textContent).toContain('Saint-Étienne');
      expect(bloc(fixture).querySelector('.etiquette.air')!.textContent).toContain('Indice 2 sur 5 : correct');
      expect(bloc(fixture).querySelector('.etiquette.air')!.getAttribute('data-indice')).toBe('2');
      expect(bloc(fixture).textContent).toMatch(/particules fines PM2,5 4[.,]1 µg\/m³/);
      expect(bloc(fixture).textContent).toMatch(/à 14 km de votre commune/);
    });

    it('annonce une dégradation prévue, et seulement une dégradation', () => {
      expect(bloc(demarrer({ air: AIR })).querySelector('.air-prevision')!.textContent).toMatch(/jusqu'à 4 \(mauvais\) vers \d\d:00/);
    });

    it('ne parle pas de prévision quand l’air ne se dégrade pas', () => {
      const stable = { ...AIR, plus_proche: { ...AIR.plus_proche!, pire_24h: 2, pire_24h_libelle: 'correct' } };

      expect(bloc(demarrer({ air: stable })).querySelector('.air-prevision')).toBeNull();
    });

    it('cite la source et dit que ce n’est ni une mesure ni l’indice ATMO', () => {
      const fixture = demarrer({ air: AIR });

      expect(bloc(fixture).textContent).toContain('Données météo fournies par OpenWeather');
      expect(bloc(fixture).textContent).toContain('pas la mesure d\'une station');
      expect(bloc(fixture).textContent).toContain('pas l\'indice ATMO');
    });

    it('ne donne pas une estimation ancienne comme l’air qu’il fait', () => {
      const ancienne = { ...AIR, plus_proche: { ...AIR.plus_proche!, indice: null, libelle: '', composants: {} } };
      const fixture = demarrer({ air: ancienne });

      expect(bloc(fixture).textContent).toContain('Estimation ancienne');
      expect(bloc(fixture).querySelector('.etiquette.air')).toBeNull();
    });

    it('n’affiche rien tant que rien n’a été relevé', () => {
      expect(bloc(demarrer({ air: AIR_VIDE }))).toBeNull();
    });
  });

  /** Réseau mobile (15/11/2026) : les antennes que les opérateurs déclarent en panne. La page
   * doit dire que c'est un état quotidien, et ce que le filtre des six mois a écarté. */
  describe('réseau mobile', () => {
    const bloc = (fixture: any): HTMLElement => fixture.nativeElement.querySelector('[aria-labelledby="titre-mobile"]');

    it('compte les pannes par opérateur et liste les antennes avec ce qui est coupé', () => {
      const fixture = demarrer({ antennes: ANTENNES });
      const lignes: HTMLElement[] = Array.from(bloc(fixture).querySelectorAll('.mobile li'));

      expect(bloc(fixture).querySelector('.compte')!.textContent).toBe('2');
      expect(bloc(fixture).querySelector('.operateurs')!.textContent).toContain('Orange : 1');
      expect(bloc(fixture).querySelector('.operateurs')!.textContent).toContain('SFR : 1');
      expect(lignes.length).toBe(2);
      expect(lignes[0].textContent).toContain('Voix et données coupées');
      expect(lignes[0].textContent).toContain('4G voix, 4G données, 5G données');
      expect(lignes[0].textContent).toMatch(/incident depuis le 14\/11\/2026/);
      expect(lignes[1].textContent).toContain('Service partiel');
      expect(lignes[1].textContent).toContain('maintenance depuis le');
      expect(lignes[1].textContent).toContain('notre première observation');
    });

    it('dit ce que le filtre des six mois a écarté, opérateur par opérateur', () => {
      const fixture = demarrer({ antennes: ANTENNES });
      const ecarts: HTMLElement[] = Array.from(bloc(fixture).querySelectorAll('.ecartees'));

      expect(ecarts.length).toBe(2);
      expect(ecarts[0].textContent).toContain('Bouygues Telecom');
      expect(ecarts[0].textContent).toContain('25 déclaration(s) de plus de six mois');
      // Aucune panne Bouygues affichée : la page ne doit pas laisser croire que son réseau va bien.
      expect(ecarts[0].textContent).toContain('cela ne dit pas que son réseau fonctionne');
      expect(ecarts[1].textContent).toContain('Orange');
      expect(ecarts[1].textContent).not.toContain('cela ne dit pas');
    });

    it('rappelle que c’est un état quotidien et qu’une antenne n’est pas une zone', () => {
      const fixture = demarrer({ antennes: ANTENNES });

      expect(bloc(fixture).textContent).toMatch(/état du 15\/11\/2026/);
      expect(bloc(fixture).textContent).toContain('Un état quotidien, publié vers 10 h');
      expect(bloc(fixture).textContent).toContain('une antenne voisine peut couvrir');
    });

    it('garde le bloc quand il ne reste que des déclarations écartées', () => {
      const fixture = demarrer({ antennes: { ...ANTENNES, par_operateur: {}, resultats: [],
                                             ecartees: 25, ecartees_par_operateur: { 'Bouygues Telecom': 25 } } });

      expect(bloc(fixture).textContent).toContain('Aucune panne récente déclarée');
      expect(bloc(fixture).textContent).toContain('Bouygues Telecom');
    });

    it('n’affiche rien quand le fichier ne déclare aucune antenne dans le rayon', () => {
      expect(bloc(demarrer({ antennes: ANTENNES_VIDES }))).toBeNull();
    });

    it('ne liste que les dix premières et renvoie à la carte pour le reste', () => {
      const beaucoup = Array.from({ length: 13 }, (_, rang) => ({ ...ANTENNE, cle: `Orange|${rang}` }));
      const fixture = demarrer({ antennes: { ...ANTENNES, par_operateur: { Orange: 13 }, resultats: beaucoup } });

      expect(bloc(fixture).querySelectorAll('.mobile li').length).toBe(10);
      expect(bloc(fixture).textContent).toContain('et 3 autres, à voir sur la carte');
    });
  });

  /** Niveau de la mer (15/11/2026) : la mesure des marégraphes, et la surcote que notre serveur
   * estime. La page doit dire que c'est une estimation, et se taire loin de la mer. */
  describe('niveau de la mer', () => {
    const bloc = (fixture: any): HTMLElement => fixture.nativeElement.querySelector('[aria-labelledby="titre-mer"]');

    it('donne la mesure, la surcote estimée avec son incertitude et la prochaine pleine mer', () => {
      const fixture = demarrer({ mer: MER });
      const lignes: HTMLElement[] = Array.from(bloc(fixture).querySelectorAll('.mer li'));

      expect(lignes.length).toBe(2);                              // le marégraphe muet n'est pas listé
      expect(lignes[0].textContent).toContain('Forte surcote');
      expect(lignes[0].textContent).toContain('LE CONQUET');
      expect(lignes[0].textContent).toMatch(/6[.,]41 m mesurés/);
      expect(lignes[0].textContent).toContain('surcote estimée +58 cm');
      expect(lignes[0].textContent).toContain('± 12');
      expect(lignes[0].textContent).toMatch(/pleine mer vers \d\d:30 : 7[.,]12 m si l'écart se maintient/);
      expect(lignes[0].textContent).toMatch(/plus haut mesuré en 180 jours : 7[.,]51 m/);
      expect(bloc(fixture).querySelector('.compte')!.textContent).toBe('1');
    });

    it('ne prétend rien pour un marégraphe dont la marée n’est pas encore calculée', () => {
      const fixture = demarrer({ mer: MER });
      const brest: HTMLElement = bloc(fixture).querySelectorAll('.mer li')[1] as HTMLElement;

      expect(brest.textContent).toContain('marée pas encore calculée');
      expect(brest.textContent).not.toContain('surcote estimée');
      expect(brest.textContent).not.toContain('pleine mer');
    });

    it('dit que la surcote est une estimation de ce serveur, pas une alerte', () => {
      const fixture = demarrer({ mer: MER });

      expect(bloc(fixture).textContent).toContain('calculées par ce');
      expect(bloc(fixture).textContent).toContain('ni une prédiction officielle de marée, ni une alerte');
    });

    it('se tait loin de la mer', () => {
      expect(bloc(demarrer({ mer: MER_VIDE }))).toBeNull();
    });
  });

  /** Hauteurs d'eau (15/11/2026) : les mesures des stations en rivière. La page ne montre
   * d'abord que ce qui monte, et dit que la hauteur ne se compare qu'à elle-même. */
  describe('hauteurs d’eau mesurées', () => {
    const bloc = (fixture: any): HTMLElement => fixture.nativeElement.querySelector('[aria-labelledby="titre-crues"]');
    const lignes = (fixture: any): HTMLElement[] => Array.from(bloc(fixture).querySelectorAll('.hauteurs li'));

    it('ne liste d’abord que les stations qui montent, avec leur variation', () => {
      const fixture = demarrer({ hauteurs: HAUTEURS });

      expect(lignes(fixture).length).toBe(1);
      expect(lignes(fixture)[0].textContent).toContain('Hausse rapide');
      expect(lignes(fixture)[0].textContent).toContain('Ondaine à Unieux');
      expect(lignes(fixture)[0].textContent).toContain('+36 cm en 1 h');
      expect(lignes(fixture)[0].textContent).toContain('+48 cm en 3 h');
      // Le séparateur décimal dépend de la langue du navigateur de test.
      expect(lignes(fixture)[0].textContent).toMatch(/0[.,]66 m à l'échelle/);
    });

    it('montre toutes les stations mesurées à la demande, pas les sondes muettes', () => {
      const fixture = demarrer({ hauteurs: HAUTEURS });
      const bouton: HTMLButtonElement = bloc(fixture).querySelector('button.discret')!;

      expect(bouton.textContent).toContain('Voir les 2 stations mesurées');
      bouton.click();
      fixture.detectChanges();

      expect(lignes(fixture).length).toBe(2);
      expect(lignes(fixture)[1].textContent).toContain('Stable');
      expect(bloc(fixture).textContent).not.toContain('Sonde muette');
    });

    it('dit que la hauteur ne se compare qu’à elle-même', () => {
      const fixture = demarrer({ hauteurs: HAUTEURS });

      expect(bloc(fixture).textContent).toContain('ni « normal » ni « en crue »');
      expect(bloc(fixture).textContent).toContain('pas une alerte');
    });

    it('dit le calme quand rien ne monte', () => {
      const fixture = demarrer({ hauteurs: {
        ...HAUTEURS, bilan: { HAUSSE_RAPIDE: 0, HAUSSE: 0, STABLE: 1, BAISSE: 0, INCONNUE: 1 },
        resultats: HAUTEURS.resultats.slice(1),
      } });

      expect(bloc(fixture).textContent).toContain('Aucune hausse marquée sur les 1 stations mesurées');
    });

    it('ne dit rien là où il n’y a pas de station', () => {
      const fixture = demarrer({ hauteurs: HAUTEURS_VIDES });

      expect(bloc(fixture).textContent).not.toContain('Hauteurs mesurées');
    });
  });

  /** Circulation (15/11/2026) : vitesses mesurées sur les routes nationales. La page ne liste
   * que ce qui ne roule pas, dit d'où vient chaque état, et rappelle ce que la source ne couvre pas. */
  describe('circulation', () => {
    const bloc = (fixture: any): HTMLElement => fixture.nativeElement.querySelector('[aria-labelledby="titre-circulation"]');

    it('liste les tronçons encombrés, avec leur vitesse et l’origine de l’état', () => {
      const fixture = demarrer({ circulation: CIRCULATION });
      const lignes: HTMLElement[] = Array.from(bloc(fixture).querySelectorAll('.troncons li'));

      expect(lignes.length).toBe(2);                              // ni les fluides, ni le « sans mesure »
      expect(lignes[0].textContent).toContain('Saturé');
      expect(lignes[0].textContent).toContain('A72 vers l’est');
      expect(lignes[0].textContent).toContain('8 km/h');
      expect(lignes[0].textContent).toContain('d\'habitude 88');
      expect(lignes[0].textContent).toContain('état donné par l\'exploitant');
      expect(lignes[1].textContent).toContain('Dense');
      expect(lignes[1].textContent).toContain('46 km/h');
      expect(lignes[1].textContent).not.toContain('habitude');    // pas encore apprise : pas de chiffre
      expect(lignes[1].textContent).toContain('estimé d\'après la vitesse');
      expect(bloc(fixture).querySelector('.compte')!.textContent).toBe('2');
    });

    it('dit ce que la source ne couvre pas', () => {
      const fixture = demarrer({ circulation: CIRCULATION });

      expect(bloc(fixture).textContent).toContain('ni les autoroutes concédées');
      expect(bloc(fixture).textContent).toContain('1 sans mesure');
      expect(bloc(fixture).textContent).toContain('Bison Futé');
    });

    it('dit quand tout roule, en comptant les tronçons mesurés', () => {
      const fixture = demarrer({ circulation: CIRCULATION_FLUIDE });

      expect(bloc(fixture).textContent).toContain('Aucun ralentissement sur les 2 tronçons mesurés');
      expect(bloc(fixture).querySelector('.troncons')).toBeNull();
    });

    it('signale un relevé ancien', () => {
      const fixture = demarrer({ circulation: { ...CIRCULATION, perime: true } });

      expect(bloc(fixture).textContent).toContain('Relevé ancien');
    });

    it('n’affiche pas de bloc là où aucune route n’est mesurée', () => {
      const fixture = demarrer({ circulation: CIRCULATION_VIDE });

      expect(bloc(fixture)).toBeNull();
    });
  });

  /** Rafales prévues (15/11/2026) : la page dit ce que la prévision donne pour la commune --
   * lu par le serveur dans ses propres images -- et renvoie à la carte pour le reste. */
  describe('rafales prévues sur la commune', () => {
    const bloc = (fixture: any): HTMLElement => fixture.nativeElement.querySelector('.rafales-ici');

    it('demande la lecture locale à notre serveur', () => {
      const fixture = TestBed.createComponent(VeilleComponent);
      fixture.detectChanges();

      const demande = http.expectOne(r => r.url === `${api}/rafales-prevues/`);
      expect(demande.request.params.get('ici')).toBe('1');
      http.match(() => true);
    });

    it('donne le palier le plus fort et la première heure où il est atteint', () => {
      const fixture = demarrer({ rafales: RAFALES });

      expect(bloc(fixture).textContent).toContain('80 à 100 km/h');
      expect(bloc(fixture).textContent).toMatch(/vers \d\d:30/);
      expect(bloc(fixture).classList).toContain('fort');
      expect(bloc(fixture).textContent).toContain('pas une alerte');
    });

    it('dit « ou plus » au dernier palier', () => {
      const fixture = demarrer({ rafales: {
        ...RAFALES, ici: { ...RAFALES.ici!, maximum_kmh: 140, paliers: [{ echeance: '2026-11-15T17:00:00Z', a_partir_de_kmh: 140 }] },
      } });

      expect(bloc(fixture).textContent).toContain('140 km/h ou plus');
    });

    it('dit le calme sans l’habiller en alerte', () => {
      const fixture = demarrer({ rafales: RAFALES_CALMES });

      expect(bloc(fixture).textContent).toContain('aucune rafale de 40 km/h ou plus');
      expect(bloc(fixture).classList).not.toContain('fort');
    });

    it('dit que l’outre-mer n’est pas couvert', () => {
      const fixture = demarrer({ rafales: {
        ...RAFALES, ici: { latitude: -21.1, longitude: 55.5, couvert: false, maximum_kmh: null,
                           paliers: [{ echeance: '2026-11-15T17:00:00Z', a_partir_de_kmh: null }] },
      } });

      expect(bloc(fixture).textContent).toContain('ne couvre que la métropole');
    });

    it('signale un relevé ancien', () => {
      const fixture = demarrer({ rafales: { ...RAFALES, perime: true } });

      expect(bloc(fixture).textContent).toContain('relevé ancien');
    });

    it('ne dit rien du lieu quand le serveur ne le connaît pas', () => {
      const fixture = demarrer({ rafales: { ...RAFALES, ici: null } });

      expect(bloc(fixture)).toBeNull();
      expect(texte(fixture)).toContain('Rafales prévues');
    });
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

  it('liste les fermetures temporaires des routes locales et compte le reste', () => {
    const fixture = demarrer();
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-routes"]');

    // L'arrêté permanent (voie piétonne) n'encombre pas la liste : il est compté.
    expect(bloc.textContent).toContain('Rue Henri Gandais');
    expect(bloc.textContent).not.toContain('Rue des Martyrs');
    expect(bloc.textContent).toContain('2 voie(s) interdite(s)');
    expect(bloc.textContent).toContain('5 interdite(s) aux poids lourds');
    expect(bloc.querySelector('a[href="https://dialog.beta.gouv.fr/regulations/a1"]')).not.toBeNull();
    // Une commune absente de DiaLog n'est pas une commune sans route fermée.
    expect(bloc.textContent).toContain('Seules les collectivités qui publient dans DiaLog');
  });

  it('donne les recours aux urgences du département et dit ce que le chiffre mesure', () => {
    const fixture = demarrer();
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-sante"]');
    const lignes = bloc.querySelectorAll('tbody tr');

    expect(bloc.textContent).toContain('Loire');
    expect(lignes[0].textContent).toContain('Grippe');
    expect(lignes[0].textContent).toContain('241');
    expect(lignes[0].textContent).toContain('en hausse');
    expect(lignes[0].classList.contains('remarquable')).toBeTrue();
    // Une semaine sans comparaison possible n'affiche pas de tendance inventée.
    expect(lignes[1].querySelector('.tendance')).toBeNull();
    expect(bloc.textContent).toContain('ni un nombre de malades');
  });

  it('ne montre pas le bloc santé sans indicateur pour ce département', () => {
    const fixture = demarrer({ sante: { ...SANTE, indicateurs: [] } });

    expect(fixture.nativeElement.querySelector('section[aria-labelledby="titre-sante"]')).toBeNull();
  });

  it('liste les séismes sans les mêler aux tirs de carrière', () => {
    const fixture = demarrer();
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-seismes"]');
    const lignes = bloc.querySelectorAll('tbody tr');

    expect(lignes.length).toBe(1);
    expect(lignes[0].textContent).toContain('Montbrison');
    expect(lignes[0].classList.contains('remarquable')).toBeTrue();          // magnitude 3 ou plus
    expect(bloc.textContent).toContain('1 tir(s) de carrière');
    expect(fixture.componentInstance.autresSecousses.length).toBe(1);
  });

  it('affiche la radioactivité sans jamais en faire une alerte', () => {
    const fixture = demarrer();
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-radioactivite"]');
    const lignes = bloc.querySelectorAll('tbody tr');

    expect(lignes[0].textContent).toContain('ST-ETIENNE');
    expect(lignes[0].textContent).toContain('99 nSv/h');
    expect(lignes[0].textContent).toContain('105 nSv/h');
    // Aucune ligne n'est mise en avant, quelle que soit la valeur.
    expect(bloc.querySelector('.remarquable')).toBeNull();
    // Sans niveau habituel connu, pas d'écart inventé ; une mesure non validée est dite telle.
    expect(lignes[1].textContent).toContain('non validée');
    expect(bloc.textContent).toContain('ne sont pas une alerte');
  });

  it('ne parle de volcans qu’aux territoires qui en ont un à portée', () => {
    expect(demarrer().nativeElement.querySelector('section[aria-labelledby="titre-volcans"]')).toBeNull();

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [VeilleComponent],
      providers: [provideHttpClient(), provideHttpClientTesting(), provideRouter([])],
    });
    http = TestBed.inject(HttpTestingController);
    const fixture = demarrer({ volcans: VOLCANS(true) });
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-volcans"]');

    expect(bloc.textContent).toContain('Piton de la Fournaise');
    expect(bloc.textContent).toContain('12 séisme(s)');
    expect(bloc.textContent).toContain('sismicité en hausse');
    expect(bloc.textContent).toContain('Ceci n\'est pas un état du volcan');
    expect(bloc.querySelector('a[href="https://www.ipgp.fr/observation/ovs/ovpf/"]')).not.toBeNull();
  });

  it('présente un foyer comme un point à vérifier, et dit ce que le satellite ne voit pas', () => {
    const fixture = demarrer();
    const bloc: HTMLElement = fixture.nativeElement.querySelector('section[aria-labelledby="titre-feux"]');
    const ligne = bloc.querySelector('.foyers li')!;

    expect(ligne.textContent).toContain('à vérifier');
    expect(ligne.textContent).toContain('à 8 km');
    expect(bloc.textContent).toContain('Ce n\'est pas forcément un feu de forêt');
    // Les usines repérées ne sont pas dans la liste, et la page le dit.
    expect(bloc.textContent).toContain('3 détection(s)');
    expect(bloc.textContent).toContain('un feu réel n\'est pas vu');
  });

  it('montre d’abord les fermetures et garde les travaux sur demande', () => {
    const fixture = demarrer();
    // Les deux listes (réseau national, routes locales) partagent leur mise en forme : on ne
    // regarde ici que les événements du réseau national, qui portent une route numérotée.
    const liste = () => (Array.from(fixture.nativeElement.querySelectorAll('.evenements li')) as HTMLElement[])
      .filter(li => li.textContent!.includes('N88'));

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
    http.expectOne(r => r.url === `${api}/radioactivite/` && r.params.get('rayon_km') === '60').flush(RADIO);
    http.expectOne(r => r.url === `${api}/seismes/` && r.params.get('rayon_km') === '60').flush(SEISMES);
    http.expectOne(r => r.url === `${api}/risque-avalanche/` && r.params.get('rayon_km') === '60').flush(EN_PLAINE);
    http.expectOne(r => r.url === `${api}/foyers-actifs/` && r.params.get('rayon_km') === '60').flush(FOYERS);
    http.expectOne(r => r.url === `${api}/zones-brulees/` && r.params.get('rayon_km') === '60').flush(FEUX);
    http.expectOne(r => r.url === `${api}/observations-meteo/` && r.params.get('rayon_km') === '60').flush(OBSERVATIONS);
    http.expectOne(r => r.url === `${api}/qualite-air/` && r.params.get('rayon_km') === '60').flush(AIR_VIDE);
    http.expectOne(r => r.url === `${api}/antennes-indisponibles/` && r.params.get('rayon_km') === '60').flush(ANTENNES_VIDES);
    http.expectOne(r => r.url === `${api}/niveaux-mer/` && r.params.get('rayon_km') === '60').flush(MER_VIDE);
    http.expectOne(r => r.url === `${api}/hauteurs-eau/` && r.params.get('rayon_km') === '60').flush(HAUTEURS_VIDES);
    http.expectOne(r => r.url === `${api}/circulation/` && r.params.get('rayon_km') === '60').flush(CIRCULATION_VIDE);
    http.expectOne(r => r.url === `${api}/arretes-circulation/` && r.params.get('rayon_km') === '60').flush(ARRETES);
    http.expectOne(r => r.url === `${api}/evenements-routiers/` && r.params.get('rayon_km') === '60').flush(ROUTES);
    http.expectOne(r => r.url === `${api}/stations-carburant/` && r.params.get('rayon_km') === '60').flush(STATIONS);
    expect(fixture.componentInstance.rayonKm).toBe(60);
  });

  it('explique pourquoi rien ne s’affiche pour un compte sans commune', () => {
    const sansEmprise = { ...ENTETE, emprise_connue: false, centre: null, rayon_km: null };
    const fixture = demarrer({
      crues: { ...sansEmprise, resultats: [] },
      radio: { ...sansEmprise, resultats: [] },
      seismes: { ...sansEmprise, resultats: [] },
      feux: { ...sansEmprise, resultats: [] },
      foyers: { ...sansEmprise, sources_fixes: 0, resultats: [] },
      observations: { ...sansEmprise, resultats: [] },
      arretes: { ...sansEmprise, bilan: { FERMETURE: 0, POIDS_LOURDS: 0, ALTERNAT: 0 }, resultats: [] },
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
    http.expectOne(`${api}/volcans/`).flush(VOLCANS(false));
    http.expectOne(`${api}/sante-urgences/`).flush(SANTE);
    http.expectOne(`${api}/meteo-forets/`).flush(FORETS_HORS_SAISON);
    http.expectOne(r => r.url === `${api}/rafales-prevues/`).flush(RAFALES_CALMES);
    http.expectOne(r => r.url === `${api}/precipitations-hiver/`).flush(HIVER_AU_SEC);
    http.expectOne(r => r.url === `${api}/vigilance-crues/`).flush(CRUES);
    http.expectOne(r => r.url === `${api}/radioactivite/`).flush(RADIO);
    http.expectOne(r => r.url === `${api}/seismes/`).flush(SEISMES);
    http.expectOne(r => r.url === `${api}/risque-avalanche/`).flush(EN_PLAINE);
    http.expectOne(r => r.url === `${api}/foyers-actifs/`).flush(FOYERS);
    http.expectOne(r => r.url === `${api}/zones-brulees/`).flush(FEUX);
    http.expectOne(r => r.url === `${api}/observations-meteo/`).flush(OBSERVATIONS);
    http.expectOne(r => r.url === `${api}/qualite-air/`).flush(AIR_VIDE);
    http.expectOne(r => r.url === `${api}/antennes-indisponibles/`).flush(ANTENNES_VIDES);
    http.expectOne(r => r.url === `${api}/niveaux-mer/`).flush(MER_VIDE);
    http.expectOne(r => r.url === `${api}/hauteurs-eau/`).flush(HAUTEURS_VIDES);
    http.expectOne(r => r.url === `${api}/circulation/`).flush(CIRCULATION_VIDE);
    http.expectOne(r => r.url === `${api}/arretes-circulation/`).flush(ARRETES);
    http.expectOne(r => r.url === `${api}/evenements-routiers/`).flush('', { status: 500, statusText: 'Erreur' });
    http.expectOne(r => r.url === `${api}/stations-carburant/`).flush(STATIONS);
    fixture.detectChanges();

    expect(texte(fixture)).toContain('Impossible de lire les événements routiers');
    expect(fixture.nativeElement.querySelector('.mon-departement')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.bilan')).not.toBeNull();
  });
});
