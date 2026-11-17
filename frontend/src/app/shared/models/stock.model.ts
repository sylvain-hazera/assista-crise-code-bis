export type ConservationStock = 'AMBIANT' | 'FRAIS' | 'SURGELE';
export type PreparationStock = '' | 'PRET' | 'A_RECHAUFFER' | 'A_CUISINER';
export type CuissonLieu = 'AUCUNE' | 'RECHAUFFAGE' | 'CUISINE';

export const LABELS_CONSERVATION: Record<ConservationStock, string> = {
  AMBIANT: 'Température ambiante', FRAIS: 'Au frais (0 à 4 °C)', SURGELE: 'Surgelé (−18 °C)',
};
export const LABELS_PREPARATION: Record<Exclude<PreparationStock, ''>, string> = {
  PRET: 'Prêt à consommer', A_RECHAUFFER: 'À réchauffer', A_CUISINER: 'À cuisiner',
};
export const LABELS_CUISSON: Record<CuissonLieu, string> = {
  AUCUNE: 'Rien pour chauffer', RECHAUFFAGE: 'De quoi réchauffer', CUISINE: 'Une cuisine',
};

export type TypeMouvementStock = 'ENTREE' | 'SORTIE' | 'TRANSFERT' | 'INVENTAIRE';

export const LABELS_TYPE_MOUVEMENT: Record<TypeMouvementStock, string> = {
  ENTREE: 'Entrée', SORTIE: 'Sortie', TRANSFERT: 'Transfert', INVENTAIRE: 'Inventaire',
};

export const LABELS_CATEGORIE_STOCK: Record<string, string> = {
  ENGIN: 'Engin agricole / chantier / spécial',
  NETTOYAGE: 'Nettoyage et remise en état',
  POMPAGE: 'Pompage et évacuation d\'eau',
  DEBLAI_MANUTENTION: 'Déblaiement et manutention',
  ENERGIE_ECLAIRAGE: 'Énergie et éclairage',
  PROTECTION_BATIMENTS: 'Protection des bâtiments',
  OUTILLAGE_TERRAIN: 'Outillage et équipement de terrain',
  PROTECTION_INDIVIDUELLE: 'Protection individuelle',
  ACCUEIL_HEBERGEMENT: 'Accueil et hébergement d\'urgence',
  DIVERS: 'Divers / consommables',
};

/** Un lieu où le stock est rangé : local, garage, armoire, véhicule. */
export interface DepotStock {
  id: string;
  institution: string;
  nom: string;
  adresse: string;
  commentaire: string;
  /** Renseigné quand ce dépôt est le stock d'un point d'accueil pendant une crise. */
  point?: string | null;
  froid_positif: boolean;
  froid_negatif: boolean;
  cuisson: CuissonLieu;
  actif: boolean;
  latitude: number | null;
  longitude: number | null;
}

export interface ArticleStock {
  id: string;
  reference: string;
  designation: string;
  categorie: string;
  categorie_libelle?: string;
  unite: string;
  /** Total en deçà duquel l'article est signalé. null = pas d'alerte. */
  seuil_alerte: string | null;
  perissable: boolean;
  /** Coût moyen pondéré, indicatif. */
  prix_unitaire: string | null;
  /** Denrées : AMBIANT, FRAIS ou SURGELE ; et ce qu'il faut pour la consommer (vide : pas une denrée). */
  conservation: ConservationStock;
  preparation: PreparationStock;
  code_barres: string;
  description: string;
  actif: boolean;
}

export interface LotStock { depot: string; lot: string; date_peremption: string | null; quantite: string; }

/** Un article et ce qu'il en reste. Les quantités arrivent en texte (décimaux exacts). */
export interface LigneEtatStock extends ArticleStock {
  total: string;
  par_depot: Record<string, string>;
  lots: LotStock[];
  sous_seuil: boolean;
  perime: string;
  bientot_perime: string;
  prochaine_peremption: string | null;
  valeur: string | null;
  /** Dépôts où cette denrée est rangée sans ce qu'il lui faut (froid, cuisson). */
  mal_range: { depot: string; nom: string; manques: string[] }[];
  /** Mis de côté pour quelqu'un : toujours au dépôt, mais plus à sortir pour un autre. */
  reserve: string;
  disponible: string;
}

