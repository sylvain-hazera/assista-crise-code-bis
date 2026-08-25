export interface DossierDocument {
  id: string;
  nom_fichier: string;
  auteur: string;
  auteur_nom: string;
  date_upload: string;
  commentaire: string | null;
  sha256: string | null;
  metadata_privees?: Record<string, string>;
  demande?: string | null;
  offre?: string | null;
  dossier?: string | null;
}
