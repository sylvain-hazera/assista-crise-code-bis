export interface RelaisMeshCore {
  id: string;
  nom: string;
  latitude?: number | null;
  longitude?: number | null;
  pubkey_hex?: string | null;
  institution?: string | null;
  institution_nom?: string | null;
  actif: boolean;
  commentaire?: string | null;
  date_creation?: string;
}
