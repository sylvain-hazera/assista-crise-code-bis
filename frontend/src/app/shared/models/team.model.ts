import type { Polygon } from "geojson";

/** Message du salon Matrix d'une équipe, relayé par TeamViewSet.salon_matrix_messages (le
 * backend parle à Synapse via le jeton du bot, jamais un jeton exposé au navigateur -- voir
 * core/matrix.py). Consommé par MatrixSalonChatComponent. */
export interface MatrixMessage {
  /** `event_id` pour un message Matrix (voir TeamViewSet.salon_matrix_messages) -- reste
   * nommé ainsi pour compat, mais contient l'UUID du message pour les sources mesh (voir
   * `source`, TeamViewSet.messagerie_unifiee). */
  event_id:        string;
  texte:           string;
  horodatage:      number;
  expediteur_id:   string | null;
  expediteur_nom:  string;
  moi:             boolean;
  /** Ouvert à tout le monde, y compris un intervenant isolé (décision utilisateur du 26/09). */
  urgent:          boolean;
  /** Noms des cadres ayant posé l'accusé "Vu" (réaction Matrix filtrée côté backend, voir
   * TeamViewSet.salon_matrix_messages) -- vide si personne, jamais rempli par un non-cadre.
   * Toujours vide pour les sources mesh (pas de concept de "Vu" côté MeshCore/Meshtastic). */
  vu_par:          string[];
  /** Canal d'origine du message -- absent (undefined) pour un message Matrix "classique" via
   * salon_matrix_messages ; toujours posé par messagerie_unifiee (fenêtre d'équipe fusionnée,
   * 2026-10-05), y compris 'matrix', pour afficher un badge discret par message. */
  source?:         'matrix' | 'meshcore' | 'meshtastic';
}

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
  /** Temps d'engagement continu sans repos (page Cellule de crise) -- null = au repos/pas
   * encore engagée. Manuel dans les deux sens, voir TeamService.demarrerEngagement/
   * mettreAuRepos. */
  engagement_debut?:    string | null;
}

/** Nom affiché d'une équipe, préfixé par son institution responsable (ex: "Mairie de Rion des
 * Landes - Cellule population") -- à utiliser partout où des équipes de PLUSIEURS institutions
 * peuvent apparaître ensemble (sélecteurs/listes/carte zone-filtrés, pas une fiche d'équipe ou
 * un sélecteur déjà restreint à une seule institution, où le préfixe serait redondant).
 * Demande utilisateur du 2026-10-15 : repérer vite qui est qui en environnement multi-entité. */
export function teamDisplayName(team: Pick<Team, 'name' | 'institution_nom'>): string {
  return team.institution_nom ? `${team.institution_nom} - ${team.name}` : team.name;
}