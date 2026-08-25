export interface PointType {
  id: string;
  code: string;
  libelle: string;
  description?: string | null;
  actif: boolean;
}

export interface PointOperationnel {
  id: string;
  nom: string;
  type: string;
  type_libelle?: string | null;
  crise: string | null;
  responsable: string | null;
  responsable_nom?: string | null;
  adresse?: string | null;
  obligatoire: boolean;
  actif: boolean;
  commentaire?: string | null;
}

export interface PointOperationnelPayload {
  nom: string;
  type: string;
  crise: string;
  adresse?: string;
  commentaire?: string;
  institution?: string;
}
