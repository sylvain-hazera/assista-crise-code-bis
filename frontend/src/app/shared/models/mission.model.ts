export interface Mission {
  id?: string;
  titre: string;
  description?: string | null;
  crise: string;
  crise_nom?: string;
  equipe_ids: string[];
  equipes_noms?: string[];
  statut: 'EN_PREPARATION' | 'EN_COURS' | 'TERMINEE';
  date_creation?: string;
  date_cloture?: string | null;
  /** Institution qui commande la mission. Posée par le serveur à la création. */
  institution?: string | null;
  institution_nom?: string | null;
  /** Mission d'intérêt général (garde du feu, ronde…) : demandée par l'institution elle-même,
   * elle peut ouvrir des dossiers génériques, sans demandeur. */
  interet_general?: boolean;
  dossiers_generiques?: { id: string; numero: string; titre: string; statut: string; date_creation: string }[];
  /** Salon Matrix de la mission (« 1 mission = 1 canal ») ; `pret` dès qu'il existe côté Matrix. */
  salon_matrix?: { id: string; room_id: string | null; pret: boolean } | null;
}

/** Ce qu'on envoie pour ouvrir un dossier générique sur une mission d'intérêt général. */
export interface OuvertureDossierGenerique {
  description: string;
  titre?: string;
  equipe_id?: string;
  priorite?: string;
}
