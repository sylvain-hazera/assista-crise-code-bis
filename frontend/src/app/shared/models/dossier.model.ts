export interface Dossier {
  id: string;

  numero: string;

  crise: string;
  crise_nom: string;

  competence: string;
  competence_nom: string;
  /** Classement « quoi + pour qui » de la demande (27/11/2026). */
  demande_type?: string | null;
  demande_type_nom?: string | null;
  demande_beneficiaire?: string | null;
  demande_categorie_animaux?: string | null;
  /** Nature du Besoin capturé à la création (COMPETENCE/MATERIEL/MIXTE) -- classe le dossier
   * ressource/matériel sur la page Cellule de crise, voir Dossier.besoin. */
  besoin_nature?: 'COMPETENCE' | 'MATERIEL' | 'MIXTE' | null;

  equipe?: string;
  equipe_nom?: string;

  mission?: string | null;
  /** Dossier générique : ouvert pour une mission d'intérêt général, à la demande d'une
   * institution et non d'une personne. Il n'a donc ni demande ni signalement d'origine. */
  generique?: boolean;
  institution_demandeuse?: string | null;
  institution_demandeuse_nom?: string | null;
  mission_titre?: string | null;

  demande?: string | null;
  information?: string | null;
  information_titre?: string | null;

  latitude?: number | null;
  longitude?: number | null;
  has_photo?: boolean;
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
