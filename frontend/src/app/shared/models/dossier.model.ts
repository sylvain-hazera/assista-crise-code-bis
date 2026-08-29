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

  titre: string;
  description: string;

  statut: string;

  date_creation: string;
  date_affectation?: string;
  date_resolution?: string;
  date_cloture?: string;

  unread_count?: number;
  has_updates?: boolean;
}
