import type { Polygon } from "geojson";

/** Message du salon Matrix d'une équipe, relayé par le backend avec le jeton du bot (core/matrix.py). */
export interface MatrixMessage {
  /** Id Matrix pour un message Matrix ; UUID du message pour les sources mesh. */
  event_id:        string;
  texte:           string;
  horodatage:      number;
  expediteur_id:   string | null;
  expediteur_nom:  string;
  moi:             boolean;
  /** Ouvert à tous les membres. */
  urgent:          boolean;
  /** Cadres ayant posé « Vu » ; toujours vide pour les sources mesh. */
  vu_par:          string[];
  /** Canal d'origine ; posé par messagerie_unifiee (badge par message). */
  source?:         'matrix' | 'meshcore' | 'meshtastic';
}

export interface TeamMission {
  id:      string;
  kind:    'Crisis' | 'Offer' | 'Request';
  titre:   string;
  statut?: string;
  date?:   string;
  // Offer uniquement : progression de la ressource (EngagementRessource), absent si non affectée.
  engagementStatut?: string | null;
  engagementStatutLibelle?: string | null;
}

export interface TeamMemberInfo {
  id: string;
  nom: string;
}

export interface Team {
  id?:                  string;
  name:                 string;
  description:          string;
  color:                string;
  leader:               string | null;      // UUID du chef d'équipe (terrain)
  leader_nom?:          string | null;
  regulateur?:          string | null;      // UUID du régulateur (pilotage depuis le centre de crise)
  regulateur_nom?:      string | null;
  mission_active?:      string | null;      // UUID de la mission courante de l'équipe (voir Mission)
  mission_active_titre?: string | null;
  mission_active_crise_id?: string | null;
  mission_active_crise_nom?: string | null;
  mission_active_statut?: 'EN_PREPARATION' | 'EN_COURS' | 'TERMINEE' | null;
  institution?:         string | null;      // UUID de l'institution responsable (auto-complétée à la création si absente)
  institution_nom?:     string | null;
  institution_delegataire?:     string | null; // UUID de l'institution délégataire courante (lecture seule, voir TeamService.definirDelegation/retirerDelegation)
  institution_delegataire_nom?: string | null;
  equipe_parente?:              string | null; // UUID de l'équipe de tête à laquelle celle-ci est rattachée comme ressource (lecture seule, voir TeamService.rattacherEquipe/detacherEquipe)
  equipe_parente_nom?:          string | null;
  est_equipe_rcsc?:             boolean;       // Marque cette équipe comme LA RCSC de son institution (lecture seule, voir TeamService.designerRcsc) -- conditionne l'accès au registre des personnes vulnérables

  sous_equipes_info?:           { id: string; nom: string }[];
  canal_meshcore_id?:           string | null;
  canal_meshcore_nom?:          string | null;
  canal_meshcore_provisionne?:  boolean;
  canal_meshtastic_id?:         string | null;
  canal_meshtastic_nom?:        string | null;
  salon_matrix_id?:             string | null;
  salon_matrix_room_id?:        string | null;
  member_ids:           string[];
  members_info?:        TeamMemberInfo[];
  vehicules_count?:     number;            // Offres de type Transport affectées à l'équipe (lecture seule)
  peut_gerer?:          boolean;           // L'utilisateur courant peut y affecter des ressources (son institution ou déléguée, lecture seule)
  assigned_crisis_ids:  string[];
  assigned_offer_ids:   string[];
  assigned_request_ids: string[];
  assigned_information_ids: string[];
  competence_ids:       string[];
  theme_ids?:           string[];             // UUID des Besoin déclarés comme thèmes de l'équipe (ex: "Hébergement")
  themes_libelles?:     string[];
  departements:         string[];           // codes département déclarés (ex: ['38', '73'])
  communes:             string[];           // codes commune INSEE déclarés, plus précis
  zone_precise?:        string | null;      // WKT en écriture (le plus précis des 3 niveaux)
  zone_precise_geojson?: Polygon | null;    // GeoJSON natif en lecture, prêt pour ZoneMapComponent
  missions:             TeamMission[];      // calculé localement, non envoyé à l'API
  created_at?:          string;
  actif?:               boolean;           // false = désactivée (politique de désactivation)
  commune_centre?:      { latitude: number | null; longitude: number | null } | null;
  /** Début de l'engagement continu (null = au repos), géré manuellement. */
  engagement_debut?:    string | null;
}

/** Nom préfixé par l'institution responsable, pour les listes mêlant plusieurs institutions. */
export function teamDisplayName(team: Pick<Team, 'name' | 'institution_nom'>): string {
  return team.institution_nom ? `${team.institution_nom} - ${team.name}` : team.name;
}