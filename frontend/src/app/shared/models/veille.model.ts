/** Veille du territoire : ce que le serveur a copié des sources ouvertes de l'État (vigilance
 * Météo-France, événements routiers Bison Futé, stations de carburant) — voir
 * backend/core/sources_ouvertes.py. Le navigateur ne lit que cette copie : il n'interroge
 * jamais ces services lui-même. */

export interface PeriodeVigilance { debut: string; fin: string; couleur: number; }

export interface PhenomeneVigilance {
  id: number;
  /** 2 jaune, 3 orange, 4 rouge (le vert n'est pas transmis). */
  couleur: number;
  periodes: PeriodeVigilance[];
}

export interface FicheVigilance {
  debut: string;
  fin: string;
  couleur: number;
  phenomenes: PhenomeneVigilance[];
}

export interface SectionBulletin { rubrique: string; alea: string; titre: string; lignes: string[]; }

export interface VigilanceDepartement {
  departement_code: string;
  nom: string;
  couleur_j: number;
  couleur_j1: number;
  detail: { J?: FicheVigilance; J1?: FicheVigilance };
  /** Servi seulement pour la France et pour le département consulté. */
  bulletin?: SectionBulletin[];
  publie_le: string;
  releve_le: string;
}

export interface VigilanceMeteo {
  disponible: boolean;
  source: string;
  releve_le: string | null;
  publie_le: string | null;
  /** La copie est trop ancienne pour être présentée comme actuelle. */
  perime: boolean;
  phenomenes: Record<string, string>;
  couleurs: Record<string, string>;
  france: VigilanceDepartement | null;
  mon_departement: VigilanceDepartement | null;
  departements: VigilanceDepartement[];
  vignettes: string[];
}

interface EnteteVeille {
  source: string;
  releve_le: string | null;
  perime: boolean;
  centre: { latitude: number; longitude: number } | null;
  rayon_km: number | null;
  /** Faux quand rien ne dit où regarder (compte sans commune de rattachement). */
  emprise_connue: boolean;
  tronque: boolean;
}

export type CategorieEvenementRoutier =
  'FERMETURE' | 'ACCIDENT' | 'OBSTACLE' | 'CONDITIONS' | 'DEVIATION' | 'TRAVAUX' | 'RESTRICTION' | 'AUTRE';

export interface EvenementRoutier {
  reference: string;
  categorie: CategorieEvenementRoutier;
  categorie_libelle: string;
  natures: string[];
  gravite: string;
  route: string;
  commune_nom: string;
  description: string;
  localisation: string;
  gestionnaire: string;
  departement_code: string | null;
  latitude: number;
  longitude: number;
  latitude_fin: number | null;
  longitude_fin: number | null;
  debut: string | null;
  fin: string | null;
  mis_a_jour_le: string | null;
}

export interface EvenementsRoutiers extends EnteteVeille { resultats: EvenementRoutier[]; }

export interface StationCarburant {
  reference: string;
  adresse: string;
  ville: string;
  code_postal: string;
  latitude: number;
  longitude: number;
  carburants_disponibles: string[];
  /** Carburants que la station vend d'ordinaire et n'a plus : le signal d'une pénurie. */
  ruptures_temporaires: string[];
  /** Carburants que la station ne vend plus : pas un signal de pénurie. */
  ruptures_definitives: string[];
  prix: Record<string, { prix: number; maj: string | null }>;
  automate_24_24: boolean;
  mis_a_jour_le: string | null;
}

export interface StationsCarburant extends EnteteVeille {
  bilan: { total: number; en_rupture: number; a_sec: number };
  resultats: StationCarburant[];
}

export interface ObservationMeteo {
  station: string;
  nom: string;
  altitude_m: number | null;
  latitude: number;
  longitude: number;
  /** Distance au centre de l'emprise, quand il y en a un. */
  distance_km: number | null;
  mesure_le: string | null;
  /** Une mesure absente vaut `null`, jamais zéro : toutes les stations ne mesurent pas tout. */
  temperature_c: number | null;
  humidite_pct: number | null;
  vent_kmh: number | null;
  vent_direction: number | null;
  rafale_kmh: number | null;
  pluie_6min_mm: number | null;
  neige_cm: number | null;
  heure_le: string | null;
  pluie_1h_mm: number | null;
  rafale_1h_kmh: number | null;
  /** Cumul construit par le serveur, heure après heure : il porte sur `heures_cumulees`
   * heures, 24 au plus. */
  pluie_24h_mm: number | null;
  heures_cumulees: number;
}

