export interface AppNotification {
  id: string;
  utilisateur: string;
  dossier: string | null;
  dossier_numero: string | null;
  titre: string;
  message: string;
  lu: boolean;
  date_creation: string;
}
