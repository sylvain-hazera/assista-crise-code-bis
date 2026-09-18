import { Observable, merge, timer } from 'rxjs';
import { filter, switchMap } from 'rxjs/operators';

/** Émet dès la souscription, puis toutes les `intervalMs` — mais jamais pendant que l'onglet
 * est en arrière-plan (`document.hidden`), et rafraîchit immédiatement dès qu'il redevient
 * visible plutôt que d'attendre le prochain tick. Évite deux travers d'un `setInterval` naïf :
 * gaspiller des requêtes réseau/batterie sur un onglet minimisé, et laisser l'utilisateur
 * revenir sur une page restée périmée pendant qu'il regardait ailleurs.
 *
 * `switchMap` annule un appel encore en vol si un nouveau tick survient avant sa réponse
 * (réseau lent) — jamais deux requêtes qui se chevauchent pour la même source. */
export function pollWhileVisible<T>(fetchFn: () => Observable<T>, intervalMs: number): Observable<T> {
  const visibiliteRegagnee$ = new Observable<void>(subscriber => {
    if (typeof document === 'undefined') return undefined;
    const gestionnaire = () => {
      if (!document.hidden) subscriber.next();
    };
    document.addEventListener('visibilitychange', gestionnaire);
    return () => document.removeEventListener('visibilitychange', gestionnaire);
  });

  return merge(timer(0, intervalMs), visibiliteRegagnee$).pipe(
    filter(() => typeof document === 'undefined' || !document.hidden),
    switchMap(() => fetchFn()),
  );
}
