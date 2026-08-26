export interface AffectationCompetence {
  id: string;

  crise: string;
  crise_nom: string;

  competence: string;
  competence_nom: string;

  equipe: string;
  equipe_nom: string;

  active: boolean;

  date_debut: string;
  date_fin?: string;

  commentaire?: string;
}