export interface ObservationsMeteo extends EnteteVeille { resultats: ObservationMeteo[]; }

/** Tronçon de cours d'eau surveillé par Vigicrues. `trace` n'est joint que pour la carte. */
export interface TronconCrues {
  code: string;
  nom: string;
  /** 1 vert, 2 jaune, 3 orange, 4 rouge. */
  niveau: number;
  couleur: string;
  publie_le: string | null;
  trace?: { type: string; coordinates: unknown };
}
export interface VigilanceCrues extends EnteteVeille { resultats: TronconCrues[]; }

export interface RestrictionEauDepartement {
  departement_code: string;
  nom: string;
  /** '' (aucune), 'vigilance', 'alerte', 'alerte_renforcee' ou 'crise' : le plus élevé des trois. */
  niveau: string;
  niveau_superficielle: string;
  niveau_souterraine: string;
  niveau_potable: string;
}
export interface RestrictionsEau {
  source: string;
  releve_le: string | null;
  perime: boolean;
  date_donnees: string | null;
  libelles: Record<string, string>;
  mon_departement: RestrictionEauDepartement | null;
  departements: RestrictionEauDepartement[];
}

/** Surface brûlée des trente derniers jours, vue par satellite. Une mémoire, pas une alerte. */
export interface ZoneBrulee {
  reference: string;
  date_feu: string | null;
  commune_nom: string;
  departement_nom: string;
  surface_ha: number | null;
  latitude: number;
  longitude: number;
  distance_km: number | null;
  trace?: { type: string; coordinates: unknown };
}
export interface ZonesBrulees extends EnteteVeille { resultats: ZoneBrulee[]; }

export interface DangerFeuDepartement {
  departement_code: string;
  nom: string;
  /** 1 faible, 2 modéré, 3 élevé, 4 très élevé. */
  niveau_demain: number | null;
  niveau_apres_demain: number | null;
}
export interface MeteoForets {
  source: string;
  releve_le: string | null;
  perime: boolean;
  /** Faux d'octobre à mai : Météo-France ne publie alors rien. */
  en_saison: boolean;
  /** Faux si une carte a été publiée mais que le serveur n'a pas su la lire. */
  compris: boolean;
  libelles: Record<string, string>;
  mon_departement: DangerFeuDepartement | null;
  departements: DangerFeuDepartement[];
}

/** Risque d'avalanche d'un massif (bulletin de Météo-France), de 1 faible à 5 très fort.
 * `risque` est null quand il n'y a pas de bulletin (hors saison). */
export interface MassifAvalanche {
  massif_code: number;
  nom: string;
  chaine: string;
  departement_nom: string;
  risque: number | null;
  risque_demain: number | null;
  commentaire: string;
  resume: string;
  publie_le: string | null;
  valide_jusqu_a: string | null;
  trace?: { type: string; coordinates: unknown };
}
export interface RisqueAvalanche extends EnteteVeille {
  libelles: Record<string, string>;
  resultats: MassifAvalanche[];
}

/** Arrêté de circulation d'une collectivité (DiaLog) qui change un itinéraire. */
export interface ArreteCirculation {
  reference: string;
  categorie: 'FERMETURE' | 'POIDS_LOURDS' | 'ALTERNAT';
  categorie_libelle: string;
  description: string;
  autorite: string;
  voies: string;
  /** Tonnage à partir duquel l'interdiction s'applique, pour les poids lourds. */
  tonnage_max: number | null;
  debut: string | null;
  /** null = arrêté permanent. */
  fin: string | null;
  url: string;
  latitude: number;
  longitude: number;
  trace?: { type: string; geometries?: unknown; coordinates?: unknown };
}
export interface ArretesCirculation extends EnteteVeille {
  bilan: { FERMETURE: number; POIDS_LOURDS: number; ALTERNAT: number };
  resultats: ArreteCirculation[];
}

