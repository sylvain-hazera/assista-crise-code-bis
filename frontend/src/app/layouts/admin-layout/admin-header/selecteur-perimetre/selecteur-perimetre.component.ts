import { Component, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AuthService } from '../../../../auth/services/auth.service';
import { EtatPerimetre, PerimetreService } from '../../../../services/perimetre.service';
import { UserRole } from '../../../../shared/models/user.model';

/** « Je regarde… » : le périmètre de consultation d'un administrateur (voir PerimetreService).
 *
 * N'apparaît que pour un administrateur : pour tout autre compte il n'y a rien à choisir, le
 * serveur ignore l'en-tête. Changer de périmètre recharge la page, comme le font déjà la
 * bascule démo/production et le changement d'institution active : il décide de ce que montrent
 * toutes les pages ouvertes, et les rafraîchir une par une serait faux à la première oubliée. */
@Component({
  selector: 'app-selecteur-perimetre',
  standalone: true,
  imports: [FormsModule],
  templateUrl: './selecteur-perimetre.component.html',
  styleUrl: './selecteur-perimetre.component.scss',
})
export class SelecteurPerimetreComponent implements OnInit {
  readonly MIENNE = PerimetreService.MIENNE;
  readonly TOUT = PerimetreService.TOUT;

  etat: EtatPerimetre | null = null;
  choix = PerimetreService.MIENNE;

  constructor(private perimetre: PerimetreService, private auth: AuthService) {}

  get visible(): boolean {
    return this.auth.getEffectiveRole() === UserRole.ADMIN && !!this.etat?.administrateur;
  }

  ngOnInit(): void {
    if (this.auth.getEffectiveRole() !== UserRole.ADMIN) { return; }
    this.choix = this.perimetre.choix;
    this.perimetre.etat().subscribe({
      next: (etat) => {
        this.etat = etat;
        // Le choix gardé ne désigne plus rien (institution supprimée depuis) : retour à la
        // sienne plutôt que de rester sur un périmètre que le serveur refuse.
        if (etat.mode === 'INVALIDE') { this.choisir(this.MIENNE); return; }
        // Sans institution à soi, « la mienne » n'existe pas : le serveur montre tout, et le
        // sélecteur doit le dire.
        if (this.choix === this.MIENNE && !etat.mienne) { this.choix = this.TOUT; }
      },
      error: () => { this.etat = null; },
    });
  }

  /** Les autres institutions : la sienne a déjà son entrée en tête de liste. */
  get autres(): { id: string; nom: string; type_libelle: string }[] {
    const mienne = this.etat?.mienne?.id;
    return (this.etat?.institutions ?? []).filter(i => i.id !== mienne);
  }

  /** Vrai quand l'administrateur ne regarde pas son institution : le sélecteur le souligne. */
  get horsDeChezSoi(): boolean {
    return this.choix !== this.MIENNE;
  }

  choisir(choix: string): void {
    if (!choix || choix === this.perimetre.choix) { return; }
    this.perimetre.definir(choix);
    this.recharger();
  }

  /** À part pour que les tests puissent l'observer sans recharger la page de test. */
  recharger(): void {
    window.location.reload();
  }
}
