/** Message retenu pour relecture avant envoi.
 *
 * Servi par `/api/brouillons-envoi/`. Le `corps` porte `[LIEN_1]`, `[LIEN_2]`… : les vraies URL
 * restent côté serveur et ne sont restaurées qu'au moment de l'envoi. Un lien magique est un
 * porteur d'identité, et le relecteur n'est pas forcément le titulaire du compte concerné — un
 * administrateur qui déclenche une réinitialisation de mot de passe pour quelqu'un d'autre en
 * est le cas réel. Les placeholders doivent donc être **conservés** dans le texte relu. */
export interface BrouillonEnvoi {
  id: string;
  institution: string;
  institution_nom: string;
  cree_par_nom: string | null;
  canal: 'EMAIL' | 'SMS';
  statut: 'A_RELIRE' | 'ENVOYE' | 'ABANDONNE' | 'EXPEDIE_AUTO';
  statut_libelle: string;
  sujet: string;
  corps: string;
  destinataires: string[];
  /** Renseigné pour un SMS seulement : la facturation est au segment, et un texte de
   * 161 caractères coûte deux fois celui de 160. */
  segments: { segments: number; restants: number; longueur: number } | null;
  modifie_par_relecteur: boolean;
  erreur: string;
  date_creation: string;
  date_traitement: string | null;

  /** Partagé par les messages d'une même action ayant le même texte générique. Null = message
   * unique, relu seul. */
  lot: string | null;
  /** Combien de messages ce texte représente. Servi par `lots-a-relire` ; 1 pour un message
   * isolé. */
  effectif?: number;
  /** Tous les destinataires du lot, pas seulement ceux de ce message : c'est à ça qu'on juge
   * l'ampleur de ce qu'on valide. */
  destinataires_du_lot?: string[];
}

/** Résultat de l'envoi d'un lot. Les échecs sont NOMMÉS et non comptés : un lot
 * « partiellement envoyé » qu'on croirait complet serait pire qu'un échec franc. */
export interface ResultatEnvoiLot {
  envoyes: number;
  echecs: { destinataires: string[]; motif: string }[];
}

/** Un message du catalogue, personnalisable par une institution. */
export interface ModeleCatalogue {
  cle: string;
  libelle: string;
  /** Quand le message part et à qui : une institution qui réécrit un texte sans le savoir
   * réécrit à l'aveugle. */
  quand: string;
  canal: 'EMAIL' | 'SMS';
  relisible: boolean;
  sujet_defaut: string;
  corps_defaut: string;
  /** `lien: true` = placeholder porteur d'un secret, jamais résolu ailleurs qu'à l'envoi et
   * impossible à ajouter à la main. */
  placeholders: { nom: string; lien: boolean }[];
}

/** Le texte réécrit par une institution. Un champ vide garde le défaut pour CE champ. */
export interface ModeleMessage {
  id: string;
  institution: string;
  cle: string;
  sujet: string;
  corps: string;
  actif: boolean;
  date_modification: string;
}
