/** Catalogue partagé des catégories de vulnérabilité -- librement extensible (voir
 * TypeVulnerabilite côté backend), même esprit que RisqueMajeurType/Competence. Description
 * fonctionnelle/opérationnelle uniquement -- jamais un diagnostic médical. */
export interface TypeVulnerabilite {
  id: string;
  nom: string;
  description: string;
  actif: boolean;
}

export type ModeConsentementVulnerabilite = 'VOLONTAIRE' | 'TIERS_AVEC_ACCORD' | 'TIERS_SANS_ACCORD_FORMEL';

/** Fiche du registre communal des personnes vulnérables (voir PersonneVulnerable côté backend)
 * -- donnée sensible, accès restreint à la RCSC/au RESPONSABLE de la mairie compétente ou à une
 * institution avec délégation de compétence active. */
export interface PersonneVulnerable {
  id: string;
  institution_declarante: string;
  institution_declarante_nom?: string;
  commune_code: string;
  zone?: string | null;
  zone_nom?: string | null;
  nom: string;
  prenom: string;
  adresse: string;
  /** Identifiant de l'adresse de la commune à laquelle la fiche est rattachée ; vide = adresse libre. */
  adresse_ban_id?: string | null;
  telephone?: string | null;
  categorie_ids: string[];
  categories_detail?: TypeVulnerabilite[];
  contact_aidant_nom?: string | null;
  contact_aidant_telephone?: string | null;
  mode_consentement: ModeConsentementVulnerabilite;
  demandeur_consentement?: string;
  date_consentement?: string | null;
  actif: boolean;
  cree_par_nom?: string;
  date_creation: string;
  date_maj: string;
}

/** Une adresse du relevé de la commune (Base Adresse Nationale, gardée sur notre serveur). */
export interface AdresseDeLaCommune { ban_id: string; adresse: string; exacte?: boolean; }

/** Où en est le rattachement des fiches du registre aux adresses de la commune. */
export interface EtatRattachement {
  releve_disponible: boolean;
  fiches: number;
  rattachees: number;
  /** Fiches dont l'adresse est, mot pour mot, une adresse du relevé : rattachables d'un coup. */
  exactes: number;
  a_rattacher: { id: string; nom: string; adresse: string; propositions: AdresseDeLaCommune[]; lien_perdu: boolean }[];
  rattachees_a_l_instant?: number;
  /** Aucune adresse connue : le serveur vient de demander le relevé de la commune. */
  releve_demande?: boolean;
}

/** Ce que le rattachement apporte : niveau d'eau qui atteint l'adresse, dégâts constatés. */
export interface ExpositionRegistre {
  seuils: Record<string, number | null>;
  degats: Record<string, string>;
  non_situees: number;
}
