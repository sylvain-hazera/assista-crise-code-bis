import { AffectationPointBenevole } from './affectation-point-benevole.model';

export interface PointType {
  id: string;
  code: string;
  libelle: string;
  description?: string | null;
  actif: boolean;
}

export interface PointOperationnel {
  id: string;
  nom: string;
  type: string;
  type_libelle?: string | null;
  type_code?: string | null;
  crise: string | null;
  crise_nom?: string | null;
  responsable: string | null;
  responsable_nom?: string | null;
  adresse?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  obligatoire: boolean;
  actif: boolean;
  commentaire?: string | null;
  description?: string | null;
  capacite_accueil?: number | null;
  date_ouverture?: string | null;
  date_fermeture?: string | null;
  competences_requises?: string[];
  competences_requises_libelles?: string[];
  equipe?: string | null;
  equipe_nom?: string | null;
  personnes_presentes?: number;
}

/** Version publique, à champs restreints, renvoyée par GET /points-operationnels/centres_accueil/
 * — voir PointOperationnelPublicSerializer côté backend. */
export interface CentreAccueilPublic {
  id: string;
  nom: string;
  adresse: string | null;
  latitude: number | null;
  longitude: number | null;
  capacite_accueil: number | null;
  personnes_presentes: number;
  crise: string | null;
}

export interface PointEquipeMembre {
  id: string;
  nom: string;
  email: string;
  temps_total_heures?: number;
}

export interface PointEquipeResponse {
  membres: PointEquipeMembre[];
  disponibilites: {
    id: string;
    point: string;
    membre: string;
    membre_nom: string;
    date: string;
    creneau: 'MATIN' | 'MIDI' | 'SOIR' | 'NUIT';
    affectation_statut?: string | null;
  }[];
  affectations: AffectationPointBenevole[];
}

export interface PointOperationnelPayload {
  nom: string;
  type: string;
  crise: string;
  adresse?: string;
  commentaire?: string;
  institution?: string;
  description?: string;
  capacite_accueil?: number | null;
  date_ouverture?: string | null;
  date_fermeture?: string | null;
  location?: string;
  competences_requises?: string[];
  equipe?: string | null;
}
