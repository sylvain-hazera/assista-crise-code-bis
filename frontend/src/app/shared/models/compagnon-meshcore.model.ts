export type MeshCoreConnexionType = 'TCP' | 'SERIE' | 'BLE';

export interface CompagnonMeshCore {
  id: string;
  nom: string;
  connexion_type: MeshCoreConnexionType;

  tcp_host?: string | null;
  tcp_port?: number | null;
  serie_device?: string | null;
  ble_adresse?: string | null;

  institution?: string | null;
  institution_nom?: string | null;

  principal: boolean;
  actif: boolean;

  /** Renseignés uniquement par le service-pont (meshcore-bridge/), jamais éditables ici. */
  pubkey_hex?: string | null;
  derniere_connexion?: string | null;
  dernier_etat?: 'CONNECTE' | 'DECONNECTE' | 'ERREUR' | null;
  derniere_erreur?: string | null;

  date_creation?: string;
}
