import { Injectable } from '@angular/core';

/**
 * Quelle collectivité l'utilisateur consulte, quand ce n'est pas la sienne.
 *
 * Une association agréée n'a pas de territoire propre : le sien est l'ensemble des communes
 * sur lesquelles une collectivité l'a acceptée, pour une crise ou par convention (voir
 * `zone_scoping.communes_accordees`). Les écrans territoriaux doivent donc savoir **laquelle**
 * elle regarde — c'est le « en précisant la collectivité » demandé le 28/10/2026.
 *
 * Porté par un service plutôt qu'un paramètre d'URL : le choix vaut pour toute la consultation
 * et traverse plusieurs écrans. Mémorisé dans `localStorage` pour survivre à un rechargement,
 * parce que refaire ce choix à chaque F5 en pleine crise serait une friction absurde — mais
 * **jamais considéré comme un droit** : le serveur revérifie à chaque appel que la commune est
 * dans le périmètre accordé et répond 403 sinon. Ce qui est stocké ici n'est qu'une préférence
 * d'affichage.
 */
@Injectable({ providedIn: 'root' })
export class CollectiviteConsulteeService {
  private static readonly CLE = 'assista.collectivite-consultee';

  private commune: string | null = this.lire();

  /** Code INSEE choisi, ou null quand l'utilisateur regarde sa propre collectivité. */
  get communeChoisie(): string | null {
    return this.commune;
  }

  choisir(communeCode: string | null): void {
    this.commune = communeCode || null;
    try {
      if (this.commune) {
        localStorage.setItem(CollectiviteConsulteeService.CLE, this.commune);
      } else {
        localStorage.removeItem(CollectiviteConsulteeService.CLE);
      }
    } catch {
      // Navigation privée ou stockage bloqué : le choix reste valable pour cette page, il ne
      // survivra simplement pas au rechargement. Préférable à une page qui refuse de s'ouvrir.
    }
  }

  private lire(): string | null {
    try {
      return localStorage.getItem(CollectiviteConsulteeService.CLE);
    } catch {
      return null;
    }
  }
}