/** Qualité de l'air ESTIMÉE par modèle (OpenWeather) dans une ville de la liste fixe du serveur.
 * L'indice va de 1 (bon) à 5 (très mauvais) : ce n'est pas l'indice ATMO français, et ce n'est
 * pas une mesure de station. Mention de la source obligatoire (licence CC BY-SA 4.0). */
export interface PointQualiteAir {
  code: string;
  nom: string;
  departement: string;
  /** Vide quand l'estimation est trop ancienne pour être donnée comme actuelle. */
  indice: number | null;
  libelle: string;
  /** Concentrations en µg/m³ : pm2_5, pm10, no2, o3, so2, co. */
  composants: Record<string, number>;
  mesure_le: string;
  /** Le plus mauvais indice prévu dans les 24 heures, et sa première heure. */
  pire_24h: number | null;
  pire_24h_libelle: string;
  pire_24h_le: string | null;
  latitude: number;
  longitude: number;
  distance_km: number | null;
}
export interface QualiteAir extends EnteteVeille {
  libelles: Record<string, string>;
  /** La ville de la liste la plus proche du centre demandé, où qu'elle soit. */
  plus_proche: PointQualiteAir | null;
  resultats: PointQualiteAir[];
}

export type GraviteAntenne = 'TOTALE' | 'PARTIELLE' | 'DECLAREE';

/** Une antenne mobile déclarée en panne ou en maintenance par son opérateur (fichier quotidien
 * de l'Arcep). `depuis` : le début déclaré, ou à défaut le jour où notre serveur a vu la panne
 * pour la première fois (`debut_declare` faux). */
export interface AntenneIndisponible {
  cle: string;
  operateur: string;
  commune: string;
  gravite: GraviteAntenne;
  voix_hs: boolean | null;
  donnees_hs: boolean | null;
  technologies: Record<string, 'OK' | 'HS'>;
  motif: 'INCIDENT' | 'MAINTENANCE' | '';
  depuis: string;
  debut_declare: boolean;
  latitude: number;
  longitude: number;
  distance_km: number | null;
}
export interface AntennesIndisponibles extends EnteteVeille {
  /** Date du fichier de l'Arcep : un état quotidien, publié vers 10 h. */
  jour_du_fichier: string | null;
  /** Pannes déclarées depuis plus de six mois : comptées, pas montrées. */
  ecartees: number;
  ecartees_par_operateur: Record<string, number>;
  par_operateur: Record<string, number>;
  resultats: AntenneIndisponible[];
}

export const LIBELLES_GRAVITE_ANTENNE: Record<GraviteAntenne, string> = {
  TOTALE: 'Voix et données coupées', PARTIELLE: 'Service partiel', DECLAREE: 'Déclarée indisponible',
};

/** « 4G données, 5G données » : les technologies qu'un opérateur dit hors service sur un site. */
export function technologiesCoupees(technologies: Record<string, 'OK' | 'HS'>): string {
  const noms: Record<string, string> = {
    voix2g: '2G voix', voix3g: '3G voix', voix4g: '4G voix', data3g: '3G données', data4g: '4G données', data5g: '5G données',
  };
  return Object.keys(noms).filter(cle => technologies[cle] === 'HS').map(cle => noms[cle]).join(', ');
}

export type EtatSurcote = 'FORTE' | 'MARQUEE' | 'NORMALE' | 'INCONNUE';

/** Un marégraphe (Shom) : le niveau de la mer mesuré, et ce que notre serveur en déduit. La
 * marée attendue est CALCULÉE par notre serveur à partir de l'historique de la station ; la
 * surcote est donc une estimation, donnée avec son incertitude. Ni prédiction officielle de
 * marée, ni alerte. */
