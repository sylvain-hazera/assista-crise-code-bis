export type TypeQuestion = 'TEXTE' | 'TEXTE_LONG' | 'NOMBRE' | 'OUI_NON' | 'CHOIX' | 'CHOIX_MULTIPLE' | 'DATE' | 'PHOTO';

/** Une question d'un questionnaire de terrain (voir core/formulaires_terrain.py). */
export interface QuestionTerrain {
  /** Posée par le serveur à la première sauvegarde, et jamais changée ensuite : c'est elle qui
   * rattache une réponse déjà saisie à sa question. */
  cle?: string;
  libelle: string;
  type: TypeQuestion;
  obligatoire: boolean;
  aide?: string;
  options?: string[];
  min?: number | null;
  max?: number | null;
  /** Affichée seulement si la question `cle` (placée avant) a reçu la réponse `valeur`. */
  si?: { cle: string; valeur: unknown } | null;
}

export interface FormulaireTerrain {
  id: string;
  titre: string;
  description: string;
  questions: QuestionTerrain[];
  actif: boolean;
  crise: string | null;
  crise_nom?: string | null;
  institution: string;
  institution_nom: string;
  nb_reponses: number;
  /** Vrai pour la collectivité qui l'a composé ; faux pour une institution déléguée. */
  peut_gerer: boolean;
  date_creation: string;
}

export type ValeurReponse = string | number | boolean | string[] | null;

export interface ReponseTerrain {
  id: string;
  saisie_le: string;
  auteur: string;
  institution: string;
  latitude: number | null;
  longitude: number | null;
  donnees: Record<string, ValeurReponse>;
  /** Identifiants des photos jointes, par question ; les images se demandent une à une. */
  photos: Record<string, string[]>;
}

/** Une photo jointe à une réponse, telle qu'elle part — ou attend le retour du réseau.
 * En base64 : c'est ce que la file chiffrée sait ranger. */
export interface PhotoAEnvoyer {
  formulaire: string;
  identifiant_client: string;
  identifiant_photo: string;
  cle: string;
  image: string;
}

/** Une réponse saisie, telle qu'elle part au serveur — ou attend le retour du réseau. */
export interface ReponseAEnvoyer {
  formulaire: string;
  identifiant_client: string;
  donnees: Record<string, ValeurReponse>;
  saisie_le: string;
  latitude?: number | null;
  longitude?: number | null;
}
