import { CategorieInterlocuteurPCS, ModeAlertePCS } from './interlocuteur-alerte-pcs.model';

export type StatutNotificationPCS = 'EN_ATTENTE' | 'ENVOYE_AUTO' | 'ECHEC_AUTO' | 'CONFIRME_PAR_CONTACT' | 'CONFIRME_MANUEL';

export type ReponseContactPCS = 'PAS_DE_RAPPEL' | 'MERCI_RAPPELER' | 'AUTRE';

/** Une ligne par (crise, interlocuteur) -- checklist + suivi d'envoi automatique, voir
 * NotificationAlertePCS côté backend. Créée dès la déclaration de la crise, SANS envoi (voir
 * NotificationAlertePCSService.envoyerLot pour l'envoi explicite après relecture). */
export interface NotificationAlertePCS {
  id: string;
  crise: string;
  interlocuteur: string | null;
  nom_snapshot: string;
  organisme_snapshot: string;
  categorie_snapshot: CategorieInterlocuteurPCS;
  institution_nom_snapshot: string;
  canal_tente: ModeAlertePCS;
  /** Pourquoi la ligne a été préparée : l'ouverture de la crise, ou celle d'un centre d'accueil. */
  motif?: 'CRISE' | 'CENTRE';
  point_nom_snapshot?: string;
  /** Cochée d'avance : l'annuaire dit de prévenir cette personne à ce moment-là. */
  preselectionne?: boolean;
  statut: StatutNotificationPCS;
  detail_erreur: string | null;
  message_envoye: string | null;
  reponse_contact: ReponseContactPCS | null;
  commentaire_contact: string | null;
  date_creation: string;
  date_envoi_auto: string | null;
  date_confirmation: string | null;
  confirme_par: string | null;
  confirme_par_nom: string | null;
}
