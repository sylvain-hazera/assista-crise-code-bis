export type TypeImplication = 'IMPLIQUE' | 'ACTEUR';

export interface ImplicationInstitution {
  id: string;
  crise: string;
  institution: string;
  institution_nom?: string | null;
  crise_nom?: string | null;
  utilisateur: string | null;
  type_implication: TypeImplication;
  commentaire?: string | null;
  actif: boolean;
  date_creation: string;
}

export interface ImplicationInstitutionPayload {
  crise: string;
  institution: string;
  type_implication: TypeImplication;
  commentaire?: string;
}
