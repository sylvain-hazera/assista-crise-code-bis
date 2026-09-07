export interface JournalCollectivite {
  id: string;
  institution: string;
  crise: string;                  // UUID de la Crisis (FK) — une institution peut être
                                   // impliquée sur plusieurs crises actives simultanément,
                                   // le journal est rattaché à une crise précise.
  crise_nom: string | null;
  auteur: string | null;
  auteur_nom: string;
  contenu: string;
  date_creation: string;
}
