export interface Besoin {
  id: string;

  nom: string;

  description?: string;

  actif: boolean;

  /** Thème parent (sous-thème), ex: "traduction anglais" sous "Traducteur" — voir
   * Competence.parent, même patron. */
  parent: string | null;
}
