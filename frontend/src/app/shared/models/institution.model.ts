import { StatutMembre } from './association.model';

export interface InstitutionType {
  id?: string;
  code: string;
  libelle: string;
  description?: string | null;
  actif: boolean;
}

export interface Institution {
  id?: string;
  nom: string;
  type: string | null;           // UUID de l'InstitutionType
  type_libelle?: string | null;  // résolu côté backend, lecture seule
  description?: string | null;
  telephone?: string | null;
  email?: string | null;
  adresse?: string | null;
  commune_code?: string | null;
  commune_nom?: string | null;
  commune_code_postal?: string | null;
  actif: boolean;
  date_creation?: string;
  // Voir InstitutionSerializer.get_salons_matrix -- toujours les deux clés, valeur null tant
  // que non provisionné (InstitutionViewSet.provisionner_salons_matrix).
  salons_matrix?: {
    PERMANENTS: { id: string; room_id: string | null } | null;
    BENEVOLES: { id: string; room_id: string | null } | null;
  };
}

export interface ContactInstitution {
  id?: string;
  institution: string;   // UUID de l'Institution
  utilisateur: string;   // UUID du User
  utilisateur_nom?: string | null;
  utilisateur_email?: string | null;
  fonction?: string;
  contact_principal: boolean;
  actif: boolean;
  // Zone (catalogue Zone de l'institution) couverte par ce contact — préparation PCS/PICS.
  zone?: string | null;
  date_creation?: string;
  /** Gouvernance de l'institution : administre les membres et instruit les candidatures. Porté
   * par le rattachement et non par le compte — on est au bureau d'UNE association. Reste
   * lisible par quiconque voit la fiche : savoir qui dirige est une information normale. */
  membre_bureau?: boolean;
  /** Les quatre champs ci-dessous ne sont servis QU'au bureau de l'institution concernée, à
   * l'intéressé et à un administrateur (ContactInstitutionSerializer.CHAMPS_SUIVI_ASSOCIATIF).
   * Absents de la réponse sinon — donc `undefined` et non `null` : ne pas les afficher comme
   * « vide », ce serait affirmer qu'il n'y a rien alors qu'on n'a pas le droit de savoir. */
  statut?: StatutMembre;
  date_adhesion?: string | null;
  adhesion_valide_jusquau?: string | null;
  /** Date seule, jamais une information d'aptitude ni un document (RGPD art. 9). */
  aptitude_valide_jusquau?: string | null;
}

export interface InstitutionDomaine {
  id?: number;
  institution: string;   // UUID de l'Institution
  domaine: string;
  valide: boolean;
}

export interface RoleOperationnel {
  id?: string;
  code: string;
  libelle: string;
  description?: string | null;
  actif: boolean;
}

export interface AffectationRoleOperationnel {
  id?: string;
  utilisateur: string;        // UUID du User
  institution: string;        // UUID de l'Institution
  competence: string | null;  // UUID de la Competence — peut être vide juste après activation
  role: string;                // UUID du RoleOperationnel
  actif: boolean;
  date_debut?: string;
  date_fin?: string | null;
  commentaire?: string | null;
  zone?: string | null;               // UUID de la Zone (catalogue de l'institution)
  zone_precise?: string | null;       // WKT, dessin optionnel propre à cette affectation
  responsabilite?: string | null;     // Intitulé libre du périmètre de responsabilité
}
