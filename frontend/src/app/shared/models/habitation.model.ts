export type StatutEvaluationHabitation = 'NON_EVALUEE' | 'PAS_DE_DEGATS' | 'DEGATS_FAIBLES' | 'DEGATS_FORTS' | 'DETRUITE';
/** Ce qui a causé le dommage : le suivi sert pour tout sinistre, pas seulement l'eau. */
export type NatureDegatsHabitation = '' | 'EAU' | 'FEU' | 'VENT' | 'GRELE' | 'NEIGE' | 'TERRAIN' | 'EXPLOSION' | 'AUTRE';
export type StatutChantierHabitation = 'A_DEBLAYER' | 'NETTOYAGE_EN_COURS' | 'TERMINE' | null;
export type TypeLienHabitation = 'PROPRIETAIRE' | 'LOCATAIRE';
export type StatutRattachementHabitation = 'EN_ATTENTE' | 'ACCEPTE' | 'REFUSE';

export interface Habitation {
  id: string;
  crise: string | null;
  zone: string | null;
  zone_nom: string | null;
  adresse: string;
  commune_code: string | null;
  commune_nom: string | null;
  latitude: number | null;
  longitude: number | null;
  parcelle_cadastrale: string | null;
  ban_id: string | null;
  statut_evaluation: StatutEvaluationHabitation;
  statut_chantier: StatutChantierHabitation;
  nature_degats?: NatureDegatsHabitation;
  evalue_par: string | null;
  date_derniere_evaluation: string | null;
  date_creation: string;
  modifie_le: string;
  nb_rattachements_en_attente: number;
  /** Évaluation à pied (20/11/2026) : type de bien, dangers, point replacé, rapprochement. */
  type_bien?: string | null;
  type_bien_nom?: string | null;
  dangers?: string[];
  personne_sur_place?: boolean | null;
  a_reloger?: boolean | null;
  position_corrigee?: boolean;
  /** Rattaché à cette fiche (le même bien, vu deux fois) ; séparable. */
  fusionne_dans?: string | null;
  peut_gerer: boolean;
  crise_nom: string | null;
  surface_habitable_totale: number | null;
  surface_habitable_impactee: number | null;
  surface_non_habitable_totale: number | null;
  surface_non_habitable_impactee: number | null;
  valeur_estimee: string | null;   // décimal sérialisé en texte par l'API
  valeur_source: string | null;
}

export interface ReleveHabitation {
  surface_habitable_totale?: number | null;
  surface_habitable_impactee?: number | null;
  surface_non_habitable_totale?: number | null;
  surface_non_habitable_impactee?: number | null;
  valeur_estimee?: number | null;
  valeur_source?: string | null;
}

export interface PrixDvf {
  prix_m2_median: number | null;
  nb_ventes: number;
}

/** Valeurs foncières indicatives (backend core/dvf.py). */
export interface EstimationDvf {
  erreur: string | null;
  source: string;
  annees?: number[];
  ensemble?: PrixDvf;
  maison?: PrixDvf;
  appartement?: PrixDvf;
  ventes_parcelle?: { date: string; type: string; valeur: number; surface: number }[];
  valeur_indicative?: number | null;
  base_estimation?: string | null;
}

export interface HabitationCommentaire {
  id: string;
  habitation: string;
  auteur: string | null;
  auteur_nom: string;
  commentaire: string;
  date_creation: string;
}

export interface HabitationHistorique {
  id: string;
  habitation: string;
  auteur: string | null;
  auteur_nom: string;
  evenement: string;
  commentaire: string | null;
  date_creation: string;
}

export interface RattachementHabitation {
  id: string;
  habitation: string;
  habitation_adresse: string;
  utilisateur: string | null;
  /** Vide pour une demande antérieure au 11/11/2026 : le prénom n'était pas un champ séparé,
   * et on ne découpe pas rétroactivement `nom_demandeur` — c'est le découpage qui était le
   * défaut. */
  prenom_demandeur: string;
  nom_demandeur: string;
  email_demandeur: string;
  telephone_demandeur: string | null;
  type_lien: TypeLienHabitation;
  statut: StatutRattachementHabitation;
  message: string | null;
  date_demande: string;
  traite_par: string | null;
  traite_par_nom: string | null;
  date_traitement: string | null;
  motif_refus: string | null;
  /** justificatif est write_only côté API -- ce booléen indique juste sa présence, la photo
   * elle-même se récupère via RattachementHabitationService.previewJustificatif. */
  a_justificatif: boolean;
}

