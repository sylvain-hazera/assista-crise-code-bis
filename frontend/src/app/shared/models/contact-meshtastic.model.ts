export interface ContactMeshtastic {
  id: string;
  compagnon: string;
  compagnon_nom?: string;
  node_num: number;
  long_name?: string;
  short_name?: string;
  hardware_model?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  dernier_advert?: string | null;
  date_synchronisation?: string;
  deja_associe: boolean;
}
