export interface TeamMission {
  id:      string;
  kind:    'Crisis' | 'Offer' | 'Request';
  titre:   string;
  statut?: string;
  date?:   string;
}

export interface Team {
  id?:                  string;
  name:                 string;
  description:          string;
  color:                string;
  leader:               string | null;      // UUID du chef
  member_ids:           string[];
  assigned_crisis_ids:  string[];
  assigned_offer_ids:   string[];
  assigned_request_ids: string[];
  missions:             TeamMission[];      // calculé localement, non envoyé à l'API
  created_at?:          string;
}