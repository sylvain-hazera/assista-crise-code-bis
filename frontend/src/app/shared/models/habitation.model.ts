export type StatutEvaluationHabitation = 'NON_EVALUEE' | 'PAS_DE_DEGATS' | 'DEGATS_FAIBLES' | 'DEGATS_FORTS';
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
  evalue_par: string | null;
  date_derniere_evaluation: string | null;
  date_creation: string;
  modifie_le: string;
  nb_rattachements_en_attente: number;
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
};