export interface NiveauMer {
  code: string;
  nom: string;
  etat: EtatSurcote;
  niveau_m: number | null;
  niveau_le: string | null;
  maree_attendue_m: number | null;
  surcote_cm: number | null;
  incertitude_cm: number | null;
  /** Prochaine pleine mer, au niveau qu'on verra si la surcote du moment se maintient. */
  pleine_mer_le: string | null;
  pleine_mer_niveau_m: number | null;
  /** Le plus haut niveau mesuré par ce marégraphe sur la période ajustée, pour repère. */
  maximum_m: number | null;
  maximum_le: string | null;
  jours_ajustes: number | null;
  latitude: number;
  longitude: number;
  distance_km: number | null;
}
export interface NiveauxMer extends EnteteVeille {
  bilan: Record<EtatSurcote, number>;
  resultats: NiveauMer[];
}

export const LIBELLES_ETAT_SURCOTE: Record<EtatSurcote, string> = {
  FORTE: 'Forte surcote', MARQUEE: 'Surcote marquée', NORMALE: 'Niveau attendu', INCONNUE: 'Sans estimation',
};

export type TendanceEau = 'HAUSSE_RAPIDE' | 'HAUSSE' | 'STABLE' | 'BAISSE' | 'INCONNUE';

/** Une station de mesure en rivière (Hub'Eau). La hauteur est celle lue à l'échelle de la
 * station : elle ne se compare qu'à elle-même, d'où la variation sur une et trois heures. */
export interface StationHydrometrique {
  code: string;
  nom: string;
  cours_eau: string;
  tendance: TendanceEau;
  hauteur_m: number | null;
  hauteur_le: string | null;
  variation_1h_cm: number | null;
  variation_3h_cm: number | null;
  debit_m3s: number | null;
  latitude: number;
  longitude: number;
  distance_km: number | null;
}
export interface HauteursEau extends EnteteVeille {
  bilan: Record<TendanceEau, number>;
  resultats: StationHydrometrique[];
}

export const LIBELLES_TENDANCE_EAU: Record<TendanceEau, string> = {
  HAUSSE_RAPIDE: 'Hausse rapide', HAUSSE: 'En hausse', STABLE: 'Stable', BAISSE: 'En baisse', INCONNUE: 'Sans mesure récente',
};

/** « +36 cm », « −4 cm », « stable » : une variation de hauteur d'eau lisible d'un coup d'œil. */
export function variationEau(cm: number | null): string {
  if (cm == null) return '';
  const arrondi = Math.round(cm);
  if (arrondi === 0) return 'stable';
  return `${arrondi > 0 ? '+' : '−'}${Math.abs(arrondi)} cm`;
}

export type EtatCirculation = 'BLOQUE' | 'SATURE' | 'DENSE' | 'FLUIDE' | 'INCONNU';

/** Un tronçon mesuré du réseau routier national, dans un sens de circulation. `origine` dit
 * d'où vient l'état : « OFFICIEL », l'exploitant de la route ; « ESTIME », notre serveur, qui
 * compare la vitesse mesurée à la vitesse habituelle qu'il a apprise pour ce tronçon. */
export interface TronconCirculation {
  code: string;
  axe: string;
  sens: string;
  etat: EtatCirculation;
  origine: 'OFFICIEL' | 'ESTIME' | '';
  vitesse_kmh: number | null;
  debit_veh_h: number | null;
  mesure_le: string | null;
  /** Vide tant que le serveur n'a pas assez de mesures pour la connaître. */
  vitesse_habituelle_kmh: number | null;
  /** +1 : chaussée à droite du trait, -1 : à gauche (les deux sens partagent le même trait). */
  cote: number;
  latitude: number;
  longitude: number;
  distance_km: number | null;
  trace?: { type: string; coordinates?: unknown };
}
export interface Circulation extends EnteteVeille {
  bilan: Record<EtatCirculation, number>;
  resultats: TronconCirculation[];
}

export const LIBELLES_ETAT_CIRCULATION: Record<EtatCirculation, string> = {
  BLOQUE: 'Bloqué', SATURE: 'Saturé', DENSE: 'Dense', FLUIDE: 'Fluide', INCONNU: 'Sans mesure',
};

