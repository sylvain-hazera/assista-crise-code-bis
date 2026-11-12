/** Suivi du relogement des familles sinistrées (voir backend/core/relogement.py).
 *
 * Deux niveaux, et c'est volontaire : un DOSSIER porte le foyer et son parcours, une SOLUTION
 * est un hébergement successif. Un foyer passe presque toujours par plusieurs solutions —
 * gymnase, hôtel, logement communal, bail — et c'est ce parcours que le bilan de fin de crise
 * demande. Une seule ligne mise à jour en place le détruirait.
 */

export type TypeSolutionRelogement =
  'URGENCE' | 'TEMPORAIRE' | 'INTERMEDIAIRE' | 'DEFINITIVE';

export type TitreOccupation =
  'CENTRE' | 'HOTEL' | 'PROCHES' | 'PRET' | 'CONVENTION' | 'BAIL' | 'RETOUR';

export type StatutDossierRelogement =
  'EN_RECHERCHE' | 'HEBERGE' | 'RELOGEE' | 'RETOUR_DOMICILE' | 'CLOS_SANS_SUITE';

export const LIBELLES_TYPE_SOLUTION: Record<TypeSolutionRelogement, string> = {
  URGENCE: "Hébergement d'urgence",
  TEMPORAIRE: 'Solution temporaire',
  INTERMEDIAIRE: 'Solution intermédiaire',
  DEFINITIVE: 'Solution définitive',
};

export const LIBELLES_TITRE_OCCUPATION: Record<TitreOccupation, string> = {
  CENTRE: "Centre d'hébergement", HOTEL: 'Hôtel ou meublé', PROCHES: 'Hébergée par des proches',
  PRET: 'Prêt à titre gratuit', CONVENTION: "Convention d'occupation", BAIL: 'Bail',
  RETOUR: 'Retour au domicile',
};

export const LIBELLES_STATUT_RELOGEMENT: Record<StatutDossierRelogement, string> = {
  EN_RECHERCHE: 'Sans solution — en recherche', HEBERGE: 'Hébergée',
  RELOGEE: 'Relogée durablement', RETOUR_DOMICILE: 'Retournée au domicile',
  CLOS_SANS_SUITE: 'Clos sans suite',
};

export interface SolutionRelogement {
  id: string;
  dossier_relogement: string;
  type_solution: TypeSolutionRelogement;
  type_solution_libelle: string;
  titre_occupation: TitreOccupation;
  titre_occupation_libelle: string;
  point?: string | null;
  point_nom?: string | null;
  offre?: string | null;
  offre_titre?: string | null;
  adresse?: string | null;
  commune_code?: string;
  commune_nom?: string;
  hebergeur?: string | null;
  hebergeur_contact?: string | null;
  date_debut: string;
  date_fin_prevue?: string | null;
  date_fin_effective?: string | null;
  motif_fin?: string;
  loyer_mensuel?: number | null;
  reste_a_charge?: number | null;
  prise_en_charge_par?: string;
  commentaire?: string | null;
  /** Calculés par le SERVEUR : « arrive à son terme » décide d'une relance, et deux calculs
   * de dates finiraient par diverger. Négatif = terme dépassé sans sortie enregistrée. */
  en_cours: boolean;
  jours_restants?: number | null;
  date_creation: string;
}

export interface DossierRelogement {
  id: string;
  crise: string;
  crise_nom?: string | null;
  institution?: string | null;
  institution_nom?: string | null;
  nom_referent: string;
  telephone_referent?: string | null;
  email_referent?: string | null;
  nombre_adultes: number;
  nombre_enfants: number;
  nombre_personnes: number;
  personnes_vulnerables: boolean;
  animaux: boolean;
  besoin_pmr: boolean;
  commune_origine_code?: string;
  commune_origine_nom?: string;
  demande?: string | null;
  dossier?: string | null;
  habitation?: string | null;
  statut: StatutDossierRelogement;
  statut_libelle: string;
  accompagnement?: string | null;
  date_ouverture: string;
  date_cloture?: string | null;
  solutions: SolutionRelogement[];
  solution_courante?: SolutionRelogement | null;
  date_creation: string;
  date_maj: string;
}

/** Les chiffres du bilan, calculés sur TOUTE la crise et non sur les lignes affichées. */
export interface SyntheseRelogement {
  crise: string;
  crise_nom: string;
  date_arrete: string;
  foyers: number;
  personnes: number;
  adultes: number;
  enfants: number;
  foyers_avec_personnes_vulnerables: number;
  par_statut: Record<string, number>;
  par_type_solution_courante: Record<string, number>;
  /** Seules les solutions DÉFINITIVES : un foyer à l'hôtel n'est pas relogé. */
  relogees_durablement: number;
  sans_solution: number;
  sans_solution_ids: string[];
  arrivent_a_terme: number;
  arrivent_a_terme_ids: string[];
  /** Terme prévu dépassé sans sortie enregistrée : personne ne sait où en est cette famille. */
  termes_depasses: number;
  termes_depasses_ids: string[];
  jours_alerte_terme: number;
}
