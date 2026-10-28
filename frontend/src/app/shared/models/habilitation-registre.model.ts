/** Habilitation nominative au registre communal des personnes vulnérables
 * (art. R. 121-7 du CASF — voir HabilitationRegistreVulnerables côté backend et
 * BASE-LEGALE-REGISTRE-VULNERABLES.md). */

/** Qualité du désignant, telle qu'il la déclare sur l'honneur. Rien ici n'est vérifiable par la
 * plateforme : c'est l'office même de l'attestation, qui fait porter la responsabilité de la
 * déclaration sur son auteur. */
export type QualiteDesignataire = 'MAIRE' | 'ADJOINT' | 'AGENT';

export interface HabilitationRegistre {
  id: string;
  institution: string;
  institution_nom?: string | null;
  utilisateur: string;
  utilisateur_nom?: string | null;
  utilisateur_email?: string | null;
  fonction?: string;
  accordee_par: string;
  accordee_par_nom?: string | null;
  qualite_accordant: QualiteDesignataire;
  qualite_accordant_libelle?: string;
  attestation_accordant: boolean;
  date_octroi: string;
  date_fin?: string | null;
  actif: boolean;
  retiree_par?: string | null;
  retiree_par_nom?: string | null;
  date_retrait?: string | null;
  motif_retrait?: string;
  /** Calculé serveur : une échéance jugée sur l'horloge du navigateur ne vaut rien. */
  valide: boolean;
  /** Le désigné a-t-il contresigné ? Une habilitation non contresignée n'ouvre aucune fiche. */
  engagement_signe: boolean;
}

/** Réponse de `mon-etat` : tout ce que la page du registre doit savoir avant d'afficher quoi que
 * ce soit. Les deux textes juridiques viennent du serveur et ne sont jamais recopiés ici — un
 * texte qu'on fait signer doit avoir une version et une seule origine. */
export interface EtatRegistreVulnerables {
  institution: string | null;
  institution_nom: string | null;
  habilitation: HabilitationRegistre | null;
  /** Un titre d'accès existe (désignation, délégation, ou administrateur). */
  a_un_titre: boolean;
  lecture_seule_administrateur: boolean;
  engagement_signe: boolean;
  /** Il y a un titre, mais l'engagement reste à prendre : c'est le cas du disclaimer bloquant. */
  engagement_a_signer: boolean;
  engagement_signe_le: string | null;
  engagement_version_signee: string | null;
  engagement_version_courante: string;
  texte_engagement: string;
  rappel_bandeau: string;
  peut_designer: boolean;
}
