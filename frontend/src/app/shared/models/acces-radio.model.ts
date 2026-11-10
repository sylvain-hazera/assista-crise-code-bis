import { NiveauAccesRadio } from './user.model';

/** Statuts d'une demande — miroir de `StatutDemandeAccesRadio` (backend/core/models.py). */
export type StatutDemandeAccesRadio = 'EN_ATTENTE' | 'ACCORDEE' | 'REFUSEE' | 'RETIREE';

/** Demande d'accès radio, et sa décision : une seule ligne porte les deux, parce que le droit
 * EST la demande instruite (voir DemandeAccesRadio côté serveur). */
export interface DemandeAccesRadio {
  id: string;
  utilisateur: string;
  utilisateur_nom: string | null;
  utilisateur_email: string;
  niveau_demande: NiveauAccesRadio;
  niveau_demande_libelle: string;
  motif: string;
  statut: StatutDemandeAccesRadio;
  statut_libelle: string;
  niveau_accorde: NiveauAccesRadio | null;
  instruite_par: string | null;
  instruite_par_nom: string | null;
  commentaire_decision: string;
  date_demande: string;
  date_decision: string | null;
}

/** Réponse de `/api/demandes-acces-radio/mon-acces/`.
 *
 * `motifs` est la liste des titres effectivement constatés, en clair. Sans elle, un compte sans
 * accès n'a aucun moyen de savoir ce qui lui manque, et un compte qui l'a ne sait pas à quel
 * titre — donc ne sait pas ce qu'il perdrait en désactivant son nœud. */
export interface EtatAccesRadio {
  niveau: NiveauAccesRadio;
  niveau_libelle: string;
  motifs: string[];
  nombre_noeuds_personnels: number;
  demande: DemandeAccesRadio | null;
  titres_possibles: string[];
}
