export type MeshCoreConnexionType = 'TCP' | 'SERIE' | 'BLE';

export interface CompagnonMeshCore {
  id: string;
  nom: string;
  connexion_type: MeshCoreConnexionType;

  /** Position du companion physique (poste de commandement, véhicule...), saisie manuelle —
   * affichée sur la carte au même titre qu'un RelaisMeshCore, voir map.component.ts. */
  latitude?: number | null;
  longitude?: number | null;

  tcp_host?: string | null;
  tcp_port?: number | null;
  serie_device?: string | null;
  ble_adresse?: string | null;

  institution?: string | null;
  institution_nom?: string | null;

  principal: boolean;
  actif: boolean;

  /** Convention communautaire de canal régional (ex: "fr-naq") — PAS une notion protocolaire
   * MeshCore (aucune ACL ni découpage régional n'existe côté firmware, vérifié le 2026-09-18),
   * simple étiquette texte libre saisie par un administrateur. Sert à suggérer le meilleur
   * companion pour joindre un contact sans chemin direct connu (voir CompagnonMeshCoreService.
   * meilleurPourContact). */
  region_tag?: string;

  /** Renseignés uniquement par le service-pont (meshcore-bridge/), jamais éditables ici. */
  pubkey_hex?: string | null;
  derniere_connexion?: string | null;
  dernier_etat?: 'CONNECTE' | 'DECONNECTE' | 'ERREUR' | null;
  derniere_erreur?: string | null;

  date_creation?: string;
}
