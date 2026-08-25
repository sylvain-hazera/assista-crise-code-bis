export enum UserRole {
  ADMIN       = 'ADMIN',
  LOCAL_AUTH  = 'AUT_LOCALE',
  RESCUE      = 'SECOURS',
  SIMPLE_USER = 'UTIL_SIMPLE',
  REGULATEUR  = 'REGULATEUR'
}

// Retourné par l'API en lecture
export interface User {
  id: string;                           // UUID (read-only, auto-généré)
  username: string;                     // AbstractUser
  email: string;
  first_name: string;                   // AbstractUser
  last_name: string;                    // AbstractUser
  phone_number: string | null;
  photo: string | null;                 // URL relative (ex: /media/photos/xxx.jpg)
  type: UserRole;
  enabled: boolean;
  affected_crisis: string | null;       // UUID de la Crisis (FK)
  // M2M — listes d'UUID, non éditables directement
  validator?: string[];
  viewed_requests?: string[];
  viewed_informations?: string[];
  viewed_offers?: string[];
}

// Envoyé au backend pour la création / mise à jour du profil
export interface UserPayload {
  username?: string;
  email?: string;
  first_name?: string;
  last_name?: string;
  phone_number?: string;
  photo?: File;                         // Envoyé via FormData
}