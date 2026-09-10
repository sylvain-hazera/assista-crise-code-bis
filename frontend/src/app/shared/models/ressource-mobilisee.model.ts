export interface RessourceMobilisee {
  type: 'personne' | 'materiel';
  nom: string;
  equipe_id: string;
  equipe_nom: string;
  institution: string | null;
  crises: string[];
  centres: string[];
  detail: string | null;
  statut: string | null;
}
