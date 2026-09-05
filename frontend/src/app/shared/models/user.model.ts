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
  postal_code: string | null;
  photo: string | null;                 // URL relative (ex: /media/photos/xxx.jpg)
  type: UserRole;
  institution_nom?: string | null;      // Nom de l'institution active de l'utilisateur (lecture seule)
  institution_id?: string | null;       // UUID de l'institution active de l'utilisateur (lecture seule)
  needs_institution_setup?: boolean;    // Compte Autorité locale activé mais pas encore rattaché à une institution
  ma_zone?: {
    niveau: string;
    nom: string | null;
    risques: { num_risque: string; libelle_risque_long: string }[];  // Aléas du territoire (API Géorisques) — voir Vue Ma Collectivité
    risques_date_maj: string | null;  // Date de dernière résolution des risques — voir bouton "Actualiser"
  } | null;  // Secteur effectif de l'institution (User.institution) — voir Vue Ma Collectivité
  demo_role: UserRole | null;           // Rôle en zone de démonstration — null = pas d'accès démo
  enabled: boolean;
  is_active?: boolean;                  // false = compte désactivé (politique de désactivation), lecture seule
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
  type?: UserRole;
  demo_role?: UserRole | null;
}

export type Environment = 'PROD' | 'DEMO';