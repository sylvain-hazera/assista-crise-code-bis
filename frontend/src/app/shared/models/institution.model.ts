export interface InstitutionType {
  id?: string;
  code: string;
  libelle: string;
  description?: string | null;
  actif: boolean;
}

export interface Institution {
  id?: string;
  nom: string;
  type: string | null;           // UUID de l'InstitutionType
  type_libelle?: string | null;  // résolu côté backend, lecture seule
  description?: string | null;
  telephone?: string | null;
  email?: string | null;
  adresse?: string | null;
  actif: boolean;
  date_creation?: string;
}

export interface ContactInstitution {
  id?: string;
  institution: string;   // UUID de l'Institution
  utilisateur: string;   // UUID du User
  fonction?: string;
  contact_principal: boolean;
  actif: boolean;
  date_creation?: string;
}

export interface InstitutionDomaine {
  id?: number;
  institution: string;   // UUID de l'Institution
  domaine: string;
  valide: boolean;
}

export interface RoleOperationnel {
  id?: string;
  code: string;
  libelle: string;
  description?: string | null;
  actif: boolean;
}
