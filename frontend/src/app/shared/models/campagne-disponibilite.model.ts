/** Campagnes de disponibilité : solliciter en masse ses bénévoles pour une période à venir.
 *
 * Voir backend/core/campagnes_disponibilite.py. Deux choses à retenir de la forme de ces types :
 *
 * - **la période est une donnée, pas une phrase.** `periode_debut` / `periode_fin` bornent la
 *   grille que le bénévole voit et les rotations qu'on en tire. Un mail qui annonce « du 12 au
 *   26 » dans son corps ne permet rien.
 * - **le motif est typé.** On n'écrit pas la même chose avant, pendant et après une crise, et
 *   un texte libre ne permettrait ni de trier les campagnes passées ni d'adapter le ton.
 */

export type MotifCampagne =
  'CRISE_A_VENIR' | 'CRISE_EN_COURS' | 'RETABLISSEMENT' | 'EXERCICE';

export type StatutCampagne = 'BROUILLON' | 'ENVOYEE' | 'CLOTUREE';

export type EchelonCiblage =
  'NATIONAL' | 'ZONE_DEFENSE' | 'REGION' | 'DEPARTEMENT' | 'COMMUNE' | 'RAYON_CRISE';

export const MOTIFS: { valeur: MotifCampagne; libelle: string; aide: string }[] = [
  { valeur: 'CRISE_A_VENIR', libelle: 'Crise à venir',
    aide: 'Prévisions, vigilance météo : on prépare le dispositif avant.' },
  { valeur: 'CRISE_EN_COURS', libelle: 'Crise en cours',
    aide: 'On est engagé et il faut organiser la relève.' },
  { valeur: 'RETABLISSEMENT', libelle: 'Rétablissement long terme',
    aide: "L'urgence est passée, la présence doit durer." },
  { valeur: 'EXERCICE', libelle: 'Exercice ou formation',
    aide: 'Hors crise réelle.' },
];

export const ECHELONS: { valeur: EchelonCiblage; libelle: string }[] = [
  { valeur: 'NATIONAL', libelle: 'National — toute l\'association' },
  { valeur: 'ZONE_DEFENSE', libelle: 'Zone de défense' },
  { valeur: 'REGION', libelle: 'Région' },
  { valeur: 'DEPARTEMENT', libelle: 'Département' },
  { valeur: 'COMMUNE', libelle: 'Commune' },
  { valeur: 'RAYON_CRISE', libelle: 'Rayon autour de la crise' },
];

/** Où en est la campagne, en nombres.
 *
 * `sans_reponse` ne compte PAS ceux qui ont répondu « aucune disponibilité » : les confondre
 * ferait relancer quelqu'un qui a déjà répondu non, ce qui est le meilleur moyen de ne plus
 * être lu. */
export interface SuiviCampagne {
  cibles: number;
  contactes: number;
  ont_repondu: number;
  sans_reponse: number;
  injoignables: number;
  /** Ceux qui ont répondu ET déclaré au moins un créneau. */
  disponibles: number;
}

export interface CampagneDisponibilite {
  id: string;
  institution: string;
  intitule: string;
  motif: MotifCampagne;
  motif_libelle?: string;
  /** Le « pourquoi », écrit par l'association et inséré dans le message. */
  texte: string;
  crise: string | null;
  crise_nom?: string | null;
  periode_debut: string;
  periode_fin: string;
  nombre_de_jours?: number;
  /** Vide = les quatre créneaux. Une permanence de nuit ne se demande pas en cochant
   * « disponible » tout court. */
  creneaux: string[];
  echelon: EchelonCiblage;
  echelon_libelle?: string;
  territoire_code: string;
  rayon_km: number | null;
  competences: string[];
  qualifications: string[];
  /** Exige des titres vérifiés, non périmés, et une aptitude valide. */
  titres_a_jour: boolean;
  equipe: string | null;
  equipe_nom?: string | null;
  duree_rotation_jours: number;
  repos_min_jours: number;
  /** 0 = on recueille des disponibilités sans armer de tours de garde. */
  effectif_cible: number;
  statut: StatutCampagne;
  statut_libelle?: string;
  cree_par?: string | null;
  cree_par_nom?: string | null;
  date_creation?: string;
  date_envoi?: string | null;
  date_cloture?: string | null;
  suivi?: SuiviCampagne;
}

export interface CibleCampagne {
  id: string;
  campagne: string;
  utilisateur: string;
  nom: string;
  etat: 'A_CONTACTER' | 'CONTACTE' | 'A_REPONDU' | 'INJOIGNABLE';
  etat_libelle?: string;
  date_envoi: string | null;
  date_reponse: string | null;
  /** Zéro EST une réponse : « je ne suis pas disponible ». */
  creneaux_declares: number;
  erreur?: string;
}

export interface ApercuCiblage {
  creees: number;
  retirees: number;
  total: number;
  cibles: CibleCampagne[];
  tronque: boolean;
}

export interface AffectationRotation {
  id: string;
  rotation: string;
  utilisateur: string;
  nom: string;
  creneau: string;
  statut: 'PROPOSEE' | 'CONFIRMEE' | 'RETIREE';
  statut_libelle?: string;
  /** Pourquoi le planificateur a retenu cette personne. Une proposition qu'on ne peut pas
   * expliquer ne se relit pas, elle se subit. */
  motif: string;
}

export interface RotationCampagne {
  id: string;
  campagne: string;
  numero: number;
  date_debut: string;
  date_fin: string;
  affectations: AffectationRotation[];
}

/** Bilan d'une génération de rotations. `manques` nomme les créneaux en sous-effectif : une
 * grille qui paraît complète parce qu'on a caché les trous est pire que pas de grille. */
export interface BilanRotations {
  rotations: number;
  proposees: number;
  conservees: number;
  manques: { rotation: number; creneau: string; attendus: number; trouves: number }[];
}

/** Couverture jour par jour : le seul chiffre qui dise si la garde est armée. Un taux de
 * réponse de 80 % ne dit rien si tous les répondants sont libres le même jour. */
export interface CouvertureCampagne {
  creneaux: string[];
  jours: { date: string; creneaux: Record<string, number> }[];
}
