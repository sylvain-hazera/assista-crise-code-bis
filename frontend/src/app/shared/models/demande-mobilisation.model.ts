export type TypeDemandeMobilisation = 'MISE_A_DISPOSITION' | 'SE_RENDRE_A';
export type StatutDemandeMobilisation = 'ACTIVE' | 'REVOQUEE';
export type CibleTypeDemandeMobilisation = 'utilisateur' | 'institution' | 'offre' | null;

/** Voir DemandeMobilisation côté backend (core/models.py) — volontairement nommée "demande" et
 * non "réquisition" : ce n'est pas un acte de réquisition légale, juste une demande formelle
 * tracée. `jeton_verification` est posé en prévision d'une future attestation PDF + QR code
 * (pas encore construite à ce stade). */
export interface DemandeMobilisation {
  id: string;
  crise: string;
  crise_nom: string;
  institution_emettrice: string;
  institution_emettrice_nom: string;
  emetteur: string | null;
  emetteur_nom: string | null;

  // Exactement un des 3 est renseigné — voir cible_type/cible_nom/cible_contact, résolus côté
  // serveur, pour ne jamais dupliquer cette logique ici.
  cible_utilisateur: string | null;
  cible_institution: string | null;
  cible_offre: string | null;
  cible_type: CibleTypeDemandeMobilisation;
  cible_nom: string | null;
  cible_contact: string | null;

  type_demande: TypeDemandeMobilisation;
  type_demande_libelle: string;
  point_operationnel: string | null;
  point_operationnel_nom: string | null;
  lieu_texte: string;
  motif: string;

  statut: StatutDemandeMobilisation;
  statut_libelle: string;
  date_creation: string;
  date_revocation: string | null;
  jeton_verification: string | null;
}

export interface DemandeMobilisationPayload {
  crise: string;
  institution_emettrice: string;
  cible_utilisateur?: string | null;
  cible_institution?: string | null;
  cible_offre?: string | null;
  type_demande: TypeDemandeMobilisation;
  lieu_texte?: string;
  motif?: string;
  point_operationnel?: string | null;
}
