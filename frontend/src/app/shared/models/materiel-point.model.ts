export type StatutMateriel = 'EN_TRANSIT' | 'SUR_PLACE' | 'RETIRE';
export type NiveauStock = 'NUL' | 'FAIBLE' | 'OK' | 'EN_TROP';

export interface MaterielPoint {
  id: string | null;
  point: string;
  item: string;
  item_nom: string;
  niveau_stock: NiveauStock;
  niveau_stock_libelle?: string;
  nom?: string;
  quantite: number;
  // Somme des apports actifs (voir ContributionMateriel) — null si aucun apport n'a jamais été
  // tracé sur cette ligne (distinct de 0, qui signifierait "tout retiré").
  quantite_totale?: number | null;
  unite: string;
  statut: StatutMateriel | null;
  statut_libelle?: string | null;
  responsable: string | null;
  responsable_nom?: string | null;
  commentaire?: string | null;
  date_maj: string | null;
}

export interface MaterielPointPayload {
  point: string;
  item: string;
  niveau_stock?: NiveauStock;
  nom?: string;
  quantite?: number;
  unite?: string;
  statut?: StatutMateriel;
  commentaire?: string;
}

export interface StocksComparaison {
  points: { id: string; nom: string; type_libelle: string | null }[];
  items: {
    item: string;
    item_nom: string;
    niveaux: Record<string, { niveau_stock: NiveauStock; niveau_stock_libelle: string }>;
  }[];
}
