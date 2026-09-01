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
  latitude?: number | null;   // GPS EXIF décimal, null si absent ou non visible pour ce viewer
  longitude?: number | null;
  azimuth?: number | null;    // 0-360°, direction de la prise de vue
}
