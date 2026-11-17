import { NatureDegatsHabitation, StatutEvaluationHabitation } from './habitation.model';

export type TypeBienSinistre = 'VEHICULE' | 'DEUX_ROUES' | 'BATEAU' | 'CARAVANE' | 'ENGIN' | 'BATIMENT_AGRICOLE'
  | 'COMMERCE' | 'MOBILIER_URBAIN' | 'AUTRE';

export const LABELS_TYPE_BIEN: Record<TypeBienSinistre, string> = {
  VEHICULE: 'Véhicule (voiture, utilitaire, camion)',
  DEUX_ROUES: 'Deux-roues',
  BATEAU: 'Bateau',
  CARAVANE: 'Caravane, camping-car, mobil-home',
  ENGIN: 'Engin, matériel agricole ou de chantier',
  BATIMENT_AGRICOLE: 'Bâtiment agricole, hangar, annexe',
  COMMERCE: 'Commerce, local professionnel',
  MOBILIER_URBAIN: 'Voirie, mobilier urbain, réseau',
  AUTRE: 'Autre bien',
};

/** Un bien sinistré qui n'est pas une habitation : voiture brûlée, bateau, hangar… */
export interface BienSinistre {
  id: string;
  crise: string;
  crise_nom?: string | null;
  type_bien: TypeBienSinistre;
  designation: string;
  /** Immatriculation, numéro de série… (chiffrée côté serveur). */
  identification: string;
  description: string;
  adresse: string;
  commune_code?: string | null;
  latitude: number | null;
  longitude: number | null;
  nature_degats: NatureDegatsHabitation;
  statut_evaluation: StatutEvaluationHabitation;
  proprietaire_nom: string;
  proprietaire_email: string;
  proprietaire_telephone: string;
  nb_photos?: number;
  cree_par_nom?: string | null;
  date_creation?: string;
  modifie_le?: string;
  /** Dernier envoi du rapport au propriétaire. */
  rapport_envoye_le?: string | null;
}