export interface EtatStock {
  institution: string;
  institution_nom: string;
  depots: DepotStock[];
  articles: LigneEtatStock[];
  alertes: { sous_seuil: number; perimes: number; bientot_perimes: number; mal_ranges: number };
  valeur_totale: string;
  jours_alerte_peremption: number;
}

export interface MouvementStock {
  id: string;
  article: string;
  article_reference: string;
  article_designation: string;
  unite: string;
  depot: string;
  depot_nom: string;
  type: TypeMouvementStock;
  type_libelle: string;
  /** Signée : positive à l'entrée, négative à la sortie. */
  quantite: string;
  lot: string;
  date_peremption: string | null;
  prix_unitaire: string | null;
  motif: string;
  tiers: string;
  crise: string | null;
  crise_nom: string | null;
  mission_titre: string | null;
  equipe_nom: string | null;
  auteur_nom: string;
  date_mouvement: string;
}

export interface SaisieMouvement {
  article: string;
  depot: string;
  type: TypeMouvementStock;
  quantite: string | number;
  depot_destination?: string;
  lot?: string;
  date_peremption?: string;
  prix_unitaire?: string | number;
  motif?: string;
  tiers?: string;
  crise?: string;
}

export interface BilanImportStock {
  colonnes: string[];
  lignes: number;
  articles_crees: number;
  articles_existants: number;
  depots_crees: number;
  quantites_posees: number;
  erreurs: { ligne: number; message: string }[];
  simulation: boolean;
}

/** Le stock d'un point d'accueil, d'après le journal des mouvements. */
export interface EtatStockPoint {
  point: string;
  point_nom: string;
  peut_distribuer: boolean;
  /** J'ai une institution : je peux doter ce point depuis mes dépôts, et rapatrier mon reste. */
  peut_doter: boolean;
  institution_nom: string;
  a_rapatrier: boolean;
  lignes: { item: string; item_nom: string; quantite: string | null; unite: string; niveau_stock: string | null; suivi: boolean;
    conservation: ConservationStock; preparation: PreparationStock; manques: string[] }[];
  /** Ce que le point a pour garder et préparer des denrées. */
  moyens: { froid_positif: boolean; froid_negatif: boolean; cuisson: CuissonLieu };
  mouvements: MouvementStock[];
}

export type GesteStockPoint = 'doter' | 'recevoir' | 'distribuer' | 'compter' | 'rapatrier' | 'transferer' | 'moyens';

// ── Tiers, commandes, factures, prêts ──────────────────────────────────────────────────────
export type TypeTiersStock = 'PARTICULIER' | 'PROFESSIONNEL' | 'ASSOCIATION' | 'COLLECTIVITE';
export const LABELS_TYPE_TIERS: Record<TypeTiersStock, string> = {
  PARTICULIER: 'Particulier', PROFESSIONNEL: 'Professionnel, entreprise', ASSOCIATION: 'Association', COLLECTIVITE: 'Collectivité, service public',
};

/** Fournisseur, donateur, emprunteur ou prêteur. */
export interface TiersStock {
  id: string;
  type: TypeTiersStock;
  type_libelle?: string;
  nom: string;
  contact: string;
  email: string;
  telephone: string;
  adresse: string;
  siret: string;
  notes: string;
  est_fournisseur: boolean;
  actif: boolean;
}

export type StatutCommandeStock = 'BROUILLON' | 'COMMANDEE' | 'RECUE_EN_PARTIE' | 'RECUE' | 'ANNULEE';

export interface LigneCommandeStock {
  id?: string;
  article: string;
  article_designation?: string;
  article_reference?: string;
  unite?: string;
  quantite: string | number;
  prix_unitaire: string | number | null;
  quantite_recue?: string;
}

export interface CommandeStock {
  id: string;
  numero: string;
  tiers: string;
  tiers_nom: string;
  statut: StatutCommandeStock;
  statut_libelle: string;
  depot: string | null;
  depot_nom: string | null;
  date_commande: string | null;
  livraison_prevue: string | null;
  commentaire: string;
  lignes: LigneCommandeStock[];
  total: string | null;
}

export interface FactureStock {
  id: string;
  tiers: string;
  tiers_nom: string;
  commande: string | null;
  commande_numero: string | null;
  numero: string;
  date_facture: string;
  montant_ht: string | null;
  montant_ttc: string;
  echeance: string | null;
  payee_le: string | null;
  commentaire: string;
  a_une_piece: boolean;
  en_retard: boolean;
}

