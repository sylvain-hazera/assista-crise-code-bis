import { Component, Input, OnChanges, OnDestroy, SimpleChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Observable, of, Subscription } from 'rxjs';
import { catchError, tap } from 'rxjs/operators';

import { MatrixMessage } from '../../../shared/models/team.model';
import { pollWhileVisible } from '../../../shared/utils/polling.util';

// Aligné sur EquipeMessagerieMeshComponent (8s) plutôt que plus agressif : chaque tick relaie
// une requête HTTP jusqu'à Synapse côté backend (voir salon_matrix_messages), pas la peine de
// solliciter ça plus souvent qu'un chat d'équipe classique n'en a besoin.
const INTERVALLE_POLLING_MS = 8_000;

/** Chat Matrix intégré, générique (salon d'équipe ou d'institution) : l'appelant fournit les
 * fonctions de chargement/envoi. Relais backend avec le jeton du bot (core/matrix.py). */
@Component({
  selector: 'app-matrix-salon-chat',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './matrix-salon-chat.component.html',
  styleUrl: './matrix-salon-chat.component.scss',
})
export class MatrixSalonChatComponent implements OnChanges, OnDestroy {

  /** Clé arbitraire identifiant la source (ex: id d'équipe, ou `${institutionId}:${type}`) --
   * ne sert qu'à détecter un changement de salon et relancer le polling, jamais utilisée pour
   * appeler l'API directement (voir chargerMessages/envoyerMessage). */
  @Input() cle!: string;
  @Input() titre = "Salon d'équipe";
  @Input() pretACharger = true;
  @Input() chargerMessages!: () => Observable<{ messages: MatrixMessage[] }>;
  @Input() envoyerMessage!: (texte: string, urgent?: boolean) => Observable<{ messages: MatrixMessage[] }>;
  /** Case « urgent », ouverte à tous ; désactivée par défaut (le chat d'équipe l'active). */
  @Input() autoriserUrgent = false;
  /** Bouton "Vu" par message -- réservé aux cadres (régulateur/chef d'équipe/institutionnel),
   * fourni par l'appelant qui seul sait qui est cadre ici. Absent = pas de bouton "Vu" du tout
   * (ex: salons d'institution, hors périmètre de cet accusé de réception). */
  @Input() cadre = false;
  @Input() reagir?: (eventId: string) => Observable<{ status: string }>;

  chargement = true;
  erreur = '';
  messages: MatrixMessage[] = [];
  nouveauMessage = '';
  urgent = false;
  envoiEnCours = false;
  reactionEnCoursEventId: string | null = null;

  private pollingSub?: Subscription;

  ngOnChanges(changes: SimpleChanges): void {
    if ((changes['cle'] || changes['pretACharger']) && this.cle && this.pretACharger) {
      this.chargement = true;
      this.erreur = '';
      this.pollingSub?.unsubscribe();
      this.pollingSub = pollWhileVisible(() => this.rafraichir(), INTERVALLE_POLLING_MS).subscribe();
    }
  }

  ngOnDestroy(): void {
    this.pollingSub?.unsubscribe();
  }

  private rafraichir() {
    return this.chargerMessages().pipe(
      tap((reponse) => {
        this.messages = reponse.messages;
        this.erreur = '';
        this.chargement = false;
      }),
      catchError(() => {
        this.erreur = 'Connexion au salon perdue.';
        this.chargement = false;
        return of(null);
      }),
    );
  }

  envoyer(): void {
    const texte = this.nouveauMessage.trim();
    if (!texte) return;
    this.envoiEnCours = true;
    this.envoyerMessage(texte, this.urgent).subscribe({
      next: (reponse) => {
        this.messages = reponse.messages;
        this.nouveauMessage = '';
        this.urgent = false;
        this.envoiEnCours = false;
      },
      error: () => {
        this.erreur = "Échec de l'envoi du message.";
        this.envoiEnCours = false;
      },
    });
  }

  marquerVu(message: MatrixMessage): void {
    if (!this.reagir || this.reactionEnCoursEventId) return;
    this.reactionEnCoursEventId = message.event_id;
    this.reagir(message.event_id).subscribe({
      next: () => { this.reactionEnCoursEventId = null; this.rafraichir().subscribe(); },
      error: () => { this.reactionEnCoursEventId = null; },
    });
  }
}
