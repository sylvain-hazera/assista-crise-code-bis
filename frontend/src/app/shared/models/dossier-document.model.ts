export interface DossierDocument {
  id: string;
  fichier: string;
  auteur: string;
  auteur_nom: string;
  date_upload: string;
  commentaire: string | null;
  sha256: string | null;
  demande?: string | null;
  offre?: string | null;
  dossier?: string | null;
}
