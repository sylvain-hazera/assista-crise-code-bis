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
  commune_code?: string | null;
  commune_nom?: string | null;
  commune_code_postal?: string | null;
  actif: boolean;
  date_creation?: string;
}

export interface ContactInstitution {
  id?: string;
  institution: string;   // UUID de l'Institution
  utilisateur: string;   // UUID du User
  utilisateur_nom?: string | null;
  utilisateur_email?: string | null;
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

export interface AffectationRoleOperationnel {
  id?: string;
  utilisateur: string;        // UUID du User
  institution: string;        // UUID de l'Institution
  competence: string | null;  // UUID de la Competence — peut être vide juste après activation
  role: string;                // UUID du RoleOperationnel
  actif: boolean;
  date_debut?: string;
  date_fin?: string | null;
  commentaire?: string | null;
  zone?: string | null;               // UUID de la Zone (catalogue de l'institution)
  zone_precise?: string | null;       // WKT, dessin optionnel propre à cette affectation
  responsabilite?: string | null;     // Intitulé libre du périmètre de responsabilité
}
