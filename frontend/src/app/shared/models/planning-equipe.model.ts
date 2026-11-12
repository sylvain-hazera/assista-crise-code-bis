/** Planning d'équipe : qui tient quel créneau, quel jour (voir backend/core/planning_equipe.py).
 *
 * À ne pas confondre avec les trois autres tables qui parlent de créneaux, chacune répondant à
 * une question différente : `DisponibiliteOffre` dit quand quelqu'un PEUT venir (une
 * déclaration, jamais une affectation), `AffectationRotation` qui arme un tour de garde d'une
 * campagne, `DisponibilitePointEquipe` qui tient un point opérationnel. Ici : qui tient le soir
 * du 14 pour CETTE équipe.
 */

export type StatutCreneauEquipe =
  'PREVU' | 'CONFIRME' | 'ANNULE' | 'REALISE' | 'ABSENT';

export const LIBELLES_STATUT_CRENEAU: Record<StatutCreneauEquipe, string> = {
  PREVU: 'Prévu', CONFIRME: 'Confirmé', ANNULE: 'Annulé', REALISE: 'Réalisé',
  ABSENT: "Absent (ne s'est pas présenté)",
};

/** Une case occupée du planning. `null` dans la grille = personne sur ce créneau. */
export interface CaseCreneau {
  id: string;
  statut: StatutCreneauEquipe;
  statut_libelle: string;
  role: string;
  point_nom?: string | null;
}

export interface JourPlanning {
  date: string;
  creneaux: Record<string, CaseCreneau | null>;
}

export interface PersonnePlanning {
  utilisateur: string;
  nom: string;
  fonction: string;
  /** Créneaux réellement tenus : les annulés et les absents ne comptent pas. */
  creneaux_tenus: number;
  jours: JourPlanning[];
}

export interface CreneauNonCouvert {
  date: string;
  creneau: string;
  tenu: number;
  cible: number;
  manque: number;
}

export interface PlanningEquipe {
  equipe: string;
  equipe_nom: string;
  debut: string;
  fin: string;
  jours: string[];
  creneaux: string[];
  personnes: PersonnePlanning[];
  /** { "2026-11-14": { "SOIR": 3 } } — effectif tenu, annulés et absents exclus. */
  effectifs: Record<string, Record<string, number>>;
  statuts: { code: StatutCreneauEquipe; libelle: string }[];
  effectif_cible: number;
  non_couverts: CreneauNonCouvert[];
}

/** La même personne attendue par deux équipes au même moment. Nommé, jamais compté : « 3
 * conflits » n'a jamais permis à personne de décider quoi que ce soit. */
export interface ConflitPlanning {
  utilisateur: string;
  nom: string;
  date: string;
  creneau: string;
  equipe: string;
  equipe_nom: string;
  motif: string;
}

export interface EcartDisponibilite {
  utilisateur: string;
  nom: string;
  date: string;
  creneau: string;
  motif: string;
}

export interface ResultatPointage {
  poses: number;
  mis_a_jour: number;
  ignores: { utilisateur?: string; date?: string; creneau?: string; motif: string }[];
  conflits: ConflitPlanning[];
  /** Affecté sur un créneau que la personne n'a pas déclaré : un coup de fil à passer, pas
   * une erreur — un chef d'équipe a le droit d'appeler. */
  hors_disponibilite: EcartDisponibilite[];
}
