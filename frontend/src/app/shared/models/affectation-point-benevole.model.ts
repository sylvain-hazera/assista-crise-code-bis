export type StatutAffectation = 'EN_ATTENTE' | 'CONFIRME' | 'DECLINE';

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

export interface InviterBenevolePayload {
  offer_ids: string[];
  date_attendue: string;
  point_transit_id?: string | null;
  creneaux: { date: string; creneau: 'MATIN' | 'MIDI' | 'SOIR' | 'NUIT' }[];
}

export interface InviterBenevoleResponse {
  created: AffectationPointBenevole[];
  errors: { offer_id: string; error: string }[];
}
