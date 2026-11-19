/** Réponse de GET /api/compagnons-meshtastic/<id>/tableau/ (backend/core/tableau_radio.py). */
export type FenetreTableauRadio = '1h' | '6h' | '24h' | '7j';

export interface PointTableau { t: string; v: number; }

export interface NoeudTableau {
  node_num: number; id: string; nom: string; nom_court: string; materiel: string;
  batterie: number | null; tension: number | null; sauts: number | null; snr: number | null;
  dernier_entendu: string | null; position: boolean;
}

export interface TracerouteTableau {
  cible: number | null; cible_nom: string; date: string | null;
  aller: { node_num: number | null; nom: string }[]; snr_aller: (number | null)[];
  retour: { node_num: number | null; nom: string }[]; snr_retour: (number | null)[];
}

export interface HistoriqueNoeud {
  node_num: number; fenetre: FenetreTableauRadio; pas_s: number; debut: string; nombre_mesures: number;
  series: Record<'batterie' | 'tension' | 'occupation_canal' | 'temps_antenne_tx', PointTableau[]>;
}

export interface TableauRadio {
  fenetre: FenetreTableauRadio; pas_s: number; debut: string;
  passerelle: { id: string; nom: string; node_num: number };
  series: Record<'occupation_canal' | 'temps_antenne_tx' | 'batterie' | 'paquets_tx' | 'paquets_rx'
    | 'paquets_recus_par_heure', PointTableau[]>;
  types_paquets: { type: string; nombre: number }[];
  noeuds: NoeudTableau[];
  traceroutes: TracerouteTableau[];
}
