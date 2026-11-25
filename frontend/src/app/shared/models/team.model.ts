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
  description:          string | null;
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
  indicatif?:                   string;        // Indicatif radio (« @ALPHA » sur le canal de crise), 23/11/2026
  transmissions?:               boolean;       // Équipe transmissions : trie le pot commun des messages radio
  est_equipe_rcsc?:             boolean;       // Marque cette équipe comme LA RCSC de son institution (lecture seule, voir TeamService.designerRcsc) -- conditionne l'accès au registre des personnes vulnérables

  sous_equipes_info?:           { id: string; nom: string }[];
  canal_meshcore_id?:           string | null;
  canal_meshcore_nom?:          string | null;
  canal_meshcore_provisionne?:  boolean;
  canal_meshtastic_id?:         string | null;
  canal_meshtastic_nom?:        string | null;
  /** Canal radio de l'équipe par protocole (25/11/2026) : jamais la clé, seulement son origine et
   * une empreinte courte. */
  canaux_radio?:                CanauxRadioEquipe;
  /** Salon Matrix de l'équipe entière. Reste au singulier et désigne le salon INTERVENANTS :
   * c'est celui que le bouton « messagerie » ouvre, et c'était le seul avant le 11/11/2026. */
  salon_matrix_id?:             string | null;
  salon_matrix_room_id?:        string | null;
  /** Les deux salons de l'équipe. `room_id` vide = provisionné côté Django mais pas encore
   * créé côté Synapse (le pont y passe toutes les 30 s). */
  salons_matrix?:               SalonMatrixEquipe[];

  /** Échelon territorial (arborescence de coordination). Vide pour une équipe opérationnelle
   * ordinaire, qui n'appartient à aucune hiérarchie. */
  echelon?:                     EchelonEquipe | '';
  echelon_libelle?:             string | null;
  /** Code INSEE pour une région ou un département, identifiant de zone (« ZD-SUD ») pour une
   * zone de défense. Jamais interprété géographiquement : le matching d'intervention reste
   * celui de `departements` / `communes` / `zone_precise`. */
  territoire_code?:             string;
  territoire_libelle?:          string;
  /** Membres formant l'encadrement de CETTE équipe (lecture seule : voir
   * TeamService.definirEncadrement). Ils peuplent le salon « Encadrement » de cette équipe et
   * celui de l'équipe parente — un seul niveau au-dessus (« n-1 »). */
  membres_encadrement?:         string[];
  member_ids:           string[];
  members_info?:        TeamMemberInfo[];
  vehicules_count?:     number;            // Offres de type Transport affectées à l'équipe (lecture seule)
  /** Peut en modifier la structure, la composition et l'encadrement (règle de l'arbre,
   * backend/core/gestion_equipes.py) — plus étroit que `peut_gerer` dans une association. */
  peut_administrer?:    boolean;
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

export type EchelonEquipe =
  | 'NATIONAL' | 'ZONE_DEFENSE' | 'REGIONAL' | 'DEPARTEMENTAL' | 'COMMUNAL';

/** Du plus large au plus fin — sert à trier une arborescence. Une équipe sans échelon vient
 * après : elle ne doit pas s'intercaler entre deux échelons. Miroir de ORDRE_ECHELONS
 * (backend/core/models.py). */
export const ORDRE_ECHELONS: EchelonEquipe[] = [
  'NATIONAL', 'ZONE_DEFENSE', 'REGIONAL', 'DEPARTEMENTAL', 'COMMUNAL',
];

export function rangEchelon(echelon: EchelonEquipe | '' | null | undefined): number {
  if (!echelon) return ORDRE_ECHELONS.length;
  const rang = ORDRE_ECHELONS.indexOf(echelon);
  return rang === -1 ? ORDRE_ECHELONS.length : rang;
}

export type TypeSalonEquipe = 'INTERVENANTS' | 'ENCADREMENT';

export interface SalonMatrixEquipe {
  id: string;
  type: TypeSalonEquipe;
  type_libelle: string;
  /** Vide tant que matrix-bridge ne l'a pas créé côté Synapse. */
  room_id: string | null;
}

/** Nom préfixé par l'institution responsable, pour les listes mêlant plusieurs institutions. */
export function teamDisplayName(team: Pick<Team, 'name' | 'institution_nom'>): string {
  return team.institution_nom ? `${team.institution_nom} - ${team.name}` : team.name;
}

/** Échelons de coordination : leur encadrement s'appelle « Bureau de la coordination ». */
export const ECHELONS_COORDINATION = ['NATIONAL', 'ZONE_DEFENSE', 'REGIONAL', 'DEPARTEMENTAL'];

export function libelleEncadrementEquipe(echelon: string | null | undefined): string {
  return echelon && ECHELONS_COORDINATION.includes(echelon) ? 'Bureau de la coordination' : 'Encadrement';
}

// ── Canal radio de l'équipe (25/11/2026) ────────────────────────────────────────────────
export type ProtocoleRadio = 'MESHTASTIC' | 'MESHCORE';

export interface EtatCanalRadio {
  nom: string;
  personnalise: boolean;
  /** Clé fournie par la structure : la plateforme ne la régénère jamais. */
  cle_fournie: boolean;
  /** Repris d'une passerelle de la structure. */
  repris: boolean;
  empreinte: string;
  actif: boolean;
  sur_passerelle: boolean;
}

export interface CanauxRadioEquipe {
  meshtastic: EtatCanalRadio | null;
  meshcore: EtatCanalRadio | null;
}

export interface CanalPasserelle {
  id: string;
  protocole: ProtocoleRadio;
  nom: string;
  passerelle: string;
  public: boolean;
  deja_le_notre: boolean;
  empreinte: string;
}

export interface CanauxPasserelle {
  canaux: CanalPasserelle[];
  entendus_sans_cle: number;
}

export interface LienCanaux {
  meshtastic_lien: string | null;
  meshtastic: { role: string; nom: string }[];
  meshcore: { role: string; nom: string; cle_hex: string }[];
  crise: string | null;
  qr_svg: string | null;
}

// ── Nœuds radio dédiés de l'équipe (25/11/2026) ─────────────────────────────────────────
export interface NoeudEquipe {
  id: string;
  protocole: ProtocoleRadio;
  identifiant: string;
  nom: string;
  etat: 'EN_RESERVE' | 'CONFIE' | 'HORS_SERVICE';
  etat_libelle: string;
  confie_a: string | null;
  confie_a_nom: string | null;
  appareil: string | null;
  configure_le: string | null;
  moyen_configuration: string;
  a_jour: boolean;
  remarque: string;
}

export interface NoeudsEquipe {
  version_plan: string;
  noeuds: NoeudEquipe[];
}
