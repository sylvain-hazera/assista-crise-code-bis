/** Fiche d'un bénévole d'association.
 *
 * Alignée sur le modèle des ressources (`Offer`, `Habitation`) : adresse texte, point géocodé,
 * et secteur dénormalisé. Un bénévole se cherche et se filtre comme une offre d'aide — « une
 * ressource particulière, qui se trouve être membre de l'association ».
 *
 * Le SECTEUR est en lecture seule : il est posé par le géocodage de l'adresse. Le laisser
 * saisir permettrait de se déclarer dans un département où l'on n'habite pas, donc de
 * rejoindre une équipe qui n'est pas la sienne. */
export interface FicheBenevole {
  id: string;
  utilisateur: string;

  adresse: string;
  code_postal: string;
  ville: string;

  latitude: number | null;
  longitude: number | null;
  commune_code: string | null;
  epci_code: string | null;
  departement_code: string | null;
  region_code: string | null;

  date_naissance: string | null;
  metier: string;
  situation: SituationProfessionnelle | '';
  situation_libelle?: string;
  /** Volume d'engagement annoncé à l'adhésion. **Ce n'est pas une disponibilité** : les
   * disponibilités datées vivent dans `DisponibiliteOperationnelle`, le seul moteur que lit la
   * constitution d'équipe (voir `MesDisponibilitesService`). Garder les deux sous le même mot
   * laissait croire à deux sources pour la même question. */
  frequence_engagement: FrequenceEngagement | '';
  frequence_engagement_libelle?: string;
  message: string;
  /** DÉCLARATIF. Une qualification vérifiée vit dans QualificationMembre, avec ses dates et
   * son justificatif : les confondre ferait passer une case cochée pour un diplôme contrôlé. */
  diplome_premier_secours: boolean;
  date_adhesion: string | null;

  /** Nul tant que la personne n'a pas relu sa fiche. */
  completee_le: string | null;
  /** De quoi joindre la personne et savoir où elle est. Le reste est utile mais n'empêche pas
   * de la mobiliser. */
  est_complete: boolean;
  date_modification: string;

  /** Servi par l'endpoint `ma-fiche-benevole` seulement : l'interface en a besoin pour choisir
   * entre « choisir un mot de passe » et « le modifier ». */
  mot_de_passe_defini?: boolean;
  /** Présent quand l'adresse n'a pas pu être géolocalisée : la fiche reste exploitable, on ne
   * sait simplement pas placer la personne sur une carte. */
  avertissement?: string;
}

export type SituationProfessionnelle =
  | 'SALARIE' | 'RETRAITE' | 'INDEPENDANT' | 'FONCTIONNAIRE' | 'ETUDIANT'
  | 'RECHERCHE_EMPLOI' | 'AUTRE';

export type FrequenceEngagement = 'OCCASIONNELLE' | 'REGULIERE' | 'FREQUENTE';

/** Libellés repris du formulaire d'adhésion : les reformuler rendrait incomparables les
 * réponses déjà collectées. */
export const SITUATIONS: { valeur: SituationProfessionnelle; libelle: string }[] = [
  { valeur: 'SALARIE', libelle: 'Salarié(e)' },
  { valeur: 'RETRAITE', libelle: 'Retraité(e)' },
  { valeur: 'INDEPENDANT', libelle: "Chef(fe) d'entreprise, artisan, profession libérale" },
  { valeur: 'FONCTIONNAIRE', libelle: 'Fonctionnaire' },
  { valeur: 'ETUDIANT', libelle: 'Étudiant(e)' },
  { valeur: 'RECHERCHE_EMPLOI', libelle: "En recherche d'emploi" },
  { valeur: 'AUTRE', libelle: 'Autre' },
];

export const FREQUENCES_ENGAGEMENT: { valeur: FrequenceEngagement; libelle: string }[] = [
  { valeur: 'OCCASIONNELLE', libelle: 'Occasionnelle (moins de 5 jours par an)' },
  { valeur: 'REGULIERE', libelle: 'Régulière (environ 10 jours par an)' },
  { valeur: 'FREQUENTE', libelle: 'Fréquente (plus de 10 jours par an)' },
];

/** Une journée de la grille personnelle. `disponible: null` = non renseigné, et c'est une
 * information : un blanc n'est pas un refus. */
export interface JourDisponibilitePersonnel {
  date: string;
  disponible: boolean | null;
}

/** Réponse de `/api/mes-disponibilites/`. `rattachements` est vide pour qui n'appartient à
 * aucune institution : l'écran doit le DIRE plutôt que d'afficher une grille vide
 * inexpliquée. */
export interface MesDisponibilites {
  rattachements: { affectation: string; institution: string; institution_nom: string }[];
  jours: JourDisponibilitePersonnel[];
}
