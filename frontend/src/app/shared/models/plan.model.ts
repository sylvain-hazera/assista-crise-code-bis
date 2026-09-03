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
}
