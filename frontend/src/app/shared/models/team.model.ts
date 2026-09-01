import type { Polygon } from "geojson";

export interface TeamMission {
  id:      string;
  kind:    'Crisis' | 'Offer' | 'Request';
  titre:   string;
  statut?: string;
  date?:   string;
  // Offer uniquement — progression réelle de la ressource (voir EngagementRessource) :
  // en attente / confirmé / en transit / arrivé / décliné, absent si jamais affectée.
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
  institution?:         string | null;      // UUID de l'institution responsable (auto-complétée à la création si absente)
  institution_nom?:     string | null;
  institution_delegataire?:     string | null; // UUID de l'institution délégataire courante (lecture seule, voir TeamService.definirDelegation/retirerDelegation)
  institution_delegataire_nom?: string | null;
  equipe_parente?:              string | null; // UUID de l'équipe de tête à laquelle celle-ci est rattachée comme ressource (lecture seule, voir TeamService.rattacherEquipe/detacherEquipe)
  equipe_parente_nom?:          string | null;
  sous_equipes_info?:           { id: string; nom: string }[];
  member_ids:           string[];
  members_info?:        TeamMemberInfo[];
  assigned_crisis_ids:  string[];
  assigned_offer_ids:   string[];
  assigned_request_ids: string[];
  assigned_information_ids: string[];
  competence_ids:       string[];
  departements:         string[];           // codes département déclarés (ex: ['38', '73'])
  communes:             string[];           // codes commune INSEE déclarés, plus précis
  zone_precise?:        string | null;      // WKT en écriture (le plus précis des 3 niveaux)
  zone_precise_geojson?: Polygon | null;    // GeoJSON natif en lecture, prêt pour ZoneMapComponent
  missions:             TeamMission[];      // calculé localement, non envoyé à l'API
  created_at?:          string;
  actif?:               boolean;           // false = désactivée (politique de désactivation)
  commune_centre?:      { latitude: number | null; longitude: number | null } | null;
}