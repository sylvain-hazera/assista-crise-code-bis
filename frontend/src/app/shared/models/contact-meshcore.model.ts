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
  /** Nombre de sauts du chemin connu par CE companion vers ce contact — null si aucun chemin
   * confirmé (sentinel firmware 255, PAS "255 sauts"). Voir ContactMeshCore.nombre_sauts. */
  nombre_sauts?: number | null;
  /** Étiquette régionale posée à la main, voir CompagnonMeshCore.region_tag. */
  region_tag?: string;
  date_synchronisation?: string;
  deja_associe: boolean;
}
