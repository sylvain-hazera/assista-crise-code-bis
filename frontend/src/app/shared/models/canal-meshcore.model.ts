export type DirectionMessageMesh = 'ENTRANT' | 'SORTANT';
export type StatutMessageMesh = 'EN_ATTENTE' | 'ENVOYE' | 'RECU' | 'ECHEC';

export interface CanalMeshCore {
  id: string;
  nom: string;
  institution?: string | null;
  institution_nom?: string | null;
  crise?: string | null;
  crise_nom?: string | null;
  /** write_only côté API — jamais renvoyée par le serveur, uniquement acceptée à la création. */
  cle_partagee_hex?: string;
  actif: boolean;
  date_creation?: string;
}

export interface MessageCanalMeshCore {
  id: string;
  canal: string;
  canal_nom?: string;
  direction: DirectionMessageMesh;
  expediteur?: string | null;
  expediteur_nom?: string | null;
  contact_pubkey_hex?: string | null;
  contenu: string;
  statut: StatutMessageMesh;
  erreur?: string | null;
  date_creation: string;
}

export interface MessageMeshLog {
  id: string;
  compagnon: string;
  compagnon_nom?: string;
  direction: DirectionMessageMesh;
  contact_pubkey_hex: string;
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
