export interface AppNotification {
  id: string;
  utilisateur: string;
  dossier: string | null;
  dossier_numero: string | null;
  crise: string | null;
  titre: string;
  message: string;
  lu: boolean;
  date_creation: string;
}

/** Réponse légère de NotificationViewSet.resume — destinée à un polling fréquent, voir
 * pollWhileVisible : la liste complète (AppNotification[]) n'est redemandée que si ce résumé a
 * changé depuis le dernier poll. */
export interface ResumeNotifications {
  count_non_lues: number;
  derniere_notification_le: string | null;
}