/** « EST_OUEST » -> « vers l'ouest ». Vide quand le sens n'est pas renseigné. */
export function sensDeCirculation(sens: string): string {
  const vers: Record<string, string> = {
    NORD_SUD: 'vers le sud', SUD_NORD: 'vers le nord', EST_OUEST: 'vers l’ouest', OUEST_EST: 'vers l’est',
  };
  return vers[sens] ?? '';
}

/** Part des passages aux urgences attribués à une pathologie, dans un département. Un taux
 * pour 100 000 passages aux urgences : une tendance, pas un nombre de malades. */
export interface IndicateurSante {
  pathologie: string;
  libelle: string;
  semaine: string;
  debut_semaine: string;
  taux_urgences: number | null;
  taux_urgences_precedent: number | null;
  taux_sos: number | null;
  /** 'hausse', 'baisse', 'stable', ou '' si la comparaison est impossible. */
  tendance: string;
}
export interface SanteUrgences {
  source: string;
  releve_le: string | null;
  perime: boolean;
  departement_code: string | null;
  departement_nom: string | null;
  indicateurs: IndicateurSante[];
}

/** Dernière mesure d'une balise du réseau Téléray (ASNR). Un affichage, jamais une alerte :
 * une forte pluie suffit à faire monter la mesure. */
export interface BaliseRadioactivite {
  station: number;
  nom: string;
  latitude: number;
  longitude: number;
  distance_km: number | null;
  /** Balise posée autour d'une installation nucléaire. */
  proche_installation: boolean;
  debit_nsv_h: number;
  /** Niveau habituel de cette balise ; null si l'ASNR ne le donne pas. */
  bruit_de_fond_nsv_h: number | null;
  ecart_nsv_h: number | null;
  valide: boolean;
  mesure_le: string;
}
export interface Radioactivite extends EnteteVeille { resultats: BaliseRadioactivite[]; }

export interface Seisme {
  reference: string;
  date: string;
  magnitude: number;
  profondeur_km: number | null;
  lieu: string;
  zone: string;
  /** 'earthquake', 'quarry blast', 'explosion', 'landslide'… */
  nature: string;
  nature_libelle: string;
  latitude: number;
  longitude: number;
  distance_km: number | null;
}
export interface Seismes extends EnteteVeille { resultats: Seisme[]; }

/** Sismicité autour d'un volcan français : un compte de séismes, pas un état du volcan. */
export interface Volcan {
  code: string;
  nom: string;
  territoire: string;
  latitude: number;
  longitude: number;
  observatoire: string;
  url: string;
  seismes_7_jours: number;
  seismes_7_jours_precedents: number;
  magnitude_max: number | null;
  dernier_seisme: string | null;
  distance_km: number | null;
  /** Vrai si ce volcan concerne le territoire regardé. */
  a_portee: boolean;
}
export interface Volcans { source: string; releve_le: string | null; perime: boolean; rayon_km: number; volcans: Volcan[]; }

/** Défibrillateur déclaré en service dans la base nationale. Déclaré, pas vérifié. */
export interface Defibrillateur {
  reference: string;
  nom: string;
  adresse: string;
  acces: string;
  acces_libre: boolean;
  emplacement: string;
  disponibilite: string;
  latitude: number;
  longitude: number;
  distance_km: number | null;
}
export interface Defibrillateurs extends EnteteVeille { total: number; resultats: Defibrillateur[]; }

/** Pixel chaud vu par satellite ces deux derniers jours (NASA FIRMS). Pas forcément un feu :
 * `source_fixe` marque ceux qui reviennent au même endroit (usines, torchères). */
export interface FoyerActif {
  reference: string;
  date: string;
  latitude: number;
  longitude: number;
  distance_km: number | null;
  confiance: string;
  puissance_mw: number | null;
  satellite: string;
  source_fixe: boolean;
}
export interface FoyersActifs extends EnteteVeille {
  /** Nombre de sources fixes dans l'emprise, qu'elles soient rendues ou non. */
  sources_fixes: number;
  resultats: FoyerActif[];
}

/** Réglage de l'annonce des foyers détectés près d'une institution. */
export interface ConfigurationAlerteFeu {
  id: number;
  institution: string;
  actif: boolean;
  rayon_km: number;
}

