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

  /** Champs de personnalisation du texte (`[PRENOM]`, `[NOM]`…). Montrés au relecteur pour
   * qu'il ne les prenne pas pour une coquille : ils seront remplis, par destinataire, au
   * moment de l'envoi. */
  champsAttendus = signal<string[]>([]);

  /** Combien de messages ce texte représente. 1 = message unique. */
  effectif = computed(() => this.brouillon()?.effectif ?? 1);

  /** Vrai quand ce texte part à plusieurs personnes : l'écran le dit autrement. */
  estUnLot = computed(() => this.effectif() > 1);

  /** Échecs du dernier envoi, nommés : un lot « partiellement envoyé » qu'on croirait complet
   * serait pire qu'un échec franc. */
  echecs = signal<{ destinataires: string[]; motif: string }[]>([]);

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
    // On demande les LOTS et non le brouillon seul : un import de deux cents bénévoles
    // produit deux cents messages identiques à un nom près, et les relire un par un serait
    // une corvée que personne ne ferait. Le lot qui contient l'identifiant annoncé est celui
    // qu'on ouvre — s'il n'y est plus (déjà traité par un collègue), on passe au suivant.
    this.service.lotsARelire().subscribe({
      next: (lots) => {
        this.chargement.set(false);
        const voulu = lots.find(l => l.id === id)
          // L'identifiant annoncé peut ne pas être le REPRÉSENTANT de son lot : le serveur
          // choisit le plus ancien. On retombe alors sur n'importe quel lot en attente.
          || lots.find(l => l.lot && this.service.aRelire().includes(l.id))
          || lots[0];
        if (!voulu) { this.service.retirer(id); return; }
        this.ouvrir(voulu);
        // Les autres messages du même lot n'ont plus à être signalés séparément : ils
        // partiront avec celui-ci.
        if (voulu.id !== id) this.service.retirer(id);
      },
      error: () => {
        this.chargement.set(false);
        this.service.retirer(id);
      },
    });
  }

  private ouvrir(brouillon: BrouillonEnvoi): void {
    this.brouillon.set(brouillon);
    this.sujet.set(brouillon.sujet);
    this.corps.set(brouillon.corps);
    this.liensAttendus.set(brouillon.corps.match(/\[LIEN_\d+\]/g) || []);
    // Les champs de personnalisation présents dans le texte : affichés au relecteur pour
    // qu'il sache que « [PRENOM] » n'est pas une coquille mais un champ qui sera rempli.
    this.champsAttendus.set(
      [...new Set(brouillon.corps.match(/\[[A-Z][A-Z0-9_]*\]/g) || [])]
        .filter(c => !c.startsWith('[LIEN')),
    );
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
    this.echecs.set([]);
    // `envoyerLot` même pour un message isolé : le serveur traite les deux cas, et l'appelant
    // n'a pas à les distinguer.
    this.service.envoyerLot(brouillon.id, this.sujet(), this.corps()).subscribe({
      next: (resultat) => {
        this.enCours.set(false);
        if (resultat.echecs.length) {
          // On NE ferme PAS : le relecteur doit voir qui n'a pas reçu, sinon il croirait le
          // lot complet.
          this.echecs.set(resultat.echecs);
          this.erreur.set(
            `${resultat.envoyes} message(s) envoyé(s), ${resultat.echecs.length} en échec.`);
          this.service.retirer(brouillon.id);
          return;
        }
        this.terminer(brouillon.id);
      },
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
    this.champsAttendus.set([]);
    this.echecs.set([]);
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
