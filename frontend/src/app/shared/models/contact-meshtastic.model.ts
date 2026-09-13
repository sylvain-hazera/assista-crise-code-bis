export interface ContactMeshtastic {
  id: string;
  compagnon: string;
  compagnon_nom?: string;
  node_num: number;
  long_name?: string;
  short_name?: string;
  hardware_model?: string | null;
  /** Clé publique X25519 annoncée par ce nœud (NodeInfo) — vide s'il n'a jamais annoncé de clé
   * (PKI non activé côté firmware) ou pas encore vu. Permet un DM chiffré par clé publique
   * plutôt que par PSK de canal, voir meshtastic-bridge/crypto.py. */
  public_key_hex?: string;
  latitude?: number | null;
  longitude?: number | null;
  dernier_advert?: string | null;
  date_synchronisation?: string;
  deja_associe: boolean;
}
