export type TypeContactMeshCore = 'INCONNU' | 'COMPANION' | 'REPEATER' | 'ROOM' | 'SENSOR';

export interface ContactMeshCore {
  id: string;
  compagnon: string;
  compagnon_nom?: string;
  pubkey_hex: string;
  nom: string;
  type_contact: TypeContactMeshCore;
  latitude?: number | null;
  longitude?: number | null;
  dernier_advert?: string | null;
  date_synchronisation?: string;
  deja_associe: boolean;
}
