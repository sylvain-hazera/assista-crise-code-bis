export interface OfferMessage {
  id: string;
  offer: string;
  auteur_equipe: string | null;         // UUID de l'utilisateur côté équipe, null si envoyé par le propriétaire de l'offre
  auteur_equipe_nom?: string | null;
  contenu: string;
  date_creation: string;
}