export type SensPret = 'CONSENTI' | 'RECU';
export type EtatMaterielPrete = 'NEUF' | 'BON' | 'USAGE' | 'DEGRADE' | 'HORS_SERVICE';
export const LABELS_ETAT_PRETE: Record<EtatMaterielPrete, string> = {
  NEUF: 'Neuf', BON: 'Bon état', USAGE: 'Usagé, fonctionne', DEGRADE: 'Dégradé', HORS_SERVICE: 'Hors service',
};

/** Un prêt de matériel, consenti par l'institution ou reçu par elle. */
export interface PretMateriel {
  id: string;
  sens: SensPret;
  sens_libelle: string;
  tiers: string;
  tiers_nom: string;
  tiers_type: string;
  article: string | null;
  depot: string | null;
  depot_nom: string | null;
  designation: string;
  identification: string;
  quantite: string;
  quantite_rendue: string | null;
  unite: string;
  date_debut: string;
  retour_prevu: string | null;
  date_retour: string | null;
  etat_depart: EtatMaterielPrete;
  etat_depart_libelle: string;
  constat_depart: string;
  etat_retour: EtatMaterielPrete | '';
  etat_retour_libelle: string;
  constat_retour: string;
  statut: 'EN_COURS' | 'RENDU' | 'LITIGE';
  statut_libelle: string;
  crise: string | null;
  conditions: string;
  en_retard: boolean;
  photos: { depart: number; retour: number };
}

/** Une ligne à compter dans un dépôt : ce que le stock dit avoir. */
export interface LigneInventaire {
  article: string;
  reference: string;
  designation: string;
  unite: string;
  lot: string;
  date_peremption: string | null;
  attendu: string;
  /** Ce qu'on a compté ; vide : pas comptée, donc pas corrigée. */
  compte?: number | null;
}

// ── Demandes de transfert, réservations, dotations, appareils ──────────────────────────────
/** « Pouvez-vous nous envoyer 20 couvertures ? » : rien ne part tant que le point de départ n'a pas accepté. */
export interface DemandeTransfertStock {
  id: string;
  source: string;
  source_nom: string;
  destination: string;
  destination_nom: string;
  item: string;
  item_nom: string;
  quantite: number;
  quantite_accordee: number | null;
  message: string;
  statut: 'DEMANDEE' | 'ACCEPTEE' | 'REFUSEE' | 'ANNULEE';
  statut_libelle: string;
  reponse: string;
  demande_par_nom: string;
  en_stock_au_depart: string;
  /** Je tiens le point de départ : c'est à moi d'accepter ou de refuser. */
  je_decide: boolean;
  je_demande: boolean;
  date_creation: string;
}

export interface ReservationStock {
  id: string;
  article: string;
  article_designation: string;
  unite: string;
  depot: string;
  depot_nom: string;
  quantite: string;
  pour: string;
  equipe_nom: string | null;
  demande_titre: string | null;
  statut: 'ACTIVE' | 'SERVIE' | 'ANNULEE';
  statut_libelle: string;
  date_creation: string;
}

export interface LotTypeStock {
  id: string;
  nom: string;
  description: string;
  actif: boolean;
  lignes: { article: string; designation: string; unite: string; quantite: string }[];
}
export interface VerificationLot { complet: boolean; lignes: { article: string; designation: string; unite: string; requis: string; libre: string; manque: string }[]; }

export interface AppareilStock {
  id: string;
  designation: string;
  numero: string;
  etat: 'EN_SERVICE' | 'EN_PANNE' | 'REFORME';
  etat_libelle: string;
  depot: string | null;
  depot_nom: string | null;
  date_acquisition: string | null;
  controle_libelle: string;
  controle_periodicite_mois: number | null;
  controle_dernier_le: string | null;
  controle_prochain_le: string | null;
  /** « a_jour », « bientot », « en_retard », ou vide sans contrôle périodique. Signale, ne bloque rien. */
  controle: '' | 'a_jour' | 'bientot' | 'en_retard';
  controles: { date: string; conforme: boolean; commentaire: string }[];
  commentaire: string;
}

export interface DisponibiliteStock {
  cherche: string;
  en_stock: boolean;
  quantite_demandee: number | null;
  articles: { article: string; designation: string; reference: string; unite: string; libre: string;
              lieux: { depot: string; depot_nom: string; au_point: boolean; en_stock: string; reserve: string; libre: string }[] }[];
}
