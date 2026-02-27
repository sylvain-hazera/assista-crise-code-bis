export enum RoleUtilisateur {
  ADMIN       = 'ADMIN',
  AUT_LOCALE  = 'AUT_LOCALE',
  SECOURS     = 'SECOURS',
  UTIL_SIMPLE = 'UTIL_SIMPLE'
}

// Retourné par l'API en lecture
export interface Utilisateur {
  id: string;                           // UUID (read-only, auto-généré)
  username: string;                     // AbstractUser
  email: string;
  first_name: string;                   // AbstractUser
  last_name: string;                    // AbstractUser
  telephone_utilisateur: string | null;
  photo: string | null;                 // URL relative (ex: /media/photos/xxx.jpg)
  type: RoleUtilisateur;
  enable: boolean;
  crise_touchee: string | null;         // UUID de la Crise (FK)
  // M2M — listes d'UUID, non éditables directement
  validateur?: string[];
  consulte_demande?: string[];
  consulte_information?: string[];
  consulte_offre?: string[];
}

// Envoyé au backend pour la création / mise à jour du profil
export interface UtilisateurPayload {
  username?: string;
  email?: string;
  first_name?: string;
  last_name?: string;
  telephone_utilisateur?: string;
  photo?: File;                         // Envoyé via FormData
}