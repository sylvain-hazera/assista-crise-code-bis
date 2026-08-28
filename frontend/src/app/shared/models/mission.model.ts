export interface Mission {
  id?: string;
  titre: string;
  description?: string | null;
  crise: string;
  crise_nom?: string;
  equipe_ids: string[];
  equipes_noms?: string[];
  statut: 'EN_PREPARATION' | 'EN_COURS' | 'TERMINEE';
  date_creation?: string;
  date_cloture?: string | null;
}
