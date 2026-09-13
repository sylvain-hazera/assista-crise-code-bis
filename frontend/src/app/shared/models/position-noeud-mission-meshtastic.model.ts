/** Position actuelle d'un nœud Meshtastic personnel — uniquement pour les nœuds d'utilisateurs
 * membres d'une équipe dont la mission courante est EN_COURS (voir
 * NoeudUtilisateurMeshtasticViewSet.positions_en_mission côté backend), même règle que pour
 * MeshCore. Jamais renvoyé en dehors d'une mission active. */
export interface PositionNoeudMissionMeshtastic {
  noeud_id: string;
  utilisateur_id: string;
  utilisateur_nom: string;
  nom_noeud: string;
  node_num: number;
  latitude: number;
  longitude: number;
  dernier_advert: string | null;
  equipe_id: string | null;
  equipe_nom: string | null;
  mission_id: string | null;
  mission_titre: string | null;
}
