import { AffectationPointBenevole } from './affectation-point-benevole.model';
import { ResponsableContact } from './materiel-point.model';

export interface PointType {
  id: string;
  code: string;
  libelle: string;
  description?: string | null;
  actif: boolean;
}

export interface PointOperationnel {
  id: string;
  nom: string;
  type: string;
  type_libelle?: string | null;
  type_code?: string | null;
  crise: string | null;
  crise_nom?: string | null;
  responsable: string | null;
  responsable_nom?: string | null;
  /** Calculé côté serveur (admin, responsable du point, ou chef/membre de son équipe) — pour
   * conditionner l'affichage des boutons Secrétariat/Stock sur les droits réels plutôt que
   * juste "point déjà créé". */
  peut_gerer?: boolean;
  adresse?: string | null;
  commune_nom?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  obligatoire: boolean;
  actif: boolean;
  commentaire?: string | null;
  description?: string | null;
  capacite_accueil?: number | null;
  date_ouverture?: string | null;
  date_fermeture?: string | null;
  competences_requises?: string[];
  competences_requises_libelles?: string[];
  equipe?: string | null;
  equipe_nom?: string | null;
  personnes_presentes?: number;
  civils_accueillis?: number;
  responsables_ids?: string[];
  responsables_contacts?: ResponsableContact[];
  equipes_gestion_ids?: string[];
  equipes_gestion_noms?: string[];
  equipes_ravitaillement_ids?: string[];
  equipes_ravitaillement_noms?: string[];
}

export interface VueOperationnelleEquipe {
  id: string;
  nom: string;
  effectif: number;
  materiel: {
    titre: string;
    materiel_type: string | null;
    materiel_catalogue_nom: string | null;
    quantite: number | null;
    unite: string | null;
  }[];
}

export interface VueOperationnelle {
  equipes_gestion: VueOperationnelleEquipe[];
  equipes_ravitaillement: VueOperationnelleEquipe[];
  civils_accueillis: number;
}

/** Version publique, à champs restreints, renvoyée par GET /points-operationnels/centres_accueil/
 * — voir PointOperationnelPublicSerializer côté backend. */
export interface CentreAccueilPublic {
  id: string;
  nom: string;
  adresse: string | null;
  latitude: number | null;
  longitude: number | null;
  capacite_accueil: number | null;
  personnes_presentes: number;
  crise: string | null;
  type_code?: string | null;
  type_libelle?: string | null;
}

export interface PointEquipeMembre {
  id: string;
  nom: string;
  email: string;
  temps_total_heures?: number;
}

export interface PointEquipeResponse {
  membres: PointEquipeMembre[];
  disponibilites: {
    id: string;
    point: string;
    membre: string;
    membre_nom: string;
    date: string;
    creneau: 'MATIN' | 'MIDI' | 'SOIR' | 'NUIT';
    affectation_statut?: string | null;
  }[];
  affectations: AffectationPointBenevole[];
}

export interface PointOperationnelPayload {
  nom: string;
  type: string;
  crise?: string;  // optionnel : un point de regroupement des moyens créé depuis une équipe n'est pas forcément lié à une crise précise
  adresse?: string;
  commentaire?: string;
  institution?: string;
  description?: string;
  capacite_accueil?: number | null;
  date_ouverture?: string | null;
  date_fermeture?: string | null;
  location?: string;
  competences_requises?: string[];
  equipe?: string | null;
  responsable?: string | null;
  // Alternative à `equipe` (mutuellement exclusifs) : crée une équipe portant ce nom en même
  // temps que le point, plutôt que d'obliger à en créer une séparément avant. Ignoré si
  // `equipe` est déjà renseigné.
  nouvelle_equipe_nom?: string;
  equipes_gestion_ids?: string[];
  equipes_ravitaillement_ids?: string[];
  responsables_ids?: string[];
}
