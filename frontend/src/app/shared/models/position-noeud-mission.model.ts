/** Position actuelle d'un nœud MeshCore personnel — uniquement pour les nœuds d'utilisateurs
 * membres d'une équipe dont la mission courante est EN_COURS (voir
 * NoeudMeshUtilisateurViewSet.positions_en_mission côté backend). Jamais renvoyé en dehors
 * d'une mission active. */
export interface PositionNoeudMission {
  noeud_id: string;
  utilisateur_id: string;
  utilisateur_nom: string;
  nom_noeud: string;
  pubkey_hex: string;
  latitude: number;
  longitude: number;
  dernier_advert: string | null;
  equipe_id: string | null;
  equipe_nom: string | null;
  mission_id: string | null;
  mission_titre: string | null;
}
