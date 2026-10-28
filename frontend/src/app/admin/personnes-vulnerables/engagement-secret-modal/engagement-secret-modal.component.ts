import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { HabilitationRegistreService } from '../../../services/vulnerabilite.service';
import { EtatRegistreVulnerables } from '../../../shared/models/habilitation-registre.model';

/**
 * Engagement au secret professionnel, présenté à la première connexion au registre après
 * l'attribution des droits (art. R. 121-7 du CASF).
 *
 * **Bloquant à dessein**, et sur trois points qui ne sont pas de l'ergonomie :
 *
 * 1. Pas de croix de fermeture, pas de fermeture au clic sur le fond, pas d'échappement par
 *    Échap. On signe ou on quitte la page : un engagement qu'on peut écarter d'un clic de côté
 *    n'engage à rien, et le serveur ne renverra de toute façon aucune fiche avant la signature
 *    (voir core/vulnerabilites.py).
 * 2. Le texte vient du serveur (`etat.texte_engagement`) et n'est pas recopié ici. Ce qui est
 *    signé doit avoir une version et une seule origine ; si le texte change, le serveur
 *    redemande la signature, et un texte figé dans le bundle ferait signer autre chose que ce
 *    qui est enregistré.
 * 3. La case à cocher est distincte du bouton. Un seul bouton « J'accepte » se clique sans
 *    lire ; cocher puis valider est le geste minimal qui rend l'acceptation explicite, ce que
 *    le serveur exige par ailleurs (`accepte` doit valoir vrai).
 *
 * Le libellé du bouton nomme l'acte (« Je m'engage ») plutôt que l'effet technique : c'est ce
 * que la personne fait, et c'est ce dont le journal gardera la trace à son nom.
 */
@Component({
  selector: 'app-engagement-secret-modal',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './engagement-secret-modal.component.html',
  styleUrl: './engagement-secret-modal.component.scss',
})
export class EngagementSecretModalComponent {
  @Input({ required: true }) etat!: EtatRegistreVulnerables;

  @Output() signe = new EventEmitter<void>();

  /** Case cochée : séparée du bouton pour que l'acceptation soit un geste conscient. */
  accepte = false;
  enCours = false;
  errorMessage = '';

  constructor(private habilitationService: HabilitationRegistreService) {}

  /** Les paragraphes sont rendus un à un plutôt qu'en un bloc préformaté : un texte juridique
   * doit rester lisible et se reflower sur un écran étroit, ce qu'un <pre> ne fait pas. */
  get paragraphes(): string[] {
    return (this.etat.texte_engagement || '')
      .split('\n')
      .map(p => p.trim())
      .filter(p => p.length > 0);
  }

  get designePar(): string | null {
    const habilitation = this.etat.habilitation;
    if (!habilitation) return null;
    const qui = habilitation.accordee_par_nom || 'la mairie';
    const titre = habilitation.qualite_accordant_libelle || '';
    return titre ? `${qui} (${titre.toLowerCase()})` : qui;
  }

  signer(): void {
    if (!this.accepte || this.enCours) return;
    this.enCours = true;
    this.errorMessage = '';
    this.habilitationService.signerEngagement().subscribe({
      next: () => {
        this.enCours = false;
        this.signe.emit();
      },
      error: (err) => {
        this.enCours = false;
        this.errorMessage = err?.error?.detail
          || "L'engagement n'a pas pu être enregistré. Réessayez ; sans lui, le registre reste fermé.";
      },
    });
  }
}
