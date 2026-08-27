export interface DelegationCompetence {
  id: string;
  institution_source: string;
  institution_source_nom?: string | null;
  institution_cible: string;
  institution_cible_nom?: string | null;
  competence: string;
  competence_libelle?: string | null;
  crise: string | null;
  active: boolean;
  date_debut: string;
  date_fin?: string | null;
  commentaire?: string | null;
  departements: string[];
  communes: string[];
  zone_precise?: any | null;
}

export interface DelegationCompetencePayload {
  institution_source: string;
  institution_cible: string;
  competence: string;
  crise: string;
  commentaire?: string;
  departements?: string[];
  communes?: string[];
  zone_precise?: string | null;
}
