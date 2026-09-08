export interface Competence {
  id: string;
  nom: string;
  description?: string;
  active: boolean;
  /** Compétence générique qui regroupe celle-ci (ex: "PSC1" -> parent "Secourisme") — jamais
   * plus d'un niveau, voir backend/core/models.py. Null = compétence de premier niveau. */
  parent: string | null;
}

