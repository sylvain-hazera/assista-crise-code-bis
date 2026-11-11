import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { BrouillonsEnvoiService } from '../../core/brouillons-envoi.service';
import { BrouillonEnvoi } from '../../shared/models/brouillon-envoi.model';

/** Les messages retenus pour relecture et pas encore traités.
 *
 * La fenêtre de relecture s'ouvre d'elle-même juste après l'action qui a produit le message
 * (voir `brouillonsEnvoiInterceptor`). Cette page existe pour les cas où elle a été manquée :
 * onglet fermé, page rechargée, « Plus tard » cliqué, ou message produit par un collègue.
 *
 * Elle est le filet qui rend le délai de 24 h acceptable : sans un endroit où retrouver ce qui
 * attend, un message reporté ne serait plus visible nulle part jusqu'à son envoi automatique. */
@Component({
  selector: 'app-messages-a-relire',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './messages-a-relire.component.html',
  styleUrl: './messages-a-relire.component.scss',
})
export class MessagesARelireComponent implements OnInit {

  brouillons = signal<BrouillonEnvoi[]>([]);
  chargement = signal(true);
  erreur = signal('');

  constructor(private service: BrouillonsEnvoiService) {}

  ngOnInit(): void {
    this.charger();
  }

  charger(): void {
    this.chargement.set(true);
    this.erreur.set('');
    this.service.aRelireListe().subscribe({
      next: (liste) => { this.brouillons.set(liste); this.chargement.set(false); },
      error: () => {
        this.chargement.set(false);
        this.erreur.set("Impossible de charger les messages en attente.");
      },
    });
  }

  /** Remet le message dans la file du service : la fenêtre de relecture, montée dans la
   * coquille de l'application, s'ouvre alors dessus. On ne duplique pas l'éditeur ici — un
   * second exemplaire divergerait du premier à la première évolution. */
  relire(brouillon: BrouillonEnvoi): void {
    this.service.signaler([brouillon.id]);
    // Retiré de cette liste : il y reviendra au prochain chargement s'il n'a pas été traité.
    this.brouillons.update(liste => liste.filter(b => b.id !== brouillon.id));
  }

  /** Âge en heures, pour montrer ce qui approche de l'envoi automatique. */
  heuresDepuis(iso: string): number {
    return Math.floor((Date.now() - new Date(iso).getTime()) / 3600000);
  }

  /** Vrai quand le message partira bientôt tout seul (délai de 24 h côté serveur). */
  presqueExpire(brouillon: BrouillonEnvoi): boolean {
    return this.heuresDepuis(brouillon.date_creation) >= 18;
  }
}
