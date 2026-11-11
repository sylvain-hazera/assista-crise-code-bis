import { CommonModule } from '@angular/common';
import { Component, computed, effect, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { BrouillonsEnvoiService } from '../../../../core/brouillons-envoi.service';
import { BrouillonEnvoi } from '../../../../shared/models/brouillon-envoi.model';

/** Fenêtre de relecture d'un message avant son envoi.
 *
 * Montée UNE FOIS dans la coquille de l'application, pas par page : un message peut être retenu
 * par n'importe quelle action, et la placer dans chaque écran concerné demanderait de la poser
 * à 25 endroits — le vingt-sixième l'oublierait.
 *
 * Elle s'ouvre quand le service signale un identifiant, ce que fait l'intercepteur HTTP en
 * lisant l'en-tête posé par le serveur.
 *
 * **Les `[LIEN_n]` doivent être conservés dans le texte.** Ce ne sont pas des abréviations
 * d'affichage : les vraies URL ne sont jamais sorties du serveur et ne sont remises qu'à
 * l'envoi. Un relecteur qui en supprime un envoie un message sans son lien — d'où
 * l'avertissement, et non un blocage : il peut y avoir une raison de le retirer. */
@Component({
  selector: 'app-relecture-envoi',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './relecture-envoi.component.html',
  styleUrl: './relecture-envoi.component.scss',
})
export class RelectureEnvoiComponent {

  brouillon = signal<BrouillonEnvoi | null>(null);
  sujet = signal('');
  corps = signal('');
  chargement = signal(false);
  enCours = signal(false);
  erreur = signal('');
  motifAbandon = signal('');
  demandeAbandon = signal(false);

  /** Placeholders de lien présents dans le texte capturé : ce sont eux qu'il ne faut pas
   * perdre. */
  private liensAttendus = signal<string[]>([]);

  /** Liens retirés par le relecteur. Avertissement et non blocage : il peut y avoir une raison
   * de retirer un lien, mais pas par accident. */
  liensPerdus = computed(() => {
    const texte = this.corps();
    return this.liensAttendus().filter(lien => !texte.includes(lien));
  });

  /** Segments SMS recalculés à la frappe : la facturation est au segment, et un texte de
   * 161 caractères coûte deux fois celui de 160. */
  segments = computed(() => {
    if (this.brouillon()?.canal !== 'SMS') return null;
    const longueur = this.corps().length;
    if (longueur === 0) return { segments: 0, restants: 160 };
    if (longueur <= 160) return { segments: 1, restants: 160 - longueur };
    const nombre = Math.ceil(longueur / 153);
    return { segments: nombre, restants: nombre * 153 - longueur };
  });

  constructor(private service: BrouillonsEnvoiService) {
    // Charge le premier brouillon de la file dès qu'il y en a un, et pas avant : la fenêtre ne
    // doit pas apparaître vide puis se remplir.
    effect(() => {
      const file = this.service.aRelire();
      if (!file.length || this.brouillon() || this.chargement()) return;
      this.charger(file[0]);
    });
  }

  private charger(id: string): void {
    this.chargement.set(true);
    this.erreur.set('');
    this.service.get(id).subscribe({
      next: (brouillon) => {
        this.brouillon.set(brouillon);
        this.sujet.set(brouillon.sujet);
        this.corps.set(brouillon.corps);
        this.liensAttendus.set(brouillon.corps.match(/\[LIEN_\d+\]/g) || []);
        this.chargement.set(false);
      },
      error: () => {
        // Le brouillon est inaccessible (droits, déjà traité ailleurs) : on le retire de la
        // file plutôt que de bloquer la fenêtre sur lui indéfiniment.
        this.chargement.set(false);
        this.service.retirer(id);
      },
    });
  }

  envoyer(): void {
    const brouillon = this.brouillon();
    if (!brouillon || this.enCours()) return;
    if (!this.corps().trim()) {
      this.erreur.set('Le message ne peut pas être vide.');
      return;
    }
    this.enCours.set(true);
    this.erreur.set('');
    this.service.envoyer(brouillon.id, this.sujet(), this.corps()).subscribe({
      next: () => { this.enCours.set(false); this.terminer(brouillon.id); },
      error: (err) => {
        this.enCours.set(false);
        this.erreur.set(err?.error?.error || "Erreur lors de l'envoi.");
      },
    });
  }

  abandonner(): void {
    const brouillon = this.brouillon();
    if (!brouillon || this.enCours()) return;
    const motif = this.motifAbandon().trim();
    if (!motif) {
      this.erreur.set("Un motif est requis : l'action a déjà eu lieu, et personne ne sera "
                      + "prévenu.");
      return;
    }
    this.enCours.set(true);
    this.service.abandonner(brouillon.id, motif).subscribe({
      next: () => { this.enCours.set(false); this.terminer(brouillon.id); },
      error: (err) => {
        this.enCours.set(false);
        this.erreur.set(err?.error?.error || "Erreur lors de l'abandon.");
      },
    });
  }

  /** Remet la fenêtre à zéro et laisse l'effet charger le suivant, s'il y en a un : une action
   * peut avoir produit plusieurs messages (inviter trois membres d'un coup). */
  private terminer(id: string): void {
    this.brouillon.set(null);
    this.sujet.set('');
    this.corps.set('');
    this.liensAttendus.set([]);
    this.motifAbandon.set('');
    this.demandeAbandon.set(false);
    this.service.retirer(id);
  }

  /** Reporter : le brouillon reste à relire et se retrouve dans la liste. Il partira seul au
   * bout de 24 h plutôt que de ne jamais partir. */
  reporter(): void {
    const brouillon = this.brouillon();
    if (!brouillon) return;
    this.brouillon.set(null);
    this.demandeAbandon.set(false);
    this.service.retirer(brouillon.id);
  }
}
