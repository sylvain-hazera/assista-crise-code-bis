export interface DernierePosition {
  id: string;
  utilisateur: string;
  utilisateur_nom: string;
  latitude: number | null;
  longitude: number | null;
  horodatage: string;
  team_ids: string[];
  team_noms: string[];
}
