export type StatutAffectation = 'EN_ATTENTE' | 'EN_VALIDATION' | 'CONFIRME' | 'DECLINE';

export interface AffectationPointBenevole {
  id: string;
  point: string;
  benevole: string;
  benevole_nom?: string;
  offer: string | null;
  statut: StatutAffectation;
  statut_libelle?: string;
  date_attendue: string;
  point_transit: string | null;
  point_transit_nom?: string | null;
  token_confirmation: string;
  date_reponse: string | null;
  affecte_par: string | null;
  date_creation: string;
}

export interface InviterBenevoleAffectation {
  offer_id: string;
  date_attendue: string;
  creneaux: { date: string; creneau: 'MATIN' | 'MIDI' | 'SOIR' | 'NUIT' }[];
}

export interface InviterBenevolePayload {
  affectations: InviterBenevoleAffectation[];
  point_transit_id?: string | null;
}

export interface InviterBenevoleResponse {
  created: AffectationPointBenevole[];
  errors: { offer_id: string; error: string }[];
}

export interface ValiderBenevolePayload {
  affectation_id: string;
  decision: 'confirmer' | 'refuser';
}
