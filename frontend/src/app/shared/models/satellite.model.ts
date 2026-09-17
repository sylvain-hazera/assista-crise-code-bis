export type ProfilSatellite = 'GW' | 'FULL';
export type StatutEnrolementSatellite = 'EN_ATTENTE' | 'APPROUVE' | 'REVOQUE';
export type EtatSatellite = 'ACTIF' | 'INACTIF' | 'PERDU' | null;

export interface Satellite {
  id: string;
  institution: string;
  institution_nom: string;
  nom: string;
  profil: ProfilSatellite;
  profil_libelle: string;
  statut_enrolement: StatutEnrolementSatellite;
  statut_enrolement_libelle: string;
  compte_service: string | null;
  dernier_contact: string | null;
  version_logicielle: string;
  date_creation: string;
  etat: EtatSatellite;
}

export interface JetonEnrolementSatellite {
  id: string;
  institution: string;
  jeton: string;
  expiration: string;
  utilise: boolean;
  date_creation: string;
}

export interface IdentifiantsCompteServiceSatellite {
  email: string;
  password: string;
}
