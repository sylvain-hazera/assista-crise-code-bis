/** Modèles de la gestion des membres d'une association agréée de sécurité civile.
 *
 * Voir backend/core/recrutement_association.py et DOCUMENTATION.md § 5.12 bis. Deux principes
 * s'y lisent et expliquent la forme de ces types :
 *
 * - une candidature ne se fait pas avancer en modifiant un champ, mais par les actions du
 *   circuit : `etape` est en lecture seule côté serveur, un PATCH dessus ne fait rien ;
 * - une disponibilité a TROIS valeurs, pas deux — `null` veut dire « non renseigné », ce qui
 *   n'est pas « indisponible ». Confondre les deux fait partir une mobilisation avec un
 *   effectif imaginaire.
 */

export type StatutMembre = 'ACTIF' | 'CONGE' | 'SORTI';

export type EtapeCandidature =
  'DEMANDE' | 'PRISE_EN_CHARGE' | 'VERIFICATION' | 'ACCEPTE' | 'REFUSE';

/** Les quatre étapes du circuit, dans l'ordre. `REFUSE` n'y figure pas : il se prononce depuis
 * n'importe quelle étape non terminale, ce n'est pas une progression. */
export const ETAPES_CIRCUIT: EtapeCandidature[] = [
  'DEMANDE', 'PRISE_EN_CHARGE', 'VERIFICATION', 'ACCEPTE',
];

export interface CandidatureAssociation {
  id: string;
  institution: string;
  institution_nom?: string | null;
  utilisateur: string;
  utilisateur_nom?: string | null;
  utilisateur_email?: string | null;
  etape: EtapeCandidature;
  etape_libelle?: string;
  /** Qui instruit le dossier. Nommément : une candidature dont personne ne se sent
   * responsable est une candidature qui dort. */
  pris_en_charge_par?: string | null;
  pris_en_charge_par_nom?: string | null;
  /** D'où vient la candidature — le libellé du lien d'invitation dit quelle action de
   * recrutement a porté. Vide = demande spontanée. */
  invitation?: string | null;
  invitation_libelle?: string | null;
  message_candidat?: string | null;
  commentaire_bureau?: string | null;
  motif_refus?: string | null;
  date_demande: string;
  date_prise_en_charge?: string | null;
  date_decision?: string | null;
}

export interface InvitationAssociation {
  id: string;
  institution: string;
  institution_nom?: string | null;
  /** Fabriqué par le serveur, jamais accepté en entrée : un lien devinable serait la porte du
   * circuit de recrutement. */
  jeton: string;
  libelle?: string | null;
  cree_par?: string | null;
  cree_par_nom?: string | null;
  date_expiration?: string | null;
  actif: boolean;
  date_creation: string;
  /** Calculé côté serveur : une échéance jugée sur l'horloge du navigateur ne vaut rien. */
  utilisable: boolean;
  nombre_candidatures: number;
}

export interface Qualification {
  id: string;
  nom: string;
  description?: string | null;
  /** Durée habituelle, pour préremplir l'échéance. Vide = sans péremption. */
  validite_mois?: number | null;
  actif: boolean;
}

export interface QualificationMembre {
  id: string;
  utilisateur: string;
  utilisateur_nom?: string | null;
  qualification: string;
  qualification_nom?: string | null;
  date_obtention?: string | null;
  date_expiration?: string | null;
  organisme?: string | null;
  commentaire?: string | null;
  /** Une qualification affirmée par le bureau n'a pas le même poids qu'une ligne déclarée par
   * l'intéressé. */
  saisie_par?: string | null;
  /** Les deux calculés côté serveur : l'horloge d'un poste client est réglable, et un titre
   * qu'on croit valide parce que la date est fausse est l'erreur qu'on découvre le jour de la
   * mobilisation. */
  expiree: boolean;
  jours_avant_expiration: number | null;
}

/** Une case de la grille. `disponible: null` = non renseigné, et c'est une information : elle
 * dit qui relancer. */
export interface JourDisponibilite {
  date: string;
  disponible: boolean | null;
}

export interface MembreGrille {
  utilisateur: string;
  nom: string;
  fonction?: string | null;
  membre_bureau: boolean;
  /** Un titre périmé vaut un titre absent : à montrer à côté du nom, pas à découvrir le jour
   * du départ. */
  qualifications_expirees: number;
  aptitude_valide_jusquau?: string | null;
  jours: JourDisponibilite[];
}

export interface GrilleDisponibilites {
  institution: string;
  institution_nom: string;
  debut: string;
  fin: string;
  jours: string[];
  membres: MembreGrille[];
  /** Les membres en congé ne sont pas listés — ils ne sont pas mobilisables — mais leur nombre
   * est rendu : une liste qui omet des gens sans le dire laisse chercher. */
  membres_en_conge: number;
}
