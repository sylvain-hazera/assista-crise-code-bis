/** Demande la permission d'afficher des notifications navigateur si elle n'a encore jamais été
 * tranchée ("default") — jamais redemandée après un refus explicite. Sans effet si l'API
 * n'existe pas (navigateur trop ancien, contexte non sécurisé type http:// non-localhost). */
export function demanderPermissionNotificationNavigateur(): void {
  if (typeof Notification === 'undefined') return;
  if (Notification.permission === 'default') {
    Notification.requestPermission().catch(() => {});
  }
}

/** Affiche une notification navigateur — utile quand l'onglet est en arrière-plan (l'utilisateur
 * ne regarde pas déjà la cloche à l'écran) : voir pollWhileVisible, qui continue de tourner tant
 * que l'onglet est visible mais peut aussi tourner juste après un retour au premier plan, d'où
 * la vérification explicite de `document.hidden` par l'appelant plutôt qu'ici — cette fonction
 * ne fait qu'afficher, sans décider quand c'est pertinent. Sans effet si la permission n'a pas
 * été accordée (jamais de blocage silencieux à gérer côté appelant). */
export function afficherNotificationNavigateur(titre: string, options?: NotificationOptions): void {
  if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;
  try {
    new Notification(titre, options);
  } catch {
    // Certains navigateurs mobiles interdisent `new Notification()` hors service worker —
    // dégrade silencieusement, la cloche in-app reste le repli fiable dans tous les cas.
  }
}
