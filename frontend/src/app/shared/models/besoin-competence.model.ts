export interface BesoinCompetence {
  id: string;

  besoin: string;
  besoin_nom: string;

  competence: string;
  competence_nom: string;

  /** Précision facultative (27/11/2026) : vide = vaut pour tous. */
  beneficiaire?: string | null;
  categorie_animaux?: string | null;
}
