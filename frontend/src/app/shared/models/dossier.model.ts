export interface Dossier {
  id: string;

  numero: string;

  crise: string;
  crise_nom: string;

  competence: string;
  competence_nom: string;

  equipe?: string;
  equipe_nom?: string;

  mission?: string | null;
  mission_titre?: string | null;

  demande?: string | null;
  information?: string | null;
  information_titre?: string | null;

  latitude?: number | null;
  longitude?: number | null;
  commune?: string | null;

  contact_nom?: string | null;
  contact_telephone?: string | null;
  contact_email?: string | null;
  description_origine?: string | null;

  titre: string;
  description: string;

  statut: string;
  priorite: 'URGENTE' | 'NORMALE' | 'BASSE';
  priorite_libelle?: string;
  ordre: number;

  date_creation: string;
  date_affectation?: string;
  date_resolution?: string;
  date_cloture?: string;

  unread_count?: number;
  has_updates?: boolean;

  important?: boolean;                  // lecture seule, voir DossierService.marquerImportant
  date_signalement_important?: string | null;

  regulateurs?: { id: string; nom: string; email: string; telephone: string | null }[];
}
