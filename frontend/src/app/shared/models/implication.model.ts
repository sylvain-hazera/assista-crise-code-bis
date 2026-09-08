export type TypeImplication = 'IMPLIQUE' | 'ACTEUR';
export type StatutImplication = 'EN_ATTENTE' | 'VALIDEE' | 'REFUSEE';

export interface ImplicationInstitution {
  id: string;
  crise: string;
  institution: string;
  institution_nom?: string | null;
  crise_nom?: string | null;
  utilisateur: string | null;
  type_implication: TypeImplication;
  statut: StatutImplication;
  peut_valider?: boolean;
  commentaire?: string | null;
  actif: boolean;
  date_creation: string;
  themes?: string[];
  themes_libelles?: string[];
  responsable?: string | null;
  responsable_nom?: string | null;
}

export interface ImplicationInstitutionPayload {
  crise: string;
  institution: string;
  type_implication: TypeImplication;
  commentaire?: string;
  themes?: string[];
  responsable?: string;
  responsable_email?: string;
}
