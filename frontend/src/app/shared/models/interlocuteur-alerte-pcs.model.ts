/** Annuaire PARTAGÉ des interlocuteurs à prévenir lors d'une activation de PCS/PICS -- voir
 * InterlocuteurAlertePCS côté backend. PAS propre à une seule institution : `institutions`
 * liste toutes celles qui l'ont rattaché (ex: le SIDPC d'une préfecture, rattaché par
 * plusieurs communes du même département). */
export type CategorieInterlocuteurPCS =
  | 'PREFECTURE' | 'SOUS_PREFECTURE' | 'GENDARMERIE_POLICE' | 'SDIS' | 'SAMU' | 'ARS'
  | 'SERVICES_ETAT' | 'ELU_PERSONNEL_COMMUNAL' | 'EPCI_INTERCOMMUNALITE' | 'GESTIONNAIRE_RESEAU'
  | 'ETABLISSEMENT_SENSIBLE' | 'ASSOCIATION_SECURITE_CIVILE' | 'MEDIA' | 'AUTRE';

export type ModeAlertePCS = 'EMAIL' | 'MATRIX' | 'TELEPHONE' | 'SMS' | 'API_TIERCE' | 'AUCUN';

export const CATEGORIES_INTERLOCUTEUR_PCS: { value: CategorieInterlocuteurPCS; label: string }[] = [
  { value: 'PREFECTURE', label: 'Préfecture (SIDPC/COD)' },
  { value: 'SOUS_PREFECTURE', label: 'Sous-préfecture' },
  { value: 'GENDARMERIE_POLICE', label: 'Gendarmerie / Police' },
  { value: 'SDIS', label: 'SDIS (secours)' },
  { value: 'SAMU', label: 'SAMU' },
  { value: 'ARS', label: 'ARS (santé)' },
  { value: 'SERVICES_ETAT', label: "Services de l'État (DDT/DREAL...)" },
  { value: 'ELU_PERSONNEL_COMMUNAL', label: 'Élu ou personnel communal' },
  { value: 'EPCI_INTERCOMMUNALITE', label: 'Intercommunalité / EPCI (PICS)' },
  { value: 'GESTIONNAIRE_RESEAU', label: 'Gestionnaire de réseau (élec./gaz/eau)' },
  { value: 'ETABLISSEMENT_SENSIBLE', label: 'Établissement sensible (école, EHPAD...)' },
  { value: 'ASSOCIATION_SECURITE_CIVILE', label: 'Association agréée de sécurité civile' },
  { value: 'MEDIA', label: 'Média local' },
  { value: 'AUTRE', label: 'Autre' },
];

export const MODES_ALERTE_PCS: { value: ModeAlertePCS; label: string; disponible: boolean }[] = [
  { value: 'EMAIL', label: 'Email', disponible: true },
  { value: 'MATRIX', label: 'Message Matrix (compte lié requis)', disponible: true },
  { value: 'TELEPHONE', label: 'Téléphone (manuel uniquement)', disponible: true },
  { value: 'SMS', label: 'SMS — pas encore disponible', disponible: false },
  { value: 'API_TIERCE', label: 'Intégration tierce (Intramuros, Facebook...) — pas encore disponible', disponible: false },
  { value: 'AUCUN', label: 'Aucun envoi automatique', disponible: true },
];

export interface InterlocuteurAlertePCS {
  id: string;
  categorie: CategorieInterlocuteurPCS;
  nom: string;
  organisme: string;
  email: string | null;
  telephone: string | null;
  notes: string | null;
  utilisateur: string | null;
  utilisateur_nom: string | null;
  mode_alerte: ModeAlertePCS;
  /** À quels moments le prévenir : la liste est préparée avec lui déjà coché, puis confirmée d'un clic. */
  prevenir_ouverture_crise?: boolean;
  prevenir_ouverture_centre?: boolean;
  actif: boolean;
  ordre: number;
  departement_code: string | null;
  institutions: string[];
  institutions_noms: string[];
  date_creation?: string;
}
