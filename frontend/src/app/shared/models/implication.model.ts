export type TypeImplication = 'IMPLIQUE' | 'ACTEUR';
export type StatutImplication = 'EN_ATTENTE' | 'VALIDEE' | 'REFUSEE';

export interface ImplicationInstitution {
  id: string;
  crise: string;
  institution: string;
  institution_nom?: string | null;
  /** Communes de la crise sur lesquelles l'institution est acceptée. Vide = toute la zone de
   * la crise (voir ImplicationInstitution.communes cote backend). */
  communes?: string[];
  /** Communes dont la collectivité a refusé l'intervention. Une commune de la crise absente
   * des deux listes attend encore la réponse de sa mairie. */
  communes_refusees?: string[];
  /** Collectivité venue en renfort hors de son territoire : accord de chaque commune requis. */
  renfort?: boolean;
  /** Où en est l'accord commune par commune ; null si la déclaration n'en dépend pas. */
  accord?: AccordCommunes | null;
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
  /** Restrictions facultatives de l'écoute (27/11/2026) : vide = tous. */
  beneficiaires_ecoutes?: string[];
  categories_animaux_ecoutees?: string[];
  responsable?: string | null;
  responsable_nom?: string | null;
}

export interface AccordCommunes {
  toute_la_crise: boolean;
  acceptees: number;
  refusees: number;
  en_attente: number;
  /** Les communes de l'appelant qui attendent SA réponse. */
  a_moi_en_attente: string[];
  /** Celles où il a déjà dit oui, et où il peut encore retirer son accord. */
  a_moi_acceptees: string[];
}

export interface ImplicationInstitutionPayload {
  crise: string;
  institution: string;
  type_implication: TypeImplication;
  commentaire?: string;
  themes?: string[];
  beneficiaires_ecoutes?: string[];
  categories_animaux_ecoutees?: string[];
  responsable?: string;
  responsable_email?: string;
  renfort?: boolean;
  /** La commune n'entre dans la zone que par les zones qu'elle dessinera. */
  territoire_partiel?: boolean;
}