/** Pluie prévue (prévision immédiate de Météo-France) : une image nationale par quart d'heure,
 * à poser sur la carte entre les quatre `coins`. C'est une prévision recalée chaque heure sur
 * les radars, pas l'image radar elle-même — l'écran doit le dire. */
export interface PluiePrevue {
  source: string;
  releve_le: string | null;
  perime: boolean;
  /** Heure du calcul qui a produit les images. */
  calcul: string | null;
  /** Haut-gauche, haut-droite, bas-droite, bas-gauche : [longitude, latitude]. */
  coins: [number, number][];
  echeances: string[];
}

/** Un champ de vent tel que notre serveur le rend, pour l'animation de la carte. */
export interface ChampVent {
  echeance: string;
  largeur: number;
  hauteur: number;
  /** Position du premier point : le coin nord-ouest. */
  ouest: number;
  nord: number;
  /** Pas de la grille, en degrés. */
  pas: number;
  vitesse_max_ms: number;
  /** Base 64 : un octet par point pour la composante vers l'est, puis autant vers le nord. */
  donnees: string;
}

/** Vent moyen prévu (modèle ARPEGE de Météo-France), heure par heure. `champ` n'est rempli que
 * si l'on a demandé une heure précise. Le vent moyen à dix kilomètres de maille : ni les
 * rafales, ni une mesure. */
export interface VentPrevu {
  source: string;
  releve_le: string | null;
  perime: boolean;
  calcul: string | null;
  echeances: string[];
  champ: ChampVent | null;
}

export type FamillePrecipitationHiver = 'VERGLAS' | 'NEIGE' | 'NEIGE_HUMIDE' | 'GRESIL' | 'GRELE';

/** Neige, verglas et grêle prévus (type de précipitation de la prévision immédiate), peints par
 * notre serveur. `ici` : ce qui est prévu au point demandé pour chaque échéance ("" : rien de
 * tel ; null : hors de la métropole), et `pire`, le plus dangereux de la liste. C'est le TYPE
 * de ce qui tombe, pas la quantité ni la tenue au sol ; une prévision, pas une alerte. */
export interface PrecipitationsHiver extends PluiePrevue {
  legende: { cle: FamillePrecipitationHiver; libelle: string; couleur: string }[];
  ici: {
    latitude: number;
    longitude: number;
    couvert: boolean;
    pire: FamillePrecipitationHiver | '';
    familles: { echeance: string; famille: FamillePrecipitationHiver | '' | null }[];
  } | null;
}

/** Un palier de la légende des rafales : sa teinte vaut « à partir de tant de km/h ». */
export interface PalierRafales {
  a_partir_de_kmh: number;
  couleur: string;
}

/** Rafales prévues (même prévision immédiate que la pluie), peintes par notre serveur en
 * paliers de km/h. `ici` n'est rempli que si l'on a demandé la lecture en un point : le palier
 * prévu à cet endroit pour chaque échéance (0 : moins que le premier palier ; null : hors de
 * la métropole). Une prévision, ni une mesure ni une alerte. */
export interface RafalesPrevues extends PluiePrevue {
  legende: PalierRafales[];
  ici: {
    latitude: number;
    longitude: number;
    couvert: boolean;
    maximum_kmh: number | null;
    paliers: { echeance: string; a_partir_de_kmh: number | null }[];
  } | null;
}

/** Réglage de l'annonce de vigilance d'une institution (voir ConfigurationAlerteVigilance). */
export interface ConfigurationAlerteVigilance {
  id: number;
  institution: string;
  institution_nom?: string | null;
  actif: boolean;
  /** 2 jaune, 3 orange, 4 rouge. */
  couleur_min: number;
  date_creation?: string;
}


/** GET /api/orages/ (backend/core/orages.py, 19/11/2026). Trois natures d'information que
 * l'écran ne mélange pas : ce que le radar a vu (`releves`), NOS estimations — qui ne sont pas
 * des prévisions — (`estimations`), et ce que Météo-France prévoit (`prevision_meteo_france`). */
/** `lon`/`lat` : centre de la commune, pour la carte (absents des cellules d'avant le 20/11/2026). */
export interface CommuneOrage { code: string; nom: string; dans_min?: number; lon?: number; lat?: number; }