export interface ModuleDegatsCrise {
  id: string;
  crise: string;
  crise_nom: string;
  institution: string;
  institution_nom: string;
  actif: boolean;
  zone: string | null;
  zone_nom: string | null;
  active_par: string | null;
  date_activation: string;
  date_desactivation: string | null;
}

export const LABELS_STATUT_EVALUATION: Record<StatutEvaluationHabitation, string> = {
  NON_EVALUEE: 'Non évaluée',
  PAS_DE_DEGATS: 'Pas de dégâts',
  DEGATS_FAIBLES: 'Dégâts faibles',
  DEGATS_FORTS: 'Dégâts forts',
  DETRUITE: 'Détruite',
};

/** États qui constatent un dommage (même liste que côté serveur). */
export const STATUTS_AVEC_DEGATS: StatutEvaluationHabitation[] = ['DEGATS_FAIBLES', 'DEGATS_FORTS', 'DETRUITE'];

export const LABELS_NATURE_DEGATS: Record<Exclude<NatureDegatsHabitation, ''>, string> = {
  EAU: 'Eau (inondation, coulée de boue, submersion)',
  FEU: 'Feu (incendie, feu de forêt)',
  VENT: 'Vent (tempête, tornade)',
  GRELE: 'Grêle',
  NEIGE: 'Neige, glace',
  TERRAIN: 'Mouvement de terrain, séisme',
  EXPLOSION: 'Explosion, accident',
  AUTRE: 'Autre',
};

export const LABELS_STATUT_CHANTIER: Record<string, string> = {
  A_DEBLAYER: 'À déblayer',
  NETTOYAGE_EN_COURS: 'Nettoyage / déblaiement en cours',
  TERMINE: 'Chantier terminé',
};

export const COULEURS_STATUT_EVALUATION: Record<StatutEvaluationHabitation, string> = {
  NON_EVALUEE: '#9ca3af',
  PAS_DE_DEGATS: '#22c55e',
  DEGATS_FAIBLES: '#f59e0b',
  DEGATS_FORTS: '#ef4444',
  // Plus sombre que « dégâts forts » : se distingue aussi imprimé en noir et blanc.
  DETRUITE: '#111827',
};

/** Ce qu'un intervenant a pointé sur le terrain, tant que la commune ne l'a pas validé : une
 * proposition, pas encore une habitation. */
export interface PointageTerrain {
  id: string;
  a_valider: boolean;
  statut: 'A_VALIDER' | 'VALIDE' | 'REFUSE';
  statut_libelle: string;
  crise: string;
  adresse: string;
  commune_nom: string | null;
  latitude: number;
  longitude: number;
  statut_evaluation: StatutEvaluationHabitation;
  nature_degats: NatureDegatsHabitation;
  commentaire: string;
  auteur: string;
  le_mien: boolean;
  date_creation: string;
  /** Une maison est déjà référencée à cet endroit : la validation la complétera. */
  existante: boolean;
  habitation: string | null;
  motif_refus: string;
  peut_valider: boolean;
}

/** Une fiche résumée, dans un rapprochement. */
export interface FicheRapprochee {
  id: string;
  adresse: string;
  statut_evaluation: StatutEvaluationHabitation;
  nature_degats: string;
  type_bien_nom: string | null;
  latitude: number | null;
  longitude: number | null;
  date_derniere_evaluation: string | null;
  photos: number;
}

/** Deux fiches qui désignent peut-être le même bien : proposé, jamais fusionné d'office. */
export interface RapprochementBien {
  id: string;
  statut: 'PROPOSE' | 'CONFIRME' | 'REFUSE' | 'SEPARE';
  distance_m: number | null;
  manuel: boolean;
  propose_le: string;
  decide_le: string | null;
  bien: FicheRapprochee;
  autre: FicheRapprochee;
}
