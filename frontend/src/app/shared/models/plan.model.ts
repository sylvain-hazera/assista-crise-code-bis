export interface Plan {
  id: string;
  institution: string;
  institution_nom?: string | null;
  nom: string;
  description?: string | null;
  actif: boolean;
  zones_ids: string[];
  zones_noms: string[];
  equipes_ids: string[];
  equipes_noms: string[];
  points_ids: string[];
  points_noms: string[];
}

export interface PlanPayload {
  nom: string;
  description?: string;
  institution?: string;
  zones_ids?: string[];
  equipes_ids?: string[];
  points_ids?: string[];
}

export interface PlanActivationEquipe {
  team_id: string;
  themes_ids?: string[];
}

export interface PlanActivationPayload {
  crise_id?: string;
  nouvelle_crise?: {
    name: string;
    type: string;
    location: string; // GeoJSON stringifié, ex: {"type":"Point","coordinates":[lng,lat]}
  };
  equipes: PlanActivationEquipe[];
  points: string[];
}

export interface PlanActivationResult {
  crise: { id: string; name: string; [key: string]: unknown };
  equipes_activees: string[];
  points_actives: string[];
  dossiers_crees: string[];
}

export type PrioriteDossier = 'URGENTE' | 'NORMALE' | 'BASSE';

/** Modèle de mission pré-enregistré dans un Plan, propre à l'une de ses équipes — instancié en
 * vraie Mission + Dossier à l'activation de cette équipe sur une crise réelle (voir
 * PlanViewSet.activer côté backend). */
export interface PlanMissionModele {
  id: string;
  plan: string;
  equipe: string;
  equipe_nom?: string | null;
  titre: string;
  description?: string | null;
  referent?: string | null;
  referent_nom?: string | null;
  priorite: PrioriteDossier;
}

export interface PlanMissionModelePayload {
  plan: string;
  equipe: string;
  titre: string;
  description?: string;
  referent?: string | null;
  priorite?: PrioriteDossier;
}