/** Un noyau tobac placé sur la carte. */
export interface NoyauOrage { lon: number; lat: number; seuil: number; max_mmh: number; fusion: boolean; division: boolean; }

export interface SuiviCellule {
  suivie_depuis_min: number; noyaux: number; noyaux_intenses: number;
  /** Évolution du noyau principal depuis l'image d'il y a dix minutes (null sans recul). */
  surface_10min_km2: number | null; max_10min_mmh: number | null;
  evolution: 'renforcement' | 'affaiblissement' | 'stable' | null;
  fusion: boolean; division: boolean;
  noyaux_positions?: NoyauOrage[];
}

export interface CelluleOrage {
  identifiant: string;
  distance_km: number | null;
  /** Contour de la cellule et couloir balayé en une heure (estimation), en GeoJSON. */
  contour: GeoJSON.Polygon;
  couloir: GeoJSON.Polygon | null;
  releves: {
    intensite_max_mmh: number; intensite_moyenne_mmh: number; libelle: string; surface_km2: number;
    tendance_mmh: number | null; communes_sous_la_pluie: CommuneOrage[];
    rafale_mesuree: { kmh: number; station: string; mesure_le: string | null } | null;
    /** Positions de l'heure écoulée : [heure, lat, lon, intensité max (absente avant le 20/11/2026)]. */
    trace: [string, number, number, number?][];
    /** Éclairs vus par le satellite MTG sous la cellule, autour de l'heure de l'image. */
    eclairs: number | null;
    /** Histoire de la cellule sur l'heure écoulée, suivie par tobac (backend/core/suivi_tobac.py). */
    suivi: SuiviCellule | null;
    /** Signatures Doppler (backend/core/doppler.py), selon les relevés des radars proches. */
    doppler: {
      /** `lon`/`lat` : où le radar a mesuré la rotation. */
      rotation: { vrot_ms: number; elevations: number[]; radar: string; lon?: number; lat?: number } | null;
      grele: { z_max_dbz: number | null; sommet_45_m: number | null; isotherme0_m: number | null; probable: boolean; radar: string } | null;
      divergence: { ms: number; radar: string } | null;
      polarimetrie: { grele: boolean; portes_grele: number; debris: boolean; radar: string } | null;
      radars: string[]; heure: string;
    } | null;
  };
  estimations: {
    cap_deg: number | null; vers: string | null; vitesse_kmh: number | null;
    communes_atteintes: CommuneOrage[]; ligne_de_grain: boolean; longueur_km: number;
  };
  prevision_meteo_france: {
    grele: boolean; rafale_kmh: number | null;
    /** Diagnostic de grêle d'AROME-PI (kg/m²) ; niveau au-delà de 8 et de 12 kg/m². */
    grele_diagnostic_kgm2: number | null; grele_niveau: string | null;
  };
}

/** Cumuls de pluie d'une commune selon le radar, en mm. `fort` : fenêtres au-delà du repère. */
export interface CumulCommune {
  code: string; nom: string; mm: Record<'1h' | '3h' | '24h', number>; fort: string[];
  /** Nos estimations pour l'heure qui vient (extrapolation des images radar par pysteps). */
  estimation: { cumul_mm: number; max_mmh: number; intense_dans_min: number | null } | null;
}

export interface CumulsPluie {
  /** Images réellement disponibles par fenêtre (un service relancé n'a pas 24 h d'historique). */
  fenetres: Partial<Record<'1h' | '3h' | '24h', number>>;
  attendues: Record<'1h' | '3h' | '24h', number>;
  seuils_mm: Record<'1h' | '3h' | '24h', number>;
  ma_commune: CumulCommune | null;
  plus_arrosees: CumulCommune[];
  pluie_intense_attendue: CumulCommune[];
}

/** GET /api/orages/radar/ : la dernière pluie OBSERVÉE par le radar, en image pour la carte
 * (backend/core/carte_radar.py). `heure` désigne l'image. */
