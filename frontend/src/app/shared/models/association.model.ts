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

  /** État d'instruction. DECLAREE est le défaut, et le mot compte : tant que l'encadrement ne
   * s'est pas prononcé, la qualification est une affirmation de son titulaire. */
  statut: 'DECLAREE' | 'VERIFIEE' | 'REFUSEE';
  statut_libelle?: string;
  verifie_par?: string | null;
  verifie_par_nom?: string | null;
  verifie_le?: string | null;
  /** Obligatoire au refus : sans lui le membre ne sait pas quoi corriger. */
  motif_refus?: string;

  /** Présence seulement. Le fichier ne sort que par l'action dédiée, après contrôle des
   * droits — servir une URL ici contournerait ce contrôle. */
  a_justificatif: boolean;
  justificatif_nom?: string;
  justificatif_depose_le?: string | null;
}

/** Ce qui attend une vérification, pour la pastille de notification. */
export interface QualificationsAVerifier {
  total: number;
  /** { id d'utilisateur: [noms de qualifications] } — permet de poser la pastille sur la
   * bonne ligne de l'arborescence sans recharger toute la liste. */
  par_membre: Record<string, string[]>;
}

/** Une journée de la grille : quatre créneaux, cochés ou non.
 *
 * **Deux états par créneau, pas trois.** La grille lisait auparavant un moteur à la journée
 * avec un « non renseigné » ; elle lit maintenant celui à créneaux
 * (`DisponibiliteOffre`), le même que la constitution d'équipe, dont la règle est « pas de
 * ligne = indisponible ». Ce qui restait vrai — distinguer le silence du refus — est porté
 * par `MembreGrille.a_declare`, parce qu'en base une grille vierge et une grille tout
 * décochée sont identiques. */
export interface JourDisponibilite {
  date: string;
  creneaux: Record<string, boolean>;
}

/** Une campagne telle que le sélecteur de fenêtre la montre.
 *
 * Le nombre de réponses est servi AVEC le nombre de cibles : « 8 réponses » ne veut rien dire
 * sans savoir si l'on a écrit à dix personnes ou à quatre cents. */
export interface CampagneGrille {
  id: string;
  intitule: string;
  motif: string;
  motif_libelle: string;
  statut: string;
  periode_debut: string;
  periode_fin: string;
  creneaux: string[];
  nombre_cibles: number;
  nombre_reponses: number;
}

/** Ce que la campagne a demandé à CETTE personne, et ce qu'elle en a fait.
 *
 * `null` veut dire « non ciblée » : on ne lui a rien demandé, elle n'est pas une silencieuse.
 * La clé est absente hors campagne — une colonne « réponse » vide sur une grille libre ferait
 * croire que tout le monde est resté muet. */
export interface CibleGrille {
  etat: 'A_CONTACTER' | 'CONTACTE' | 'A_REPONDU' | 'INJOIGNABLE';
  etat_libelle: string;
  /** Zéro EST une réponse : « je ne suis pas disponible » n'est pas un silence. */
  creneaux_declares: number;
  date_envoi?: string | null;
  date_reponse?: string | null;
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
  /** A-t-elle touché à sa grille ? C'est ce qui dit qui relancer : sans ce drapeau, on ne
   * distinguerait pas quelqu'un qui s'est déclaré indisponible de quelqu'un qui n'a rien
   * rempli. */
  a_declare: boolean;
  jours: JourDisponibilite[];
  /** Présent uniquement quand la grille est ouverte sur une campagne. `null` = non ciblée. */
  cible?: CibleGrille | null;
}

export interface GrilleDisponibilites {
  institution: string;
  institution_nom: string;
  debut: string;
  fin: string;
  jours: string[];
  /** Les créneaux servis, dans l'ordre de la journée. Vient du serveur plutôt que d'une
   * constante locale : l'ordre est métier, et deux listes divergeraient. */
  creneaux: string[];
  membres: MembreGrille[];
  /** Les membres en congé ne sont pas listés — ils ne sont pas mobilisables — mais leur nombre
   * est rendu : une liste qui omet des gens sans le dire laisse chercher. */
  membres_en_conge: number;
  /** Les campagnes consultables de l'association, servies AVEC la grille : le sélecteur de
   * fenêtre en a besoin dès l'ouverture de l'onglet, et un second appel le ferait clignoter. */
  campagnes: CampagneGrille[];
  /** La campagne sur laquelle la fenêtre est ouverte, ou `null` pour la fenêtre libre. */
  campagne: string | null;
  /** La période demandée dépassait le plafond : la grille est coupée, et le dit. */
  tronquee: boolean;
}

// ══ Annuaire enrichi, pour l'arborescence des équipes ═══════════════════════════════════════

/** Place d'une personne DANS une équipe donnée. Calculée par le serveur et non déduite ici :
 * la même personne peut être cadre dans une équipe et simple intervenant dans une autre, et un
 * rôle recomposé côté navigateur finirait par diverger de ce que le serveur retient. */
export type RoleDansEquipe = 'CHEF' | 'REGULATEUR' | 'CADRE' | 'INTERVENANT';

export const LIBELLES_ROLE_EQUIPE: Record<RoleDansEquipe, string> = {
  CHEF: "Chef d'équipe", REGULATEUR: 'Régulateur', CADRE: 'Cadre',
  INTERVENANT: 'Intervenant',
};

/** Une ligne de l'annuaire enrichi (`/api/contacts-institutions/annuaire-association/`).
 *
 * **Les coordonnées sont OPTIONNELLES au sens fort** : elles sont absentes de la réponse quand
 * le lecteur n'est pas au bureau, et non mises à `null`. Les afficher comme « — » affirmerait
 * qu'il n'y a pas de téléphone, alors qu'on n'a simplement pas le droit de le savoir — d'où
 * `coordonneesVisibles` sur l'enveloppe, qui dit lequel des deux cas on est en train de lire. */
export interface MembreAnnuaire {
  utilisateur: string;
  contact: string;
  nom: string;
  fonction: string;
  membre_bureau: boolean;
  statut: StatutMembre;
  competences: { id: string; nom: string }[];
  /** A touché à sa grille de créneaux. Seul signal qui distingue le silence du refus : ce
   * moteur tient « pas de ligne = indisponible » et ne sait pas stocker « non renseigné ». */
  a_declare: boolean;
  /** Sans ressource, la personne est invisible aux campagnes et à la constitution d'équipe. */
  a_ressource: boolean;
  a_fiche: boolean;
  fiche_complete: boolean;
  titres: number;
  titres_verifies: number;
  titres_perimes: number;
  // ── Réservé au bureau : absent sinon ───────────────────────────────────────
  email?: string;
  telephone?: string;
  ville?: string;
  commune_code?: string | null;
  departement_code?: string | null;
  metier?: string;
  aptitude_valide_jusquau?: string | null;
  adhesion_valide_jusquau?: string | null;
}

export interface AnnuaireAssociation {
  institution: string;
  institution_nom: string;
  membres: MembreAnnuaire[];
  coordonnees_visibles: boolean;
  /** `{ equipeId: { utilisateurId: rôle } }`. */
  roles_par_equipe: Record<string, Record<string, RoleDansEquipe>>;
}
