export type TypeMateriel = 'CUVE' | 'POMPE' | 'ETUVE' | 'CHAMBRE_FROIDE' | 'REMORQUE' | 'AUTRE';
export type StatutMateriel = 'EN_TRANSIT' | 'SUR_PLACE' | 'RETIRE';

export interface MaterielPoint {
  id: string;
  point: string;
  type: TypeMateriel;
  type_libelle?: string;
  nom: string;
  quantite: number;
  unite: string;
  statut: StatutMateriel;
  statut_libelle?: string;
  responsable: string | null;
  responsable_nom?: string | null;
  commentaire?: string | null;
  date_maj: string;
}

export interface MaterielPointPayload {
  point: string;
  type: TypeMateriel;
  nom: string;
  quantite?: number;
  unite?: string;
  statut?: StatutMateriel;
  commentaire?: string;
}
