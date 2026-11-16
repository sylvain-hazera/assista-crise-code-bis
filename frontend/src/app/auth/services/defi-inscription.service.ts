import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, signal } from '@angular/core';
import { Observable, firstValueFrom, from } from 'rxjs';
import { environment } from '../../../environments/environment';
import { DefiInscription, DefiResolu, resoudreDefi } from './defi-calcul';

/** Le contrôle anti-robot de la création de compte, côté navigateur.
 *
 * La personne n'a rien à lire ni à résoudre : le navigateur demande un défi au serveur dès
 * l'ouverture du formulaire, fait le calcul pendant qu'elle le remplit, et joint le résultat à
 * l'envoi. Si le serveur juge le calcul insuffisant (réponse 428 : formulaire envoyé très vite,
 * beaucoup d'inscriptions depuis le même réseau…), on en demande un plus long et on renvoie le
 * même formulaire, sans rien lui redemander. Voir core/defi_inscription.py côté serveur. */
@Injectable({ providedIn: 'root' })
export class DefiInscriptionService {
  private url = `${environment.apiUrl}/inscription/defi/`;
  private enPreparation: Promise<DefiResolu | null> | null = null;

  /** Vrai pendant qu'un envoi attend la fin d'un calcul : l'écran dit « vérification en cours ». */
  readonly verification = signal(false);

  constructor(private http: HttpClient) {}

  /** Demande un défi et le résout en arrière-plan. À appeler à l'ouverture du formulaire. */
  preparer(): void {
    this.enPreparation = this.obtenir();
  }

  /** `null` si le serveur ne répond pas ou ne connaît pas encore les défis (satellite pas à
   * jour) : l'envoi part alors sans, et c'est le serveur qui décide. */
  private async obtenir(): Promise<DefiResolu | null> {
    try {
      const defi = await firstValueFrom(this.http.get<DefiInscription>(this.url));
      const nombre = await resoudreDefi(defi);
      return nombre === null ? null : { ...defi, nombre };
    } catch {
      return null;
    }
  }

  /** Envoie avec un défi résolu, et recommence avec un défi neuf si le serveur en redemande. */
  avecDefi<T>(envoyer: (defi: DefiResolu | null) => Observable<T>): Observable<T> {
    return from(this.envoyer(envoyer));
  }

  private async envoyer<T>(envoyer: (defi: DefiResolu | null) => Observable<T>): Promise<T> {
    let preparation = this.enPreparation ?? this.obtenir();
    this.enPreparation = null;            // un défi ne sert qu'une fois
    try {
      for (let essai = 0; ; essai++) {
        this.verification.set(true);
        const defi = await preparation;
        this.verification.set(false);
        try {
          return await firstValueFrom(envoyer(defi));
        } catch (erreur) {
          const aRefaire = erreur instanceof HttpErrorResponse && erreur.status === 428;
          if (!aRefaire || essai >= 2) {
            // La personne va corriger et renvoyer (adresse déjà prise, mot de passe
            // refusé…) : le défi suivant se prépare pendant ce temps.
            this.preparer();
            throw erreur;
          }
          preparation = this.obtenir();
        }
      }
    } finally {
      this.verification.set(false);
    }
  }
}