export interface PluieRadar {
  source: string; releve_le: string | null; perime: boolean;
  heure: string | null;
  coins: [[number, number], [number, number], [number, number], [number, number]] | null;
  legende: { a_partir_de_mmh: number; couleur: string }[];
  /** Heures des images observées gardées (une heure), pour la boucle. */
  passees: string[];
  /** Images de l'heure qui vient extrapolées de la dernière : NOS ESTIMATIONS. */
  estimees: { minutes: number; echeance: string }[];
}

export interface OragesRadar {
  source: string; releve_le: string | null; perime: boolean;
  heure_image: string | null; radars: number; radars_absents: string[];
  centre: { latitude: number; longitude: number } | null; rayon_km: number | null;
  couvert: boolean | null;
  cellules: CelluleOrage[];
  cumuls: CumulsPluie | null;
  foudre: FoudreIci | null;
  /** Blitzortung, à titre indicatif seulement (jamais analysé ni annoncé). */
  blitzortung: { source: string; perime: boolean; impacts_15min: number; impacts_1h: number; dernier_ici: string | null } | null;
}

/** Éclairs vus par le satellite MTG autour de la commune (backend/core/foudre.py). Comptés
 * depuis la donnée la plus récente, qui a 10 à 20 minutes de retard sur l'éclair. */
export interface FoudreIci {
  source: string; releve_le: string | null; perime: boolean;
  eclairs_15min: number; eclairs_1h: number; dernier_ici: string | null; derniere_donnee: string;
}

/** Valeurs du potentiel d'orage de feu en un point (core/orages_de_feu.valeur_au_point). */
export interface ValeurOrageFeu {
  /** Puissance de feu nécessaire pour un orage, en GW ; null si aucun orage n'est possible. */
  pft_gw: number | null;
  c_haines: number;
  /** 0 (rien) à 3 (très élevé). */
  palier: number;
  potentiel: 'modéré' | 'élevé' | 'très élevé' | null;
}

/** Potentiel d'orage de feu (pyrocumulonimbus), nos estimations, pour l'après-midi
 * d'aujourd'hui et de demain (GET /api/orages-de-feu/). */
export interface PotentielOrageFeu {
  source: string;
  releve_le: string | null;
  perime: boolean;
  nos_estimations: true;
  /** Croisé avec la météo des forêts : rien n'est peint hors saison, ni sous le danger « élevé ». */
  meteo_forets: { en_saison: boolean; danger_minimum: string };
  calcul: string | null;
  coins: [number, number][];
  legende: { palier: number; libelle: string; pft_jusqua_gw: number; couleur: string }[];
  centre: { latitude: number; longitude: number } | null;
  rayon_km: number | null;
  echeances: {
    echeance: string;
    palier_max_france: number;
    ici?: ValeurOrageFeu | null;
    palier_max_autour?: number | null;
  }[];
}

/** Un feu en cours suivi par le satellite MTG (GET /api/feux-suivis/). */
export interface FeuSuivi {
  identifiant: string;
  latitude: number;
  longitude: number;
  distance_km: number | null;
  premier_vu: string;
  dernier_vu: string;
  statut: 'actif' | 'plus vu';
  /** Puissance rayonnée à la dernière image où il est vu, en MW. */
  puissance_mw: number;
  puissance_max_mw: number;
  instant_max: string;
  pixels: number;
  confirme: boolean;
  source_fixe: boolean;
  /** [créneau, MW, pixels] des dernières 24 heures. */
  courbe: [string, number, number][];
  contexte: {
    orage?: { identifiant: string; distance_km: number; au_dessus: boolean; intensite_max_mmh: number;
              eclairs: number | null; rafale_descendante: boolean; rotation: boolean; grele: boolean } | null;
    eclairs_30_min?: number;
    masque_par_nuage?: boolean;
    potentiel?: (ValeurOrageFeu & { echeance: string; puissance_estimee_gw: [number, number];
                                    atteint_le_seuil: boolean }) | null;
  };
}

export interface FeuxSuivis {
  source: string;
  releve_le: string | null;
  perime: boolean;
  centre: { latitude: number; longitude: number } | null;
  rayon_km: number | null;
  emprise_connue: boolean;
  sources_fixes: number;
  resultats: FeuSuivi[];
}
