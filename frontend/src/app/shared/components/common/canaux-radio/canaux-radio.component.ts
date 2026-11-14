import { Component, Input, OnChanges } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { RelaisLocalService, RelaisVisible } from '../../../../services/relais-local.service';
import { EntreePlan } from '../../../mesh/plan-canaux';

/**
 * Plan de canaux d'une radio Meshtastic branchée : ce qu'elle porte, ce qu'on propose, et le
 * bouton pour l'appliquer.
 *
 * Règle du 14/11/2026 (backend/core/canaux_locaux.py) : Fr_Balise et Fr_EMCOM d'abord, puis le
 * canal de la crise et celui de la commune selon la place — en proposant d'en supprimer d'autres
 * s'il n'y en a pas assez. **Rien n'est écrit sur la radio sans le clic de la personne**, et les
 * canaux en clé publique s'affichent avec leur avertissement.
 */
@Component({
  selector: 'app-canaux-radio',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './canaux-radio.component.html',
  styleUrl: './canaux-radio.component.scss',
})
export class CanauxRadioComponent implements OnChanges {
  @Input({ required: true }) relais!: RelaisVisible;

  /** Ajouts cochés (par nom) et emplacements à libérer (par index). */
  retenus = new Set<string>();
  aSupprimer = new Set<number>();
  enCours = false;
  resultat = '';
  erreur = '';
  private signature = '';

  constructor(private moteur: RelaisLocalService) {}

  ngOnChanges(): void {
    // Cases cochées par défaut — tous les ajouts proposés — mais seulement quand la proposition
    // change, sinon chaque rafraîchissement du moteur effacerait les choix de la personne.
    const p = this.relais.plan?.proposition;
    const signature = JSON.stringify(p?.ajouts.map(a => a.entree.nom) ?? []);
    if (signature !== this.signature) {
      this.signature = signature;
      this.retenus = new Set(p?.ajouts.map(a => a.entree.nom) ?? []);
      this.aSupprimer = new Set();
    }
  }

  get plan() { return this.relais.plan; }

  get titreIsolement(): string {
    return this.plan?.isolee
      ? "Passerelle isolée : elle ne réémet que sa crise et sa commune, et ce qu'elle entend "
        + "n'est réémis par aucune autre passerelle."
      : 'Passerelle ouverte au réseau : elle réémet aussi ce qui ne concerne pas sa commune.';
  }

  get nomsIndisponibles(): string {
    return (this.plan?.proposition.indisponibles ?? []).map(e => e.nom).join(', ');
  }

  /** Combien d'emplacements manquent encore avec les choix actuels. */
  get manqueEncore(): number {
    const p = this.plan?.proposition;
    if (!p) { return 0; }
    return Math.max(0, this.retenus.size - p.libres.length - this.aSupprimer.size);
  }

  /** Au moins un canal en clé publique va être écrit : l'avertissement doit être lu avant. */
  get publicsRetenus(): boolean {
    return !!this.plan?.proposition.ajouts.some(a => this.retenus.has(a.entree.nom) && a.entree.public
      && a.entree.role !== 'communautaire');
  }

  libelleRole(e: EntreePlan): string {
    return e.role === 'crise' ? 'crise' : e.role === 'commune' ? 'commune' : 'communautaire';
  }

  nomDe(index: number): string {
    const e = this.plan?.emplacements.find(x => x.index === index);
    if (!e || e.role === 0) { return '— libre —'; }
    return e.nom || (index === 0 ? 'primaire (préréglage)' : 'sans nom');
  }

  basculerAjout(nom: string): void {
    if (this.retenus.has(nom)) { this.retenus.delete(nom); } else { this.retenus.add(nom); }
  }

  basculerSuppression(index: number): void {
    if (this.aSupprimer.has(index)) { this.aSupprimer.delete(index); } else { this.aSupprimer.add(index); }
  }

  async appliquer(): Promise<void> {
    const p = this.plan?.proposition;
    if (!p) { return; }
    this.enCours = true;
    this.erreur = '';
    this.resultat = '';
    try {
      // Dans l'ordre du plan : les communautaires d'abord, s'il manque de la place à la fin.
      const retenus = p.ajouts.map(a => a.entree).filter(e => this.retenus.has(e.nom));
      const sansPlace = await this.moteur.appliquerPlan(
        this.relais.compagnonId, retenus, [...this.aSupprimer]);
      this.resultat = sansPlace.length
        ? `Appliqué. Faute de place : ${sansPlace.map(e => e.nom).join(', ')}.`
        : 'Canaux écrits sur la radio.';
    } catch (e) {
      this.erreur = this.moteur.lisible(e);
    } finally {
      this.enCours = false;
    }
  }
}
