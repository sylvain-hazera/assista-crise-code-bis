export type TypePersonneAccueillie = 'EVACUE' | 'POMPIER' | 'BENEVOLE_AUTRE_EQUIPE' | 'INTERVENANT' | 'AUTRE';

export interface RegistrePresence {
  id: string;
  point: string;
  type_personne: TypePersonneAccueillie;
  type_personne_libelle?: string;
  nom?: string;
  nombre: number;
  date_arrivee: string;
  date_depart: string | null;
  commentaire?: string | null;
  enregistre_par: string | null;
  enregistre_par_nom?: string | null;
  /** Admission d'un évacué : sa déclaration, et si son contact reste à compléter. */
  declaration?: string | null;
  contact_a_completer?: boolean;
  email_manquant?: boolean;
  telephone_manquant?: boolean;
}

export interface RegistrePresencePayload {
  point: string;
  type_personne: TypePersonneAccueillie;
  nom?: string;
  nombre?: number;
  commentaire?: string;
}
