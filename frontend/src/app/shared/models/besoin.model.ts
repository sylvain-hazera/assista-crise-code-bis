export type BesoinNature = 'COMPETENCE' | 'MATERIEL' | 'MIXTE';

export interface Besoin {
  id: string;

  nom: string;

  description?: string;

  actif: boolean;

  /** Thème parent (sous-thème), ex: "traduction anglais" sous "Traducteur" — voir
   * Competence.parent, même patron. */
  parent: string | null;

  /** Ce que le besoin mobilise pour être satisfait — détermine quel(s) type(s) de
   * correspondance (besoin-compétence / besoin-matériel) proposer. Peut rester vide pour
   * un besoin pas encore qualifié, ou une catégorie purement groupante. */
  nature: BesoinNature | null;
}
