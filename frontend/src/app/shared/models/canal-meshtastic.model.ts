import { DirectionMessageMesh, StatutMessageMesh } from './canal-meshcore.model';

export interface CanalMeshtastic {
  id: string;
  /** DOIT correspondre exactement au nom du canal configuré sur les appareils cibles — c'est
   * lui qui compose le topic MQTT (voir meshtastic-bridge/bridge.py), pas une étiquette libre. */
  nom: string;
  institution?: string | null;
  institution_nom?: string | null;
  crise?: string | null;
  crise_nom?: string | null;
  equipe?: string | null;
  equipe_nom?: string | null;
  /** write_only côté API — jamais renvoyée par le serveur. Hex : vide (pas de chiffrement),
   * 1 octet (index de PSK "par défaut" du protocole, 01-0A), ou 32/64 caractères hex (clé
   * complète 16/32 octets). */
  psk_hex?: string;
  actif: boolean;
  date_creation?: string;
}

export interface MessageCanalMeshtastic {
  id: string;
  canal: string;
  canal_nom?: string;
  direction: DirectionMessageMesh;
  expediteur?: string | null;
  expediteur_nom?: string | null;
  contact_node_num?: number | null;
  contenu: string;
  statut: StatutMessageMesh;
  erreur?: string | null;
  date_creation: string;
}

export interface MessageMeshtasticLog {
  id: string;
  compagnon: string;
  compagnon_nom?: string;
  canal?: string | null;
  direction: DirectionMessageMesh;
  contact_node_num: number;
  expediteur?: string | null;
  expediteur_nom?: string | null;
  equipe?: string | null;
  equipe_nom?: string | null;
  contenu: string;
  statut: StatutMessageMesh;
  erreur?: string | null;
  date_creation: string;
  date_envoi?: string | null;
}
