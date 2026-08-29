import { StatutMateriel } from './materiel-point.model';

export interface ContributionMateriel {
  id: string;
  materiel_point: string;
  offre: string | null;
  fournisseur_nom: string;
  quantite: number;
  unite: string;
  statut: StatutMateriel;
  statut_libelle?: string;
  responsable: string | null;
  responsable_nom?: string | null;
  commentaire?: string | null;
  date_reception: string;
}

export interface ContributionMaterielPayload {
  materiel_point: string;
  fournisseur_nom: string;
  quantite: number;
  unite?: string;
  statut?: StatutMateriel;
  commentaire?: string;
}
